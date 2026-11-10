import asyncio
import sqlite3

from pwdlib import PasswordHash

from app.auth.jwt_service import JWTService
from app.db.db_pool import DatabasePool
from app.schemas.user import LoginRequest, LoginResponse, RegisterUserRequest, UserResponse

password_hasher = PasswordHash.recommended()


class DuplicateUsernameError(Exception):
    """The requested username is already registered."""


class InvalidCredentialsError(Exception):
    """The credentials do not identify an enabled account."""


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
        password_hash = await asyncio.to_thread(
            password_hasher.hash, request.password.get_secret_value()
        )
        try:
            row = await self._pool.fetch_one(
                """
                INSERT INTO users (username, password_hash)
                VALUES (?, ?)
                RETURNING id, username, is_admin, enabled, created_at
                """,
                (request.username, password_hash),
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
        updated = await self._pool.execute(
            """
            UPDATE users SET last_login_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
            WHERE id = ? AND enabled = 1
            """,
            (row["id"],),
        )
        if updated != 1:
            raise InvalidCredentialsError("Invalid username or password")
        return LoginResponse(access_token=token)