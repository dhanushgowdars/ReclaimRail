from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone
from uuid import UUID

import pytest

from app.services.recovery_audit import (
    RecoveryAuditChainEntry,
    RecoveryAuditVerificationReason,
    build_recovery_audit_entry,
    compute_recovery_audit_hash,
    verify_recovery_audit_chain,
)

CASE_ID = UUID("10000000-0000-0000-0000-000000000001")
RUN_ID = UUID("20000000-0000-0000-0000-000000000001")
ACTION_ID = UUID("30000000-0000-0000-0000-000000000001")
OCCURRED_AT = datetime(2026, 8, 24, 12, 30, tzinfo=UTC)


def create_chain() -> tuple[RecoveryAuditChainEntry, RecoveryAuditChainEntry]:
    first = build_recovery_audit_entry(
        recovery_case_id=CASE_ID,
        sequence_number=1,
        event_type="agent.plan.created",
        actor_type="agent",
        event_data={"proposal_count": 2, "bounded": True},
        previous_event_hash=None,
        occurred_at=OCCURRED_AT,
        agent_run_id=RUN_ID,
    )
    second = build_recovery_audit_entry(
        recovery_case_id=CASE_ID,
        sequence_number=2,
        event_type="policy.action.allowed",
        actor_type="policy",
        event_data={"action_type": "create_payment_link", "guardrails": []},
        previous_event_hash=first.event_hash,
        occurred_at=OCCURRED_AT + timedelta(seconds=1),
        agent_run_id=RUN_ID,
        recovery_action_id=ACTION_ID,
    )
    return first, second


def test_hash_is_stable_across_event_data_key_order() -> None:
    common = {
        "recovery_case_id": CASE_ID,
        "sequence_number": 1,
        "event_type": "case.opened",
        "actor_type": "system",
        "previous_event_hash": None,
        "occurred_at": OCCURRED_AT,
    }

    first_hash = compute_recovery_audit_hash(
        **common,
        event_data={"currency": "INR", "amount_minor": 149900},
    )
    second_hash = compute_recovery_audit_hash(
        **common,
        event_data={"amount_minor": 149900, "currency": "INR"},
    )

    assert first_hash == second_hash
    assert len(first_hash) == 64


def test_hash_normalizes_equivalent_timestamps_to_utc() -> None:
    indian_time = OCCURRED_AT.astimezone(timezone(timedelta(hours=5, minutes=30)))

    utc_hash = compute_recovery_audit_hash(
        recovery_case_id=CASE_ID,
        sequence_number=1,
        event_type="case.opened",
        actor_type="system",
        event_data={},
        previous_event_hash=None,
        occurred_at=OCCURRED_AT,
    )
    indian_time_hash = compute_recovery_audit_hash(
        recovery_case_id=CASE_ID,
        sequence_number=1,
        event_type="case.opened",
        actor_type="system",
        event_data={},
        previous_event_hash=None,
        occurred_at=indian_time,
    )

    assert utc_hash == indian_time_hash


def test_changed_evidence_changes_hash() -> None:
    original, _ = create_chain()
    changed_hash = compute_recovery_audit_hash(
        recovery_case_id=original.recovery_case_id,
        sequence_number=original.sequence_number,
        event_type=original.event_type,
        actor_type=original.actor_type,
        event_data={"proposal_count": 3, "bounded": True},
        previous_event_hash=original.previous_event_hash,
        occurred_at=original.occurred_at,
        agent_run_id=original.agent_run_id,
    )

    assert changed_hash != original.event_hash


def test_verifies_valid_chain() -> None:
    chain = create_chain()

    result = verify_recovery_audit_chain(chain)

    assert result.valid is True
    assert result.reason is RecoveryAuditVerificationReason.VALID
    assert result.checked_event_count == 2
    assert result.broken_sequence_number is None


def test_detects_tampered_event_data() -> None:
    first, second = create_chain()
    tampered_second = replace(
        second,
        event_data={"action_type": "create_payment_link", "guardrails": ["bypassed"]},
    )

    result = verify_recovery_audit_chain((first, tampered_second))

    assert result.valid is False
    assert result.reason is RecoveryAuditVerificationReason.EVENT_HASH_MISMATCH
    assert result.checked_event_count == 1
    assert result.broken_sequence_number == 2


def test_detects_broken_previous_hash_link() -> None:
    first, second = create_chain()
    broken_second = replace(second, previous_event_hash="0" * 64)

    result = verify_recovery_audit_chain((first, broken_second))

    assert result.valid is False
    assert result.reason is RecoveryAuditVerificationReason.PREVIOUS_HASH_MISMATCH
    assert result.broken_sequence_number == 2


def test_detects_sequence_gap() -> None:
    first, second = create_chain()
    skipped = replace(second, sequence_number=3)

    result = verify_recovery_audit_chain((first, skipped))

    assert result.valid is False
    assert result.reason is RecoveryAuditVerificationReason.SEQUENCE_GAP
    assert result.broken_sequence_number == 3


def test_detects_case_mismatch() -> None:
    first, second = create_chain()
    other_case = replace(
        second,
        recovery_case_id=UUID("10000000-0000-0000-0000-000000000099"),
    )

    result = verify_recovery_audit_chain((first, other_case))

    assert result.valid is False
    assert result.reason is RecoveryAuditVerificationReason.CASE_MISMATCH


def test_rejects_naive_timestamp() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        compute_recovery_audit_hash(
            recovery_case_id=CASE_ID,
            sequence_number=1,
            event_type="case.opened",
            actor_type="system",
            event_data={},
            previous_event_hash=None,
            occurred_at=datetime(2026, 8, 24, 12, 30),
        )


def test_rejects_non_finite_event_data() -> None:
    with pytest.raises(ValueError, match="non-finite"):
        compute_recovery_audit_hash(
            recovery_case_id=CASE_ID,
            sequence_number=1,
            event_type="case.opened",
            actor_type="system",
            event_data={"confidence": float("nan")},
            previous_event_hash=None,
            occurred_at=OCCURRED_AT,
        )
