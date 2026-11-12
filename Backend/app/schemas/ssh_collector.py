from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ADDRESS_PATTERN = r"^[A-Za-z0-9.:-]+$"


class SSHScanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    address: str = Field(min_length=1, max_length=255, pattern=ADDRESS_PATTERN)
    port: int = Field(default=22, ge=1, le=65535)


class SSHInstallRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9][A-Za-z0-9_. -]*$")
    address: str = Field(min_length=1, max_length=255, pattern=ADDRESS_PATTERN)
    port: int = Field(default=22, ge=1, le=65535)
    username: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z_][A-Za-z0-9_.-]*$")
    auth_method: Literal["password", "private_key"]
    secret: str = Field(min_length=1, max_length=20000, repr=False)
    host_key_fingerprint: str = Field(pattern=r"^SHA256:[A-Za-z0-9+/]+=*$")
    long_running_seconds: int = Field(default=3600, ge=60, le=31536000)
