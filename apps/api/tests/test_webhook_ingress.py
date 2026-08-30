from collections.abc import AsyncIterator, Iterator
from typing import cast
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes import webhooks as webhook_routes
from app.core.config import Settings, get_settings
from app.core.database import get_database_session
from app.webhook_main import app


def override_settings() -> Settings:
    return Settings(
        app_env="test",
        razorpay_webhook_secret=SecretStr("webhook-ingress-test-secret"),
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


def test_exposes_the_signature_verified_webhook_route(
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
        content=b"{}",
        headers={"X-Razorpay-Event-Id": "evt_ingress_test"},
    )

    assert response.status_code == 401
    assert response.json() == {"detail": "Webhook rejected"}
    rejection.assert_awaited_once()


@pytest.mark.parametrize(
    "private_path",
    [
        "/docs",
        "/openapi.json",
        "/health/live",
        "/payment-lab/runs",
        "/recovery/dashboard/summary",
    ],
)
def test_does_not_expose_private_application_routes(
    client: TestClient,
    private_path: str,
) -> None:
    response = client.get(private_path)

    assert response.status_code == 404
