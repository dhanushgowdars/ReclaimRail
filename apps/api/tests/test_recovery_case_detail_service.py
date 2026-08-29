from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.services import recovery_case_detail_service
from app.services.recovery_audit import (
    RecoveryAuditChainEntry,
    RecoveryAuditVerification,
    RecoveryAuditVerificationReason,
)
from app.services.recovery_case_detail_service import (
    RecoveryCaseDetailNotFoundError,
    load_recovery_case_detail,
)

CASE_ID = UUID("10000000-0000-0000-0000-000000000001")
PAYMENT_ID = UUID("20000000-0000-0000-0000-000000000001")
ACTION_ID = UUID("30000000-0000-0000-0000-000000000001")
AGENT_RUN_ID = UUID("40000000-0000-0000-0000-000000000001")
OUTCOME_ID = UUID("50000000-0000-0000-0000-000000000001")
NOW = datetime(2026, 8, 26, 5, 30, tzinfo=UTC)


def build_result(*, row: object | None = None, values: list[object] | None = None) -> MagicMock:
    result = MagicMock()
    result.one_or_none.return_value = row
    result.scalars.return_value.all.return_value = values or []
    return result


def build_case() -> MagicMock:
    value = MagicMock()
    value.id = CASE_ID
    value.status = "recovered"
    value.amount_minor = 349_900
    value.currency = "INR"
    value.payment_method = "upi"
    value.source_incident_id = None
    value.recovery_attempt_count = 1
    value.active_payment_link_id = "plink_demo"
    value.next_action_at = None
    value.late_authorization_detected_at = None
    value.opened_at = NOW
    value.recovered_at = NOW
    value.closed_at = NOW
    value.close_reason = "payment_link_recovered"
    return value


def build_payment_attempt() -> MagicMock:
    value = MagicMock()
    value.id = PAYMENT_ID
    value.current_state = "failed"
    value.state_version = 1
    value.amount_minor = 349_900
    value.currency = "INR"
    value.method = "upi"
    value.error_code = "BAD_REQUEST_ERROR"
    value.error_source = "customer"
    value.error_step = "payment_authentication"
    value.error_reason = "payment_failed"
    value.recovery_eligible = True
    value.recovery_stopped_at = None
    value.recovery_stop_reason = None
    value.late_authorization_detected_at = None
    return value


def build_agent_run() -> MagicMock:
    value = MagicMock()
    value.id = AGENT_RUN_ID
    value.run_number = 1
    value.status = "succeeded"
    value.planner_provider = "gemini"
    value.model_name = "gemini-3.6-flash"
    value.prompt_version = "gemini-structured-v1"
    value.reasoning_summary = "A payment link is safe to create."
    value.proposed_action_count = 1
    value.failure_code = None
    value.started_at = NOW
    value.completed_at = NOW
    value.evidence = {
        "evidence_codes": ["payment_failed", "recovery_eligible"],
        "planner": {
            "fallback_used": False,
            "fallback_reason": None,
            "input_token_count": 212,
            "output_token_count": 61,
        },
        "bounded_ai_analysis": {
            "root_cause_category": "bank_authorization_failure",
            "recoverability_assessment": "recoverable",
            "confidence": 0.91,
            "allowed_action_recommendation": "create_payment_link",
            "evidence_references": ["payment_state_snapshot", "merchant_recovery_policy"],
        },
        "bounded_ai_evidence_tools": {
            "payment_state_snapshot": {"ref": "payment_state_snapshot"},
            "merchant_recovery_policy": {"ref": "merchant_recovery_policy"},
        },
    }
    return value


def build_action() -> MagicMock:
    value = MagicMock()
    value.id = ACTION_ID
    value.agent_run_id = AGENT_RUN_ID
    value.sequence_number = 1
    value.action_type = "create_payment_link"
    value.status = "succeeded"
    value.proposal_reason = "Create a recovery link."
    value.amount_minor = 349_900
    value.currency = "INR"
    value.channel = None
    value.target_payment_method = None
    value.execute_after = None
    value.policy_outcome = "allow"
    value.policy_guardrails = []
    value.policy_explanation = "All deterministic checks passed."
    value.policy_version = "deterministic-v1"
    value.policy_evaluated_at = NOW
    value.execution_attempt_count = 1
    value.provider_action_id = "plink_demo"
    value.provider_action_status = "paid"
    value.provider_action_url = "https://rzp.io/i/case-detail"
    value.provider_action_expires_at = NOW
    value.started_at = NOW
    value.completed_at = NOW
    return value


def build_outcome() -> MagicMock:
    value = MagicMock()
    value.id = OUTCOME_ID
    value.status = "recovered"
    value.attribution = "direct_payment_link"
    value.recovery_action_id = ACTION_ID
    value.payment_link_id = "plink_demo"
    value.gross_recovered_minor = 349_900
    value.reversed_minor = 0
    value.duplicate_collection_prevented_minor = 0
    value.evidence_event_ids = ["evt_payment_link_paid"]
    value.occurred_at = NOW
    value.updated_at = NOW
    return value


def build_transition() -> MagicMock:
    value = MagicMock()
    value.event_type = "payment.failed"
    value.previous_state = "created"
    value.incoming_state = "failed"
    value.resulting_state = "failed"
    value.resulting_version = 1
    value.outcome = "applied"
    value.reason = "payment_failed"
    value.late_authorization = False
    value.stop_recovery = False
    value.event_created_at = NOW
    value.processed_at = NOW
    return value


def build_audit_entry() -> RecoveryAuditChainEntry:
    return RecoveryAuditChainEntry(
        recovery_case_id=CASE_ID,
        sequence_number=1,
        event_type="case.opened",
        actor_type="system",
        event_data={"internal_only": "not_exposed"},
        previous_event_hash=None,
        event_hash="a" * 64,
        occurred_at=NOW,
    )


@pytest.mark.asyncio
async def test_loads_pii_safe_case_detail_with_verified_audit_chain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = AsyncMock(spec=AsyncSession)
    session.execute.side_effect = (
        build_result(row=(build_case(), build_payment_attempt(), build_outcome())),
        build_result(values=[build_agent_run()]),
        build_result(values=[build_action()]),
        build_result(),
        build_result(values=[build_transition()]),
    )
    audit_entries = (build_audit_entry(),)
    monkeypatch.setattr(
        recovery_case_detail_service,
        "load_recovery_audit_chain",
        AsyncMock(return_value=audit_entries),
    )
    monkeypatch.setattr(
        recovery_case_detail_service,
        "verify_persisted_recovery_audit_chain",
        AsyncMock(
            return_value=RecoveryAuditVerification(
                valid=True,
                reason=RecoveryAuditVerificationReason.VALID,
                checked_event_count=1,
            ),
        ),
    )

    detail = await load_recovery_case_detail(
        session,
        recovery_case_id=CASE_ID,
    )

    assert detail.recovery_case.recovery_case_id == CASE_ID
    assert detail.payment_lifecycle.current_state == "failed"
    assert detail.agent_runs[0].planner_provider == "gemini"
    assert detail.agent_runs[0].ai_trace.confidence == 0.91
    assert detail.agent_runs[0].ai_trace.root_cause_category == "bank_authorization_failure"
    assert detail.agent_runs[0].ai_trace.evidence_tool_names == (
        "merchant_recovery_policy",
        "payment_state_snapshot",
    )
    assert detail.actions[0].policy_outcome == "allow"
    assert detail.actions[0].provider_action_url == "https://rzp.io/i/case-detail"
    assert detail.outcome is not None
    assert detail.outcome.gross_recovered_minor == 349_900
    assert detail.payment_transitions[0].event_type == "payment.failed"
    assert detail.audit_chain.valid is True
    assert detail.audit_chain.total_event_count == 1
    assert detail.audit_chain.events[0].event_hash == "a" * 64
    assert not hasattr(detail.audit_chain.events[0], "event_data")
    assert session.execute.await_count == 5


@pytest.mark.asyncio
async def test_missing_case_is_rejected_before_follow_up_queries() -> None:
    session = AsyncMock(spec=AsyncSession)
    session.execute.return_value = build_result(row=None)

    with pytest.raises(
        RecoveryCaseDetailNotFoundError,
        match="does not exist",
    ):
        await load_recovery_case_detail(
            session,
            recovery_case_id=CASE_ID,
        )

    assert session.execute.await_count == 1


@pytest.mark.asyncio
async def test_audit_timeline_is_bounded_without_changing_chain_verification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = AsyncMock(spec=AsyncSession)
    session.execute.side_effect = (
        build_result(row=(build_case(), build_payment_attempt(), None)),
        build_result(),
        build_result(),
        build_result(),
        build_result(),
    )
    audit_entries = tuple(
        RecoveryAuditChainEntry(
            recovery_case_id=CASE_ID,
            sequence_number=index,
            event_type="case.opened",
            actor_type="system",
            event_data={},
            previous_event_hash=None if index == 1 else "a" * 64,
            event_hash="a" * 64,
            occurred_at=NOW,
        )
        for index in range(1, 102)
    )
    monkeypatch.setattr(
        recovery_case_detail_service,
        "load_recovery_audit_chain",
        AsyncMock(return_value=audit_entries),
    )
    monkeypatch.setattr(
        recovery_case_detail_service,
        "verify_persisted_recovery_audit_chain",
        AsyncMock(
            return_value=RecoveryAuditVerification(
                valid=False,
                reason=RecoveryAuditVerificationReason.EVENT_HASH_MISMATCH,
                checked_event_count=1,
                broken_sequence_number=2,
            ),
        ),
    )

    detail = await load_recovery_case_detail(
        session,
        recovery_case_id=CASE_ID,
    )

    assert detail.audit_chain.total_event_count == 101
    assert detail.audit_chain.timeline_truncated is True
    assert len(detail.audit_chain.events) == 100
    assert detail.audit_chain.valid is False
    assert detail.audit_chain.broken_sequence_number == 2
