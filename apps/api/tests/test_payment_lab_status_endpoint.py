from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes import payment_lab_status
from app.core.config import Settings, get_settings
from app.core.database import get_database_session
from app.main import app
from app.services.payment_lab_live_run_service import (
    PaymentLabLiveRun,
    PaymentLabLiveRunNotFoundError,
    PaymentLabLiveStage,
    PaymentLabLiveStep,
    PaymentLabLiveStepStatus,
)

NOW = datetime(2026, 8, 26, 19, 30, tzinfo=UTC)
RUN_ID = UUID("94000000-0000-0000-0000-000000000001")
CLIENT_ID = UUID("94000000-0000-0000-0000-000000000002")


async def override_database_session() -> AsyncIterator[AsyncSession]:
    yield MagicMock(spec=AsyncSession)


def build_settings() -> Settings:
    return Settings(payment_lab_access_token=SecretStr("lab-secret"))


@pytest.fixture(autouse=True)
def dependency_overrides() -> Iterator[None]:
    app.dependency_overrides[get_database_session] = override_database_session
    app.dependency_overrides[get_settings] = build_settings
    yield
    app.dependency_overrides.clear()


def build_live_run() -> PaymentLabLiveRun:
    return PaymentLabLiveRun(
        payment_lab_run_id=RUN_ID,
        client_request_id=CLIENT_ID,
        mode="guided",
        provenance="razorpay_test",
        persisted_status="checkout_ready",
        current_stage=PaymentLabLiveStage.CHECKOUT,
        terminal=False,
        poll_after_milliseconds=1000,
        amount_minor=349_900,
        currency="INR",
        payment_method="netbanking",
        provider_order_id="order_status_endpoint",
        provider_order_status="created",
        failure_code=None,
        checkout_expires_at=NOW + timedelta(minutes=10),
        created_at=NOW,
        updated_at=NOW,
        steps=(
            PaymentLabLiveStep(
                key="payment_attempt",
                label="Payment attempt",
                status=PaymentLabLiveStepStatus.COMPLETED,
                occurred_at=NOW,
                detail="Razorpay Test Mode order created",
            ),
        ),
        payment=None,
        agent=None,
        actions=(),
        outcome=None,
    )


def test_reads_protected_provider_backed_live_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    load_run = AsyncMock(return_value=build_live_run())
    monkeypatch.setattr(payment_lab_status, "load_payment_lab_live_run", load_run)

    with TestClient(app) as client:
        response = client.get(
            f"/payment-lab/runs/{RUN_ID}",
            headers={"X-ReclaimRail-Lab-Token": "lab-secret"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["payment_lab_run_id"] == str(RUN_ID)
    assert body["current_stage"] == "checkout"
    assert body["poll_after_milliseconds"] == 1000
    assert body["steps"][0]["status"] == "completed"
    assert "lab-secret" not in response.text


def test_rejects_missing_access_before_reading_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    load_run = AsyncMock()
    monkeypatch.setattr(payment_lab_status, "load_payment_lab_live_run", load_run)

    with TestClient(app) as client:
        response = client.get(f"/payment-lab/runs/{RUN_ID}")

    assert response.status_code == 401
    load_run.assert_not_awaited()


def test_returns_not_found_for_unknown_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        payment_lab_status,
        "load_payment_lab_live_run",
        AsyncMock(side_effect=PaymentLabLiveRunNotFoundError()),
    )

    with TestClient(app) as client:
        response = client.get(
            f"/payment-lab/runs/{RUN_ID}",
            headers={"X-ReclaimRail-Lab-Token": "lab-secret"},
        )

    assert response.status_code == 404
    assert response.json()["detail"] == "Payment Lab run not found"
