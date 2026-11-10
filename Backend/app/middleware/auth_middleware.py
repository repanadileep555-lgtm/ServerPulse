from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.auth.jwt_service import JWTService, TokenError, get_jwt_service

bearer_scheme = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class AuthenticatedUser:
    subject: str


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    jwt_service: Annotated[JWTService, Depends(get_jwt_service)],
) -> AuthenticatedUser:
    unauthorized = {"WWW-Authenticate": "Bearer"}
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers=unauthorized,
        )
    try:
        claims = jwt_service.validate_access_token(credentials.credentials)
    except TokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
            headers=unauthorized,
        ) from exc
    return AuthenticatedUser(subject=claims["sub"])
