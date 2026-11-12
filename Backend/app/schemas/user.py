from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, SecretStr, StringConstraints

MAX_AVATAR_LENGTH = 200_000
AVATAR_DATA_URL_PATTERN = r"^data:image/(png|jpeg|webp);base64,[A-Za-z0-9+/]+={0,2}$"
DisplayName = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)
]


class RegisterUserRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str = Field(min_length=3, max_length=64, pattern=r"^[A-Za-z0-9_.-]+$")
    password: SecretStr = Field(min_length=8, max_length=128)


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str = Field(min_length=1, max_length=64)
    password: SecretStr = Field(min_length=1, max_length=128)


class UpdateProfileRequest(BaseModel):
    """Fields that are omitted are left unchanged; an explicit null clears them."""

    model_config = ConfigDict(extra="forbid")

    display_name: DisplayName | None = None
    avatar: str | None = Field(
        default=None, max_length=MAX_AVATAR_LENGTH, pattern=AVATAR_DATA_URL_PATTERN
    )


class ChangePasswordRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    current_password: SecretStr = Field(min_length=1, max_length=128)
    new_password: SecretStr = Field(min_length=8, max_length=128)


class UserResponse(BaseModel):
    id: int
    username: str
    is_admin: bool
    enabled: bool
    created_at: str
    display_name: str | None = None
    avatar: str | None = None


class LoginResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    refresh_token: str = Field(min_length=1)


class RefreshResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
