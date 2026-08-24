import pytest
from pydantic import ValidationError

from app.integrations.razorpay.webhooks import (
    compute_payload_sha256,
    compute_signature_sha256,
    parse_webhook_envelope,
    verify_webhook_signature,
)

RAW_BODY = (
    b'{"entity":"event","event":"payment.failed",'
    b'"contains":["payment"],"payload":{},'
    b'"created_at":1787550000}'
)
WEBHOOK_SECRET = "reclaimrail-test-secret"
VALID_SIGNATURE = "02f27f49bdfd385affc32b39bde4dfb3615e6005f4b259729ab222d3856b3671"
PAYLOAD_SHA256 = "8dcaa86dc51bfa01e07c01caa552c7de48eb0d69411bf52a11498024d27ed73c"


def test_verifies_known_valid_signature() -> None:
    assert verify_webhook_signature(
        RAW_BODY,
        VALID_SIGNATURE,
        WEBHOOK_SECRET,
    )


def test_rejects_signature_after_payload_tampering() -> None:
    tampered_body = RAW_BODY.replace(
        b"payment.failed",
        b"payment.captured",
    )

    assert not verify_webhook_signature(
        tampered_body,
        VALID_SIGNATURE,
        WEBHOOK_SECRET,
    )


def test_rejects_incorrect_signature() -> None:
    assert not verify_webhook_signature(
        RAW_BODY,
        "0" * 64,
        WEBHOOK_SECRET,
    )


def test_computes_stable_payload_hash() -> None:
    assert compute_payload_sha256(RAW_BODY) == PAYLOAD_SHA256


def test_hashes_signature_before_audit_storage() -> None:
    signature_hash = compute_signature_sha256(VALID_SIGNATURE)

    assert len(signature_hash) == 64
    assert signature_hash != VALID_SIGNATURE


def test_parses_valid_envelope_after_verification() -> None:
    envelope = parse_webhook_envelope(RAW_BODY)

    assert envelope.entity == "event"
    assert envelope.event == "payment.failed"
    assert envelope.contains == ["payment"]
    assert envelope.created_at == 1787550000


def test_rejects_envelope_without_event_name() -> None:
    invalid_body = b'{"entity":"event","contains":["payment"],"payload":{},"created_at":1787550000}'

    with pytest.raises(ValidationError):
        parse_webhook_envelope(invalid_body)


def test_rejects_negative_provider_timestamp() -> None:
    invalid_body = (
        b'{"entity":"event","event":"payment.failed",'
        b'"contains":["payment"],"payload":{},"created_at":-1}'
    )

    with pytest.raises(ValidationError):
        parse_webhook_envelope(invalid_body)
