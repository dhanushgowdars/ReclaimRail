from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "ReclaimRail API"
    app_version: str = "0.1.0"
    app_env: Literal["development", "test", "production"] = "development"

    database_url: SecretStr | None = None
    redis_url: SecretStr | None = None

    razorpay_key_id: SecretStr | None = None
    razorpay_key_secret: SecretStr | None = None
    razorpay_webhook_secret: SecretStr | None = None
    gemini_api_key: SecretStr | None = None

    outbox_stream_name: str = "reclaimrail:webhook-events:v1"
    outbox_batch_size: int = Field(default=25, ge=1, le=100)
    outbox_poll_interval_seconds: float = Field(
        default=1.0,
        ge=0.1,
        le=60.0,
    )
    outbox_claim_timeout_seconds: int = Field(
        default=60,
        ge=5,
        le=3600,
    )
    outbox_max_attempts: int = Field(default=5, ge=1, le=20)
    outbox_retry_base_seconds: float = Field(
        default=2.0,
        ge=0.1,
        le=300.0,
    )
    outbox_retry_max_seconds: float = Field(
        default=300.0,
        ge=1.0,
        le=3600.0,
    )
    outbox_stream_max_length: int = Field(
        default=10_000,
        ge=100,
        le=1_000_000,
    )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="RECLAIMRAIL_",
        case_sensitive=False,
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
