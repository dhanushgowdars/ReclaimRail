from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes import recovery_approvals
from app.core.config import Settings, get_settings
from app.core.database import get_database_session
from app.db.models.recovery import RecoveryApproval, RecoveryApprovalStatus
from app.main import app
from app.services.recovery_approval_service import (
    RecoveryApprovalDecisionDisposition,
    RecoveryApprovalDecisionResult,
)

NOW = datetime(2026, 8, 28, 13, 0, tzinfo=UTC)
APPROVAL_ID = UUID("cb000000-0000-0000-0000-000000000001")
CASE_ID = UUID("cb000000-0000-0000-0000-000000000002")
ACTION_ID = UUID("cb000000-0000-0000-0000-000000000003")
SESSION = AsyncMock(spec=AsyncSession)


async def override_database_session() -> AsyncIterator[AsyncSession]:
    yield SESSION


def override_settings() -> Settings:
    return Settings(
        recovery_operator_access_token=SecretStr("operator-secret"),
    )


@pytest.fixture(autouse=True)
def dependency_overrides() -> Iterator[None]:
    app.dependency_overrides[get_database_session] = override_database_session
    app.dependency_overrides[get_settings] = override_settings
    yield
    app.dependency_overrides.clear()
    SESSION.reset_mock()


def build_approval(
    status: RecoveryApprovalStatus = RecoveryApprovalStatus.PENDING,
) -> RecoveryApproval:
    return RecoveryApproval(
        id=APPROVAL_ID,
        recovery_case_id=CASE_ID,
        recovery_action_id=ACTION_ID,
        status=status.value,
        request_reason="amount_requires_operator_approval",
        amount_minor=349_900,
        currency="INR",
        threshold_minor=300_000,
        request_context={},
        requested_at=NOW,
        expires_at=NOW + timedelta(minutes=15),
        version=0,
    )


def test_operator_token_is_required_before_reading_queue(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    list_approvals = AsyncMock()
    monkeypatch.setattr(
        recovery_approvals,
        "list_recovery_approvals",
        list_approvals,
    )

    with TestClient(app) as client:
        response = client.get("/recovery/approvals")

    assert response.status_code == 401
    list_approvals.assert_not_awaited()


def test_lists_pending_approval_without_secrets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        recovery_approvals,
        "list_recovery_approvals",
        AsyncMock(return_value=(build_approval(),)),
    )

    with TestClient(app) as client:
        response = client.get(
            "/recovery/approvals",
            headers={"X-ReclaimRail-Operator-Token": "operator-secret"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["approvals"][0]["approval_id"] == str(APPROVAL_ID)
    assert body["approvals"][0]["status"] == "pending"
    assert "operator-secret" not in response.text


def test_approves_action_with_versioned_operator_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    approval = build_approval(RecoveryApprovalStatus.APPROVED)
    approval.version = 1
    approval.decided_at = NOW
    approval.decided_by = "judge-operator"
    approval.decision_reason = "Verified exact amount and policy receipt"
    decide = AsyncMock(
        return_value=RecoveryApprovalDecisionResult(
            approval=approval,
            disposition=RecoveryApprovalDecisionDisposition.DECIDED,
        ),
    )
    monkeypatch.setattr(
        recovery_approvals,
        "decide_recovery_approval",
        decide,
    )

    with TestClient(app) as client:
        response = client.post(
            f"/recovery/approvals/{APPROVAL_ID}/decision",
            headers={"X-ReclaimRail-Operator-Token": "operator-secret"},
            json={
                "decision": "approve",
                "reviewer_id": "judge-operator",
                "reason": "Verified exact amount and policy receipt",
                "expected_version": 0,
            },
        )

    assert response.status_code == 200
    assert response.json()["approval"]["status"] == "approved"
    assert decide.await_args.kwargs["expected_version"] == 0
    assert decide.await_args.kwargs["reviewer_id"] == "judge-operator"
