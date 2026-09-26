"""Environment configuration. Relative storage/database paths are anchored to backend/."""
from pathlib import Path
from typing import Literal
from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BACKEND_DIR / ".env", extra="ignore")
    app_env: Literal["development", "test", "production"] = "development"
    database_url: str = f"sqlite:///{(BACKEND_DIR / 'packsure.db').as_posix()}"
    jwt_secret_key: SecretStr
    jwt_algorithm: Literal["HS256"] = "HS256"
    access_token_expire_minutes: int = Field(default=60, ge=1, le=1440)
    upload_dir: Path = BACKEND_DIR / "uploads"
    max_upload_size_mb: int = Field(default=10, ge=1, le=100)
    allowed_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    ocr_worker_python: Path = BACKEND_DIR / ".ocr-venv" / "Scripts" / "python.exe"
    ocr_timeout_seconds: int = Field(default=300, ge=10, le=1200)
    ocr_model_cache_dir: Path = BACKEND_DIR / ".ocr-cache"
    report_dir: Path = BACKEND_DIR / "reports"
    login_rate_limit_attempts: int = Field(default=8, ge=3, le=100)
    login_rate_limit_window_seconds: int = Field(default=300, ge=60, le=3600)
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    @model_validator(mode="after")
    def validate_config(self):
        secret = self.jwt_secret_key.get_secret_value()
        if len(secret) < 32 or secret.lower().startswith("replace"):
            raise ValueError("Set JWT_SECRET_KEY to a random secret of at least 32 characters.")
        if not self.upload_dir.is_absolute():
            self.upload_dir = (BACKEND_DIR / self.upload_dir).resolve()
        if not self.report_dir.is_absolute():
            self.report_dir = (BACKEND_DIR / self.report_dir).resolve()
        if not self.ocr_worker_python.is_absolute():
            self.ocr_worker_python = (BACKEND_DIR / self.ocr_worker_python).resolve()
        if not self.ocr_model_cache_dir.is_absolute():
            self.ocr_model_cache_dir = (BACKEND_DIR / self.ocr_model_cache_dir).resolve()
        if self.database_url.startswith("sqlite:///./"):
            self.database_url = "sqlite:///" + (BACKEND_DIR / self.database_url[12:]).as_posix()
        if self.app_env == "production" and not self.database_url.startswith("postgresql+psycopg://"):
            raise ValueError("Production requires a PostgreSQL DATABASE_URL.")
        if "*" in self.origins:
            raise ValueError("Use explicit ALLOWED_ORIGINS, not a wildcard.")
        return self

    @property
    def origins(self):
        return [origin.strip() for origin in self.allowed_origins.split(",") if origin.strip()]


settings = Settings()
