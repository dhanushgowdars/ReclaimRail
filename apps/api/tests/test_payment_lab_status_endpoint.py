from collections.abc import AsyncIterator, Iterator
from dataclasses import replace
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
    PaymentLabLiveBusinessState,
    PaymentLabLiveRun,
    PaymentLabLiveRunNotFoundError,
    PaymentLabLiveStage,
    PaymentLabLiveStep,
    PaymentLabLiveStepStatus,
    PaymentLabVerifiedReplayNotFoundError,
)
from app.services.worker_supervision_service import (
    WorkerFleetHealth,
    WorkerFleetStatus,
    WorkerHealth,
    WorkerHealthStatus,
    WorkerName,
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
        business_state=PaymentLabLiveBusinessState.AWAITING_ORIGINAL_PAYMENT,
        state_label="Waiting for provider payment result",
        current_stage=PaymentLabLiveStage.CHECKOUT,
        active_step_key="verified_failure",
        waiting_reason="Waiting for signed provider evidence",
        automation_complete=False,
        financial_outcome_terminal=False,
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
    assert body["business_state"] == "awaiting_original_payment"
    assert body["active_step_key"] == "verified_failure"
    assert body["automation_complete"] is False
    assert body["responsible_worker"] is None
    assert body["stalled_reason"] is None
    assert body["poll_after_milliseconds"] == 1000
    assert body["steps"][0]["status"] == "completed"
    assert "lab-secret" not in response.text


def test_live_run_identifies_unhealthy_responsible_worker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    live_run = replace(
        build_live_run(),
        business_state=PaymentLabLiveBusinessState.DIAGNOSING,
        current_stage=PaymentLabLiveStage.AGENT,
        active_step_key="agent_recommendation",
    )
    worker = WorkerHealth(
        name=WorkerName.PAYMENT_LAB_RECOVERY,
        status=WorkerHealthStatus.DOWN,
        instance_id=None,
        heartbeat_age_seconds=None,
        started_at=None,
        last_heartbeat_at=None,
        last_success_at=None,
        last_failure_at=None,
        consecutive_failures=0,
        last_error_type=None,
        metrics={},
    )
    fleet = WorkerFleetHealth(
        status=WorkerFleetStatus.DEGRADED,
        workers=(worker,),
        healthy_count=0,
        expected_count=8,
        generated_at=NOW,
    )
    monkeypatch.setattr(
        payment_lab_status,
        "load_payment_lab_live_run",
        AsyncMock(return_value=live_run),
    )
    monkeypatch.setattr(
        payment_lab_status,
        "get_redis_client",
        MagicMock(return_value=object()),
    )
    monkeypatch.setattr(
        payment_lab_status,
        "load_worker_fleet_health",
        AsyncMock(return_value=fleet),
    )

    with TestClient(app) as client:
        response = client.get(
            f"/payment-lab/runs/{RUN_ID}",
            headers={"X-ReclaimRail-Lab-Token": "lab-secret"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["responsible_worker"] == "payment_lab_recovery"
    assert body["responsible_worker_status"] == "down"
    assert "payment_lab_recovery worker is down" in body["stalled_reason"]


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


def test_reads_latest_completed_test_mode_replay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    replay = replace(build_live_run(), terminal=True, persisted_status="completed")
    load_replay = AsyncMock(return_value=replay)
    monkeypatch.setattr(
        payment_lab_status,
        "load_latest_verified_payment_lab_replay",
        load_replay,
    )

    with TestClient(app) as client:
        response = client.get(
            "/payment-lab/replays/latest",
            headers={"X-ReclaimRail-Lab-Token": "lab-secret"},
        )

    assert response.status_code == 200
    assert response.json()["payment_lab_run_id"] == str(RUN_ID)
    load_replay.assert_awaited_once()


def test_reports_when_no_completed_replay_exists(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        payment_lab_status,
        "load_latest_verified_payment_lab_replay",
        AsyncMock(side_effect=PaymentLabVerifiedReplayNotFoundError()),
    )

    with TestClient(app) as client:
        response = client.get(
            "/payment-lab/replays/latest",
            headers={"X-ReclaimRail-Lab-Token": "lab-secret"},
        )

    assert response.status_code == 404
    assert response.json()["detail"] == "No completed Razorpay Test Mode replay is available yet"
