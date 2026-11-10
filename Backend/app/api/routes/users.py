from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.auth.jwt_service import JWTService, get_jwt_service
from app.db.db_client import get_database_pool
from app.db.db_pool import DatabasePool
from app.middleware.auth_middleware import AuthenticatedUser, get_current_user
from app.schemas.user import (
    LoginRequest,
    LoginResponse,
    RefreshRequest,
    RefreshResponse,
    RegisterUserRequest,
    UserResponse,
)
from app.services.user_service import (
    DuplicateUsernameError,
    InvalidCredentialsError,
    InvalidRefreshTokenError,
    UserService,
)

router = APIRouter(prefix="/users", tags=["users"])


async def get_user_service(
    pool: Annotated[DatabasePool, Depends(get_database_pool)],
    jwt_service: Annotated[JWTService, Depends(get_jwt_service)],
) -> UserService:
    return UserService(pool, jwt_service)


async def require_admin(
    current_user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    service: Annotated[UserService, Depends(get_user_service)],
) -> AuthenticatedUser:
    if not await service.is_enabled_admin(current_user.subject):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Admin privileges required"
        )
    return current_user


@router.get("/me", response_model=UserResponse)
async def me(
    current_user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    service: Annotated[UserService, Depends(get_user_service)],
) -> UserResponse:
    user = await service.get_enabled_user(current_user.subject)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Account is not available",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


@router.get("", response_model=list[UserResponse])
async def list_users(
    _admin: Annotated[AuthenticatedUser, Depends(require_admin)],
    service: Annotated[UserService, Depends(get_user_service)],
) -> list[UserResponse]:
    return await service.list_users()


@router.post("/admins", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_admin(
    request: RegisterUserRequest,
    _admin: Annotated[AuthenticatedUser, Depends(require_admin)],
    service: Annotated[UserService, Depends(get_user_service)],
) -> UserResponse:
    try:
        return await service.create_admin(request)
    except DuplicateUsernameError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc


@router.post("/create", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(
    request: RegisterUserRequest,
    service: Annotated[UserService, Depends(get_user_service)],
) -> UserResponse:
    try:
        return await service.create_user(request)
    except DuplicateUsernameError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc


@router.post("/login", response_model=LoginResponse)
async def login(
    request: LoginRequest,
    service: Annotated[UserService, Depends(get_user_service)],
) -> LoginResponse:
    try:
        return await service.login(request)
    except InvalidCredentialsError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


@router.post("/refresh", response_model=RefreshResponse)
async def refresh(
    request: RefreshRequest,
    service: Annotated[UserService, Depends(get_user_service)],
) -> RefreshResponse:
    try:
        return await service.refresh(request.refresh_token)
    except InvalidRefreshTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
