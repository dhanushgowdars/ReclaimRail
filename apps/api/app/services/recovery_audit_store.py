from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.recovery import (
    RecoveryAuditActor,
    RecoveryAuditEvent,
    RecoveryCase,
)
from app.services.recovery_audit import (
    RecoveryAuditChainEntry,
    RecoveryAuditVerification,
    build_recovery_audit_entry,
    normalize_recovery_audit_event_data,
    verify_recovery_audit_chain,
)


class RecoveryCaseNotFoundError(LookupError):
    pass


@dataclass(frozen=True, slots=True)
class RecoveryAuditAppendRequest:
    event_type: str
    actor_type: RecoveryAuditActor
    event_data: Mapping[str, object]
    occurred_at: datetime
    agent_run_id: UUID | None = None
    recovery_action_id: UUID | None = None

    def __post_init__(self) -> None:
        normalized_event_type = self.event_type.strip()

        if not normalized_event_type:
            raise ValueError("Audit event type cannot be empty")

        if self.occurred_at.tzinfo is None or self.occurred_at.utcoffset() is None:
            raise ValueError("Audit timestamp must be timezone-aware")

        normalized_event_data = normalize_recovery_audit_event_data(self.event_data)

        object.__setattr__(self, "event_type", normalized_event_type)
        object.__setattr__(self, "event_data", normalized_event_data)


def recovery_audit_model_to_chain_entry(
    event: RecoveryAuditEvent,
) -> RecoveryAuditChainEntry:
    return RecoveryAuditChainEntry(
        recovery_case_id=event.recovery_case_id,
        sequence_number=event.sequence_number,
        event_type=event.event_type,
        actor_type=event.actor_type,
        event_data=event.event_data,
        previous_event_hash=event.previous_event_hash,
        event_hash=event.event_hash,
        occurred_at=event.occurred_at,
        agent_run_id=event.agent_run_id,
        recovery_action_id=event.recovery_action_id,
        hash_algorithm=event.hash_algorithm,
    )


async def append_recovery_audit_event(
    session: AsyncSession,
    *,
    recovery_case_id: UUID,
    request: RecoveryAuditAppendRequest,
) -> RecoveryAuditEvent:
    case_result = await session.execute(
        select(RecoveryCase.id).where(RecoveryCase.id == recovery_case_id).with_for_update(),
    )

    if case_result.scalar_one_or_none() is None:
        raise RecoveryCaseNotFoundError(f"Recovery case {recovery_case_id} does not exist")

    previous_result = await session.execute(
        select(RecoveryAuditEvent)
        .where(RecoveryAuditEvent.recovery_case_id == recovery_case_id)
        .order_by(RecoveryAuditEvent.sequence_number.desc())
        .limit(1),
    )
    previous_event = previous_result.scalar_one_or_none()

    sequence_number = 1 if previous_event is None else previous_event.sequence_number + 1
    previous_event_hash = None if previous_event is None else previous_event.event_hash

    chain_entry = build_recovery_audit_entry(
        recovery_case_id=recovery_case_id,
        sequence_number=sequence_number,
        event_type=request.event_type,
        actor_type=request.actor_type.value,
        event_data=request.event_data,
        previous_event_hash=previous_event_hash,
        occurred_at=request.occurred_at,
        agent_run_id=request.agent_run_id,
        recovery_action_id=request.recovery_action_id,
    )

    event = RecoveryAuditEvent(
        recovery_case_id=chain_entry.recovery_case_id,
        agent_run_id=chain_entry.agent_run_id,
        recovery_action_id=chain_entry.recovery_action_id,
        sequence_number=chain_entry.sequence_number,
        event_type=chain_entry.event_type,
        actor_type=chain_entry.actor_type,
        event_data=dict(chain_entry.event_data),
        previous_event_hash=chain_entry.previous_event_hash,
        event_hash=chain_entry.event_hash,
        hash_algorithm=chain_entry.hash_algorithm,
        occurred_at=chain_entry.occurred_at,
    )
    session.add(event)
    await session.flush()
    return event


async def load_recovery_audit_chain(
    session: AsyncSession,
    *,
    recovery_case_id: UUID,
) -> tuple[RecoveryAuditChainEntry, ...]:
    result = await session.execute(
        select(RecoveryAuditEvent)
        .where(RecoveryAuditEvent.recovery_case_id == recovery_case_id)
        .order_by(RecoveryAuditEvent.sequence_number),
    )
    return tuple(recovery_audit_model_to_chain_entry(event) for event in result.scalars().all())


async def verify_persisted_recovery_audit_chain(
    session: AsyncSession,
    *,
    recovery_case_id: UUID,
) -> RecoveryAuditVerification:
    entries = await load_recovery_audit_chain(
        session,
        recovery_case_id=recovery_case_id,
    )
    return verify_recovery_audit_chain(entries)
