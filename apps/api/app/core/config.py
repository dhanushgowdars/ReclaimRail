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
    gemini_model_name: str = Field(
        default="gemini-3.6-flash",
        min_length=1,
        max_length=128,
    )
    gemini_temperature: float = Field(default=0.1, ge=0.0, le=1.0)
    gemini_max_output_tokens: int = Field(default=4096, ge=256, le=4096)

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

    payment_consumer_group_name: str = "reclaimrail:payment-projectors:v1"
    payment_consumer_batch_size: int = Field(
        default=25,
        ge=1,
        le=100,
    )
    payment_consumer_block_milliseconds: int = Field(
        default=1000,
        ge=1,
        le=60_000,
    )
    payment_consumer_claim_idle_milliseconds: int = Field(
        default=60_000,
        ge=1000,
        le=3_600_000,
    )
    payment_consumer_error_retry_seconds: float = Field(
        default=2.0,
        ge=0.1,
        le=300.0,
    )
    payment_consumer_dead_letter_stream_name: str = "reclaimrail:payment-events:dead-letter:v1"
    payment_consumer_dead_letter_stream_max_length: int = Field(
        default=10_000,
        ge=100,
        le=1_000_000,
    )

    incident_payment_methods: tuple[str, ...] = (
        "upi",
        "card",
        "netbanking",
        "wallet",
    )
    incident_currency: str = Field(
        default="INR",
        min_length=3,
        max_length=3,
    )
    incident_window_minutes: int = Field(
        default=5,
        ge=1,
        le=60,
    )
    incident_baseline_window_count: int = Field(
        default=12,
        ge=6,
        le=288,
    )
    incident_poll_interval_seconds: float = Field(
        default=60.0,
        ge=1.0,
        le=3600.0,
    )
    recovery_action_batch_size: int = Field(
        default=25,
        ge=1,
        le=100,
    )
    recovery_action_poll_interval_seconds: float = Field(
        default=2.0,
        ge=0.1,
        le=300.0,
    )
    recovery_action_claim_timeout_seconds: int = Field(
        default=120,
        ge=10,
        le=3600,
    )
    recovery_action_max_attempts: int = Field(
        default=3,
        ge=1,
        le=20,
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
