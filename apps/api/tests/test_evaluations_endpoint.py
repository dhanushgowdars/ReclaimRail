from collections.abc import AsyncIterator
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes import evaluations
from app.core.database import get_database_session
from app.db.models.evaluation import EvaluationRun
from app.main import app
from app.services.evaluation_service import EvaluationMetrics


async def override_database_session() -> AsyncIterator[AsyncSession]:
    yield MagicMock(spec=AsyncSession)


@pytest.fixture(autouse=True)
def database_session_override() -> AsyncIterator[None]:
    app.dependency_overrides[get_database_session] = override_database_session
    yield
    app.dependency_overrides.clear()


def build_run() -> EvaluationRun:
    return EvaluationRun(
        id=uuid4(),
        run_key="track3-controlled-batch-v1",
        label="Controlled Track 3 batch evaluation",
        provenance="controlled_synthetic",
        currency="INR",
        scenario_count=100,
        policy_version="deterministic-recovery-policy-v1",
        audit_root_hash="a" * 64,
        created_at=datetime.now(UTC),
    )


def build_metrics() -> EvaluationMetrics:
    return EvaluationMetrics(
        payments_evaluated=100,
        failed_or_at_risk=27,
        recovery_eligible=19,
        recovery_attempted=16,
        successfully_recovered=11,
        recovered_minor=1_176_000,
        baseline_recovered_minor=0,
        incremental_recovered_minor=1_176_000,
        pending_minor=442_000,
        unsafe_actions_blocked=3,
        duplicate_recovery_blocked=2,
        late_authorization_stops=1,
        recovery_rate_percent=68.8,
    )


def test_create_controlled_batch_labels_synthetic_data(monkeypatch: pytest.MonkeyPatch) -> None:
    run = build_run()
    monkeypatch.setattr(
        evaluations, "create_or_load_controlled_evaluation", AsyncMock(return_value=run)
    )
    monkeypatch.setattr(
        evaluations, "load_evaluation_metrics", AsyncMock(return_value=build_metrics())
    )

    with TestClient(app) as client:
        response = client.post("/recovery/evaluations/controlled-batch")

    assert response.status_code == 201
    body = response.json()
    assert body["provenance"] == "controlled_synthetic"
    assert body["financial_scope"] == "not_production_merchant_revenue"
    assert body["run_key"] == "track3-controlled-batch-v1"
    assert body["policy_version"] == "deterministic-recovery-policy-v1"
    assert body["timing_scope"] == "deterministic_fixture_not_runtime_benchmark"
    assert body["created_at"] == run.created_at.isoformat().replace("+00:00", "Z")
    assert body["metrics"]["payments_evaluated"] == 100
    assert body["metrics"]["recovery_rate_percent"] == 68.8
    assert body["metrics"]["incremental_recovered_minor"] == 1_176_000
