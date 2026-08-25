from datetime import UTC, datetime
from enum import StrEnum
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.recovery import (
    RecoveryAuditActor,
    RecoveryAuditEvent,
)
from app.services.recovery_audit import RecoveryAuditVerificationReason
from app.services.recovery_audit_store import (
    RecoveryAuditAppendRequest,
    RecoveryCaseNotFoundError,
    append_recovery_audit_event,
    load_recovery_audit_chain,
    verify_persisted_recovery_audit_chain,
)

CASE_ID = UUID("10000000-0000-0000-0000-000000000001")
RUN_ID = UUID("20000000-0000-0000-0000-000000000001")
ACTION_ID = UUID("30000000-0000-0000-0000-000000000001")
OCCURRED_AT = datetime(2026, 8, 25, 6, 0, tzinfo=UTC)


class EvidenceOutcome(StrEnum):
    ALLOW = "allow"


def query_result(*, scalar: object | None = None) -> MagicMock:
    result = MagicMock()
    result.scalar_one_or_none.return_value = scalar
    return result


def chain_query_result(*events: RecoveryAuditEvent) -> MagicMock:
    result = MagicMock()
    result.scalars.return_value.all.return_value = list(events)
    return result


def create_request() -> RecoveryAuditAppendRequest:
    return RecoveryAuditAppendRequest(
        event_type=" policy.action.allowed ",
        actor_type=RecoveryAuditActor.POLICY,
        event_data={
            "outcome": EvidenceOutcome.ALLOW,
            "evaluated_at": OCCURRED_AT,
            "run_id": RUN_ID,
        },
        occurred_at=OCCURRED_AT,
        agent_run_id=RUN_ID,
        recovery_action_id=ACTION_ID,
    )


def create_persisted_event(
    *,
    sequence_number: int,
    previous_event_hash: str | None,
    event_hash: str,
) -> RecoveryAuditEvent:
    return RecoveryAuditEvent(
        recovery_case_id=CASE_ID,
        sequence_number=sequence_number,
        event_type="policy.action.allowed",
        actor_type=RecoveryAuditActor.POLICY.value,
        event_data={"outcome": "allow"},
        previous_event_hash=previous_event_hash,
        event_hash=event_hash,
        hash_algorithm="sha256",
        occurred_at=OCCURRED_AT,
    )


def test_request_normalizes_json_evidence() -> None:
    request = create_request()

    assert request.event_type == "policy.action.allowed"
    assert request.event_data == {
        "outcome": "allow",
        "evaluated_at": "2026-08-25T06:00:00.000000Z",
        "run_id": str(RUN_ID),
    }


def test_request_rejects_naive_timestamp() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        RecoveryAuditAppendRequest(
            event_type="case.opened",
            actor_type=RecoveryAuditActor.SYSTEM,
            event_data={},
            occurred_at=datetime(2026, 8, 25, 6, 0),
        )


@pytest.mark.asyncio
async def test_appends_genesis_event() -> None:
    session = AsyncMock(spec=AsyncSession)
    session.execute.side_effect = [
        query_result(scalar=CASE_ID),
        query_result(scalar=None),
    ]

    event = await append_recovery_audit_event(
        session,
        recovery_case_id=CASE_ID,
        request=create_request(),
    )

    assert event.sequence_number == 1
    assert event.previous_event_hash is None
    assert len(event.event_hash) == 64
    assert event.actor_type == RecoveryAuditActor.POLICY.value
    assert event.event_data["outcome"] == "allow"
    session.add.assert_called_once_with(event)
    session.flush.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_appends_event_after_previous_hash() -> None:
    previous = create_persisted_event(
        sequence_number=7,
        previous_event_hash="a" * 64,
        event_hash="b" * 64,
    )
    session = AsyncMock(spec=AsyncSession)
    session.execute.side_effect = [
        query_result(scalar=CASE_ID),
        query_result(scalar=previous),
    ]

    event = await append_recovery_audit_event(
        session,
        recovery_case_id=CASE_ID,
        request=create_request(),
    )

    assert event.sequence_number == 8
    assert event.previous_event_hash == previous.event_hash


@pytest.mark.asyncio
async def test_missing_case_is_rejected_before_append() -> None:
    session = AsyncMock(spec=AsyncSession)
    session.execute.return_value = query_result(scalar=None)

    with pytest.raises(RecoveryCaseNotFoundError, match=str(CASE_ID)):
        await append_recovery_audit_event(
            session,
            recovery_case_id=CASE_ID,
            request=create_request(),
        )

    assert session.execute.await_count == 1
    session.add.assert_not_called()
    session.flush.assert_not_awaited()


@pytest.mark.asyncio
async def test_loads_chain_in_database_order() -> None:
    first = create_persisted_event(
        sequence_number=1,
        previous_event_hash=None,
        event_hash="a" * 64,
    )
    second = create_persisted_event(
        sequence_number=2,
        previous_event_hash="a" * 64,
        event_hash="b" * 64,
    )
    session = AsyncMock(spec=AsyncSession)
    session.execute.return_value = chain_query_result(first, second)

    entries = await load_recovery_audit_chain(
        session,
        recovery_case_id=CASE_ID,
    )

    assert [entry.sequence_number for entry in entries] == [1, 2]
    assert entries[1].previous_event_hash == first.event_hash


@pytest.mark.asyncio
async def test_verifies_empty_persisted_chain() -> None:
    session = AsyncMock(spec=AsyncSession)
    session.execute.return_value = chain_query_result()

    verification = await verify_persisted_recovery_audit_chain(
        session,
        recovery_case_id=CASE_ID,
    )

    assert verification.valid is True
    assert verification.reason is RecoveryAuditVerificationReason.VALID
    assert verification.checked_event_count == 0
