import asyncio
import sqlite3

from pwdlib import PasswordHash

from app.auth.jwt_service import JWTService, TokenError
from app.db.db_pool import DatabasePool
from app.schemas.user import (
    LoginRequest,
    LoginResponse,
    RefreshResponse,
    RegisterUserRequest,
    UserResponse,
)

password_hasher = PasswordHash.recommended()


class DuplicateUsernameError(Exception):
    """The requested username is already registered."""


class InvalidCredentialsError(Exception):
    """The credentials do not identify an enabled account."""


class InvalidRefreshTokenError(Exception):
    """The refresh token is invalid or its account is no longer enabled."""


def _verify_password(password: str, stored_hash: str | None) -> bool:
    if stored_hash is None:
        # Do comparable password work even when the username does not exist.
        password_hasher.hash(password)
        return False
    return password_hasher.verify(password, stored_hash)


class UserService:
    def __init__(self, pool: DatabasePool, jwt_service: JWTService) -> None:
        self._pool = pool
        self._jwt_service = jwt_service

    async def create_user(self, request: RegisterUserRequest) -> UserResponse:
        return await self._insert_user(request, is_admin=False)

    async def create_admin(self, request: RegisterUserRequest) -> UserResponse:
        return await self._insert_user(request, is_admin=True)

    async def is_enabled_admin(self, user_id: str) -> bool:
        row = await self._pool.fetch_one(
            "SELECT is_admin, enabled FROM users WHERE id = ?", (user_id,)
        )
        return row is not None and bool(row["is_admin"]) and bool(row["enabled"])

    async def get_enabled_user(self, user_id: str) -> UserResponse | None:
        row = await self._pool.fetch_one(
            """
            SELECT id, username, is_admin, enabled, created_at
            FROM users WHERE id = ? AND enabled = 1
            """,
            (user_id,),
        )
        return UserResponse(**dict(row)) if row is not None else None

    async def list_users(self) -> list[UserResponse]:
        rows = await self._pool.fetch_all(
            """
            SELECT id, username, is_admin, enabled, created_at
            FROM users ORDER BY created_at, id
            """
        )
        return [UserResponse(**dict(row)) for row in rows]

    async def _insert_user(self, request: RegisterUserRequest, *, is_admin: bool) -> UserResponse:
        password_hash = await asyncio.to_thread(
            password_hasher.hash, request.password.get_secret_value()
        )
        try:
            row = await self._pool.fetch_one(
                """
                INSERT INTO users (username, password_hash, is_admin)
                VALUES (?, ?, ?)
                RETURNING id, username, is_admin, enabled, created_at
                """,
                (request.username, password_hash, int(is_admin)),
            )
        except sqlite3.IntegrityError as exc:
            if exc.sqlite_errorcode == sqlite3.SQLITE_CONSTRAINT_UNIQUE:
                raise DuplicateUsernameError("Username is already registered") from exc
            raise
        if row is None:
            raise RuntimeError("User insert did not return the created account")
        return UserResponse(**dict(row))

    async def login(self, request: LoginRequest) -> LoginResponse:
        row = await self._pool.fetch_one(
            "SELECT id, password_hash, enabled FROM users WHERE username = ?",
            (request.username,),
        )
        valid = await asyncio.to_thread(
            _verify_password,
            request.password.get_secret_value(),
            row["password_hash"] if row is not None else None,
        )
        if row is None or not valid or not row["enabled"]:
            raise InvalidCredentialsError("Invalid username or password")

        token = self._jwt_service.create_access_token(str(row["id"]))
        refresh_token = self._jwt_service.create_refresh_token(str(row["id"]))
        updated = await self._pool.execute(
            """
            UPDATE users SET last_login_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
            WHERE id = ? AND enabled = 1
            """,
            (row["id"],),
        )
        if updated != 1:
            raise InvalidCredentialsError("Invalid username or password")
        return LoginResponse(access_token=token, refresh_token=refresh_token)

    async def refresh(self, refresh_token: str) -> RefreshResponse:
        try:
            claims = self._jwt_service.validate_refresh_token(refresh_token)
            user_id = int(claims["sub"])
        except (TokenError, ValueError) as exc:
            raise InvalidRefreshTokenError("Invalid refresh token") from exc

        row = await self._pool.fetch_one("SELECT enabled FROM users WHERE id = ?", (user_id,))
        if row is None or not row["enabled"]:
            raise InvalidRefreshTokenError("Invalid refresh token")
        return RefreshResponse(access_token=self._jwt_service.create_access_token(str(user_id)))