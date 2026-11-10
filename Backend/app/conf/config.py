import secrets
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_DIR = Path(__file__).resolve().parents[3]
BACKEND_DIR = PROJECT_DIR / "Backend"
STORE_DIR = PROJECT_DIR / "Store"
DB_PATH = STORE_DIR / "serverpulse.db"
DB_MIGRATIONS_DIR = BACKEND_DIR / "db" / "migrations"

DB_POOL_SIZE = 5
DB_TIMEOUT_SECONDS = 10.0
DB_BUSY_TIMEOUT_MS = 5000


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SERVERPULSE_", env_file=".env")

    host: str = "127.0.0.1"
    port: int = 8000
    cors_origins: list[str] = ["http://localhost:5173"]
    jwt_secret_key: str = Field(default_factory=lambda: secrets.token_urlsafe(32))
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 30
    jwt_refresh_token_expire_days: int = 1


settings = Settings()
