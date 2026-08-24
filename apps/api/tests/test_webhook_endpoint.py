import hashlib
import hmac
from collections.abc import AsyncIterator, Iterator
from typing import cast
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes import webhooks as webhook_routes
from app.core.config import Settings, get_settings
from app.core.database import get_database_session
from app.integrations.razorpay.webhooks import MAX_WEBHOOK_BODY_BYTES
from app.main import app
from app.services.webhook_ingestion import WebhookIngestionResult

WEBHOOK_SECRET = "reclaimrail-endpoint-test-secret"
PROVIDER_EVENT_ID = "evt_reclaimrail_test_001"
CANONICAL_EVENT_ID = UUID("11111111-1111-4111-8111-111111111111")
RAW_BODY = (
    b'{"entity":"event","event":"payment.failed",'
    b'"contains":["payment"],"payload":{},'
    b'"created_at":1787550000}'
)


def sign_payload(raw_body: bytes) -> str:
    return hmac.new(
        WEBHOOK_SECRET.encode("utf-8"),
        raw_body,
        hashlib.sha256,
    ).hexdigest()


def override_settings() -> Settings:
    return Settings(
        app_env="test",
        razorpay_webhook_secret=SecretStr(WEBHOOK_SECRET),
    )


async def override_database_session() -> AsyncIterator[AsyncSession]:
    yield cast(AsyncSession, object())


@pytest.fixture
def client() -> Iterator[TestClient]:
    app.dependency_overrides[get_settings] = override_settings
    app.dependency_overrides[get_database_session] = override_database_session

    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()


def test_accepts_verified_webhook(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ingestion = AsyncMock(
        return_value=WebhookIngestionResult(
            canonical_event_id=CANONICAL_EVENT_ID,
            provider_event_id=PROVIDER_EVENT_ID,
            duplicate=False,
        ),
    )
    rejection = AsyncMock()

    monkeypatch.setattr(
        webhook_routes,
        "ingest_verified_webhook",
        ingestion,
    )
    monkeypatch.setattr(
        webhook_routes,
        "record_rejected_webhook",
        rejection,
    )

    response = client.post(
        "/webhooks/razorpay",
        content=RAW_BODY,
        headers={
            "X-Razorpay-Signature": sign_payload(RAW_BODY),
            "X-Razorpay-Event-Id": PROVIDER_EVENT_ID,
        },
    )

    assert response.status_code == 202
    assert response.json() == {
        "status": "accepted",
        "event_id": str(CANONICAL_EVENT_ID),
        "provider_event_id": PROVIDER_EVENT_ID,
    }
    ingestion.assert_awaited_once()
    rejection.assert_not_awaited()


def test_returns_200_for_duplicate_webhook(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        webhook_routes,
        "ingest_verified_webhook",
        AsyncMock(
            return_value=WebhookIngestionResult(
                canonical_event_id=CANONICAL_EVENT_ID,
                provider_event_id=PROVIDER_EVENT_ID,
                duplicate=True,
            ),
        ),
    )

    response = client.post(
        "/webhooks/razorpay",
        content=RAW_BODY,
        headers={
            "X-Razorpay-Signature": sign_payload(RAW_BODY),
            "X-Razorpay-Event-Id": PROVIDER_EVENT_ID,
        },
    )

    assert response.status_code == 200
    assert response.json()["status"] == "duplicate"


def test_rejects_invalid_signature(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rejection = AsyncMock()
    ingestion = AsyncMock()

    monkeypatch.setattr(
        webhook_routes,
        "record_rejected_webhook",
        rejection,
    )
    monkeypatch.setattr(
        webhook_routes,
        "ingest_verified_webhook",
        ingestion,
    )

    response = client.post(
        "/webhooks/razorpay",
        content=RAW_BODY,
        headers={
            "X-Razorpay-Signature": "0" * 64,
            "X-Razorpay-Event-Id": PROVIDER_EVENT_ID,
        },
    )

    assert response.status_code == 401
    rejection.assert_awaited_once()
    ingestion.assert_not_awaited()


def test_rejects_missing_signature(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rejection = AsyncMock()

    monkeypatch.setattr(
        webhook_routes,
        "record_rejected_webhook",
        rejection,
    )

    response = client.post(
        "/webhooks/razorpay",
        content=RAW_BODY,
        headers={
            "X-Razorpay-Event-Id": PROVIDER_EVENT_ID,
        },
    )

    assert response.status_code == 401
    rejection.assert_awaited_once()


def test_rejects_signed_malformed_payload(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    malformed_body = b'{"entity":"event"}'
    rejection = AsyncMock()

    monkeypatch.setattr(
        webhook_routes,
        "record_rejected_webhook",
        rejection,
    )

    response = client.post(
        "/webhooks/razorpay",
        content=malformed_body,
        headers={
            "X-Razorpay-Signature": sign_payload(malformed_body),
            "X-Razorpay-Event-Id": PROVIDER_EVENT_ID,
        },
    )

    assert response.status_code == 400
    rejection.assert_awaited_once()


def test_rejects_oversized_payload(
    client: TestClient,
) -> None:
    oversized_body = b"x" * (MAX_WEBHOOK_BODY_BYTES + 1)

    response = client.post(
        "/webhooks/razorpay",
        content=oversized_body,
        headers={
            "X-Razorpay-Signature": "0" * 64,
            "X-Razorpay-Event-Id": PROVIDER_EVENT_ID,
        },
    )

    assert response.status_code == 413


def test_rejects_missing_event_id(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rejection = AsyncMock()
    ingestion = AsyncMock()

    monkeypatch.setattr(
        webhook_routes,
        "record_rejected_webhook",
        rejection,
    )
    monkeypatch.setattr(
        webhook_routes,
        "ingest_verified_webhook",
        ingestion,
    )

    response = client.post(
        "/webhooks/razorpay",
        content=RAW_BODY,
        headers={
            "X-Razorpay-Signature": sign_payload(RAW_BODY),
        },
    )

    assert response.status_code == 400
    rejection.assert_awaited_once()
    ingestion.assert_not_awaited()
