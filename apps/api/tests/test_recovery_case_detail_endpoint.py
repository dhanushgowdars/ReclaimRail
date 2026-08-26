from collections.abc import AsyncIterator
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes import recovery_case_detail
from app.core.database import get_database_session
from app.main import app
from app.services.recovery_case_detail_service import (
    PaymentLifecycleSnapshot,
    PaymentTransitionSummary,
    RecoveryActionSummary,
    RecoveryAgentRunSummary,
    RecoveryAuditChainSummary,
    RecoveryAuditEventSummary,
    RecoveryCaseDetail,
    RecoveryCaseDetailNotFoundError,
    RecoveryCaseSnapshot,
    RecoveryOutcomeSummary,
)

CASE_ID = UUID("10000000-0000-0000-0000-000000000001")
PAYMENT_ID = UUID("20000000-0000-0000-0000-000000000001")
ACTION_ID = UUID("30000000-0000-0000-0000-000000000001")
AGENT_RUN_ID = UUID("40000000-0000-0000-0000-000000000001")
OUTCOME_ID = UUID("50000000-0000-0000-0000-000000000001")
NOW = datetime(2026, 8, 26, 6, 0, tzinfo=UTC)


async def override_database_session() -> AsyncIterator[AsyncSession]:
    yield MagicMock(spec=AsyncSession)


@pytest.fixture(autouse=True)
def database_session_override() -> AsyncIterator[None]:
    app.dependency_overrides[get_database_session] = override_database_session

    yield

    app.dependency_overrides.clear()


def build_detail() -> RecoveryCaseDetail:
    return RecoveryCaseDetail(
        recovery_case=RecoveryCaseSnapshot(
            recovery_case_id=CASE_ID,
            status="recovered",
            amount_minor=349_900,
            currency="INR",
            payment_method="upi",
            source_incident_id=None,
            recovery_attempt_count=1,
            active_payment_link_id="plink_demo",
            next_action_at=None,
            late_authorization_detected_at=None,
            opened_at=NOW,
            recovered_at=NOW,
            closed_at=NOW,
            close_reason="payment_link_recovered",
        ),
        payment_lifecycle=PaymentLifecycleSnapshot(
            payment_attempt_id=PAYMENT_ID,
            current_state="failed",
            state_version=1,
            amount_minor=349_900,
            currency="INR",
            payment_method="upi",
            error_code="BAD_REQUEST_ERROR",
            error_source="customer",
            error_step="payment_authentication",
            error_reason="payment_failed",
            recovery_eligible=True,
            recovery_stopped_at=None,
            recovery_stop_reason=None,
            late_authorization_detected_at=None,
        ),
        agent_runs=(
            RecoveryAgentRunSummary(
                agent_run_id=AGENT_RUN_ID,
                run_number=1,
                status="succeeded",
                planner_provider="gemini",
                model_name="gemini-3.6-flash",
                prompt_version="gemini-structured-v1",
                reasoning_summary="A payment link is safe to create.",
                proposed_action_count=1,
                failure_code=None,
                started_at=NOW,
                completed_at=NOW,
            ),
        ),
        actions=(
            RecoveryActionSummary(
                recovery_action_id=ACTION_ID,
                agent_run_id=AGENT_RUN_ID,
                sequence_number=1,
                action_type="create_payment_link",
                status="succeeded",
                proposal_reason="Create a recovery link.",
                amount_minor=349_900,
                currency="INR",
                channel=None,
                target_payment_method=None,
                execute_after=None,
                policy_outcome="allow",
                policy_guardrails=("customer_contact_allowed",),
                policy_explanation="All deterministic checks passed.",
                policy_version="deterministic-v1",
                policy_evaluated_at=NOW,
                execution_attempt_count=1,
                provider_action_id="plink_demo",
                provider_action_status="paid",
                started_at=NOW,
                completed_at=NOW,
            ),
        ),
        outcome=RecoveryOutcomeSummary(
            recovery_outcome_id=OUTCOME_ID,
            status="recovered",
            attribution="direct_payment_link",
            recovery_action_id=ACTION_ID,
            payment_link_id="plink_demo",
            gross_recovered_minor=349_900,
            reversed_minor=0,
            duplicate_collection_prevented_minor=0,
            evidence_event_count=2,
            occurred_at=NOW,
            updated_at=NOW,
        ),
        payment_transitions=(
            PaymentTransitionSummary(
                event_type="payment.failed",
                previous_state="created",
                incoming_state="failed",
                resulting_state="failed",
                resulting_version=1,
                outcome="applied",
                reason="payment_failed",
                late_authorization=False,
                stop_recovery=False,
                event_created_at=NOW,
                processed_at=NOW,
            ),
        ),
        audit_chain=RecoveryAuditChainSummary(
            valid=True,
            reason="valid",
            checked_event_count=2,
            broken_sequence_number=None,
            total_event_count=2,
            timeline_truncated=False,
            events=(
                RecoveryAuditEventSummary(
                    sequence_number=1,
                    event_type="case.opened",
                    actor_type="system",
                    recovery_action_id=None,
                    previous_event_hash=None,
                    event_hash="a" * 64,
                    hash_algorithm="sha256",
                    occurred_at=NOW,
                ),
            ),
        ),
    )


def test_reads_pii_safe_recovery_case_detail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    load_detail = AsyncMock(return_value=build_detail())
    monkeypatch.setattr(
        recovery_case_detail,
        "load_recovery_case_detail",
        load_detail,
    )

    with TestClient(app) as client:
        response = client.get(f"/recovery/dashboard/cases/{CASE_ID}")

    assert response.status_code == 200

    body = response.json()
    assert body["recovery_case"]["recovery_case_id"] == str(CASE_ID)
    assert body["recovery_case"]["status"] == "recovered"
    assert body["payment_lifecycle"]["payment_attempt_id"] == str(PAYMENT_ID)
    assert body["agent_runs"][0]["planner_provider"] == "gemini"
    assert body["actions"][0]["policy_guardrails"] == ["customer_contact_allowed"]
    assert body["outcome"]["gross_recovered_minor"] == 349_900
    assert body["audit_chain"]["valid"] is True
    assert body["audit_chain"]["events"][0]["event_hash"] == "a" * 64
    assert "event_data" not in response.text
    assert "email" not in response.text
    assert "customer_email" not in response.text
    assert "+91" not in response.text
    assert load_detail.await_args.kwargs["recovery_case_id"] == CASE_ID


def test_returns_not_found_for_unknown_recovery_case(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    load_detail = AsyncMock(side_effect=RecoveryCaseDetailNotFoundError())
    monkeypatch.setattr(
        recovery_case_detail,
        "load_recovery_case_detail",
        load_detail,
    )

    with TestClient(app) as client:
        response = client.get(f"/recovery/dashboard/cases/{CASE_ID}")

    assert response.status_code == 404
    assert response.json() == {"detail": "Recovery case not found"}
