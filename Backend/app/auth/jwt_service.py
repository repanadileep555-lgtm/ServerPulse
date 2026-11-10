from datetime import UTC, datetime, timedelta
from functools import lru_cache
from typing import Any

import jwt

from app.conf.config import settings

ACCESS_TOKEN_TYPE = "access"
REFRESH_TOKEN_TYPE = "refresh"
REQUIRED_CLAIMS = ["sub", "iat", "exp", "type"]


class TokenError(Exception):
    """Raised when a token is malformed, expired, tampered with, or of the wrong type."""


class JWTService:
    def __init__(
        self,
        secret_key: str,
        algorithm: str,
        access_token_expire_minutes: int,
        refresh_token_expire_days: int = 1,
    ) -> None:
        self._secret_key = secret_key
        self._algorithm = algorithm
        self._access_token_ttl = timedelta(minutes=access_token_expire_minutes)
        self._refresh_token_ttl = timedelta(days=refresh_token_expire_days)

    def create_access_token(self, subject: str, claims: dict[str, Any] | None = None) -> str:
        return self._create_token(subject, ACCESS_TOKEN_TYPE, self._access_token_ttl, claims)

    def create_refresh_token(self, subject: str) -> str:
        return self._create_token(subject, REFRESH_TOKEN_TYPE, self._refresh_token_ttl)

    def validate_access_token(self, token: str) -> dict[str, Any]:
        return self._validate_token(token, ACCESS_TOKEN_TYPE)

    def validate_refresh_token(self, token: str) -> dict[str, Any]:
        return self._validate_token(token, REFRESH_TOKEN_TYPE)

    def _create_token(
        self,
        subject: str,
        token_type: str,
        ttl: timedelta,
        claims: dict[str, Any] | None = None,
    ) -> str:
        now = datetime.now(UTC)
        # Reserved claims are set last so callers cannot override them.
        payload = {
            **(claims or {}),
            "sub": subject,
            "type": token_type,
            "iat": now,
            "exp": now + ttl,
        }
        return jwt.encode(payload, self._secret_key, algorithm=self._algorithm)

    def _validate_token(self, token: str, expected_type: str) -> dict[str, Any]:
        try:
            claims = jwt.decode(
                token,
                self._secret_key,
                algorithms=[self._algorithm],
                options={"require": REQUIRED_CLAIMS},
            )
        except jwt.InvalidTokenError as exc:
            raise TokenError(str(exc)) from exc

        if claims["type"] != expected_type:
            raise TokenError(f"Token type must be '{expected_type}'")
        return claims


@lru_cache
def get_jwt_service() -> JWTService:
    return JWTService(
        secret_key=settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
        access_token_expire_minutes=settings.jwt_access_token_expire_minutes,
        refresh_token_expire_days=settings.jwt_refresh_token_expire_days,
    )
