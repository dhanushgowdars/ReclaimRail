import hashlib
import hmac

from pydantic import BaseModel, ConfigDict, Field

MAX_WEBHOOK_BODY_BYTES = 1_048_576


class RazorpayWebhookEnvelope(BaseModel):
    model_config = ConfigDict(
        extra="allow",
        strict=True,
    )

    entity: str
    account_id: str | None = None
    event: str = Field(min_length=1, max_length=128)
    contains: list[str] = Field(default_factory=list)
    payload: dict[str, object]
    created_at: int = Field(
        ge=0,
        le=253_402_300_799,
    )


def compute_payload_sha256(raw_body: bytes) -> str:
    return hashlib.sha256(raw_body).hexdigest()


def compute_signature_sha256(signature: str) -> str:
    return hashlib.sha256(signature.encode("utf-8")).hexdigest()


def verify_webhook_signature(
    raw_body: bytes,
    signature: str,
    webhook_secret: str,
) -> bool:
    expected_signature = hmac.new(
        webhook_secret.encode("utf-8"),
        raw_body,
        hashlib.sha256,
    ).hexdigest()

    return hmac.compare_digest(
        expected_signature,
        signature,
    )


def parse_webhook_envelope(
    raw_body: bytes,
) -> RazorpayWebhookEnvelope:
    return RazorpayWebhookEnvelope.model_validate_json(raw_body)
