from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.auth.jwt_service import JWTService, get_jwt_service
from app.db.db_client import get_database_pool
from app.db.db_pool import DatabasePool
from app.schemas.user import LoginRequest, LoginResponse, RegisterUserRequest, UserResponse
from app.services.user_service import (
    DuplicateUsernameError,
    InvalidCredentialsError,
    UserService,
)

router = APIRouter(prefix="/users", tags=["users"])


async def get_user_service(
    pool: Annotated[DatabasePool, Depends(get_database_pool)],
    jwt_service: Annotated[JWTService, Depends(get_jwt_service)],
) -> UserService:
    return UserService(pool, jwt_service)


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
