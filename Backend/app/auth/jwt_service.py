from datetime import UTC, datetime, timedelta
from functools import lru_cache
from typing import Any

import jwt

from app.conf.config import settings

ACCESS_TOKEN_TYPE = "access"
REQUIRED_CLAIMS = ["sub", "iat", "exp", "type"]


class TokenError(Exception):
    """Raised when a token is malformed, expired, tampered with, or of the wrong type."""


class JWTService:
    def __init__(self, secret_key: str, algorithm: str, access_token_expire_minutes: int) -> None:
        self._secret_key = secret_key
        self._algorithm = algorithm
        self._access_token_ttl = timedelta(minutes=access_token_expire_minutes)

    def create_access_token(self, subject: str, claims: dict[str, Any] | None = None) -> str:
        now = datetime.now(UTC)
        # Reserved claims are set last so callers cannot override them.
        payload = {
            **(claims or {}),
            "sub": subject,
            "type": ACCESS_TOKEN_TYPE,
            "iat": now,
            "exp": now + self._access_token_ttl,
        }
        return jwt.encode(payload, self._secret_key, algorithm=self._algorithm)

    def validate_access_token(self, token: str) -> dict[str, Any]:
        try:
            claims = jwt.decode(
                token,
                self._secret_key,
                algorithms=[self._algorithm],
                options={"require": REQUIRED_CLAIMS},
            )
        except jwt.InvalidTokenError as exc:
            raise TokenError(str(exc)) from exc

        if claims["type"] != ACCESS_TOKEN_TYPE:
            raise TokenError("Token is not an access token")
        return claims


@lru_cache
def get_jwt_service() -> JWTService:
    return JWTService(
        secret_key=settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
        access_token_expire_minutes=settings.jwt_access_token_expire_minutes,
    )
