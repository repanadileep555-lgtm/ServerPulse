from pydantic import BaseModel, ConfigDict, Field, SecretStr


class RegisterUserRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str = Field(min_length=3, max_length=64, pattern=r"^[A-Za-z0-9_.-]+$")
    password: SecretStr = Field(min_length=8, max_length=128)


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str = Field(min_length=1, max_length=64)
    password: SecretStr = Field(min_length=1, max_length=128)


class UserResponse(BaseModel):
    id: int
    username: str
    is_admin: bool
    enabled: bool
    created_at: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
