"""Persistence and orchestration for versioned payment truth."""

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from string import hexdigits
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.payment import PaymentAttempt, PaymentStateTransition
from app.db.models.payment_truth import (
    PaymentEvidenceRecord,
    PaymentTruthSnapshotRecord,
)
from app.domain.payments import PaymentLifecycleEvent, PaymentState
from app.domain.payments.truth import (
    PaymentTruthDecision,
    PaymentTruthEvidenceFact,
    resolve_payment_truth,
)
from app.domain.recovery.contracts import PaymentEvidenceSource, PaymentTruthState

TRUTH_RESOLVER_VERSION = "payment-truth-v1"


@dataclass(frozen=True, slots=True)
class PaymentEvidenceWrite:
    payment_attempt_id: UUID
    source: PaymentEvidenceSource
    source_reference: str
    fact_name: str
    fact_value: str
    content_sha256: str
    observed_at: datetime
    event_at: datetime | None = None
    fresh_until: datetime | None = None
    recovery_case_id: UUID | None = None
    verified: bool = False

    def __post_init__(self) -> None:
        for field_name in ("source_reference", "fact_name", "fact_value"):
            if not getattr(self, field_name).strip():
                raise ValueError(f"{field_name} cannot be empty")
        digest = self.content_sha256.strip().casefold()
        if len(digest) != 64 or any(character not in hexdigits for character in digest):
            raise ValueError("content_sha256 must be a SHA-256 hex digest")
        object.__setattr__(self, "content_sha256", digest)
        for field_name in ("observed_at", "event_at", "fresh_until"):
            value = getattr(self, field_name)
            if value is not None and (value.tzinfo is None or value.utcoffset() is None):
                raise ValueError(f"{field_name} must be timezone-aware")
        if self.fresh_until is not None and self.fresh_until <= self.observed_at:
            raise ValueError("fresh_until must follow observed_at")


@dataclass(frozen=True, slots=True)
class PaymentTruthPersistenceResult:
    snapshot: PaymentTruthSnapshotRecord
    created: bool


def canonical_sha256(payload: object) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _evidence_uuid(request: PaymentEvidenceWrite) -> UUID:
    identity = "|".join(
        (
            str(request.payment_attempt_id),
            request.source.value,
            request.source_reference.strip(),
            request.fact_name.strip().casefold(),
            request.content_sha256,
        ),
    )
    return uuid5(NAMESPACE_URL, identity)


async def record_payment_evidence(
    session: AsyncSession,
    request: PaymentEvidenceWrite,
) -> PaymentEvidenceRecord:
    """Insert an immutable fact idempotently and return its canonical row."""
    evidence_id = _evidence_uuid(request)
    statement = (
        insert(PaymentEvidenceRecord)
        .values(
            id=evidence_id,
            payment_attempt_id=request.payment_attempt_id,
            recovery_case_id=request.recovery_case_id,
            source=request.source.value,
            source_reference=request.source_reference.strip(),
            fact_name=request.fact_name.strip().casefold(),
            fact_value=request.fact_value.strip(),
            content_sha256=request.content_sha256,
            event_at=request.event_at,
            observed_at=request.observed_at,
            fresh_until=request.fresh_until,
            verified=request.verified,
        )
        .on_conflict_do_nothing(constraint="uq_payment_evidence_fact_identity")
        .returning(PaymentEvidenceRecord.id)
    )
    await session.execute(statement)

    result = await session.execute(
        select(PaymentEvidenceRecord).where(PaymentEvidenceRecord.id == evidence_id),
    )
    return result.scalar_one()


def _as_domain_evidence(record: PaymentEvidenceRecord) -> PaymentTruthEvidenceFact:
    return PaymentTruthEvidenceFact(
        evidence_id=str(record.id),
        source=PaymentEvidenceSource(record.source),
        fact_name=record.fact_name,
        fact_value=record.fact_value,
        content_sha256=record.content_sha256,
        event_at=record.event_at,
        observed_at=record.observed_at,
        fresh_until=record.fresh_until,
        verified=record.verified,
    )


def _decision_digest(
    decision: PaymentTruthDecision,
    evidence: tuple[PaymentEvidenceRecord, ...],
) -> str:
    hashes_by_id = {str(item.id): item.content_sha256 for item in evidence}
    return canonical_sha256(
        {
            "resolver_version": TRUTH_RESOLVER_VERSION,
            "state": decision.state.value,
            "evidence": [
                {"id": reference, "sha256": hashes_by_id[reference]}
                for reference in decision.evidence_refs
            ],
            "conflict_codes": list(decision.conflict_codes),
        },
    )


def _apply_truth_gate(
    payment_attempt: PaymentAttempt,
    decision: PaymentTruthDecision,
    *,
    resolved_at: datetime,
) -> None:
    payment_attempt.recovery_eligible = (
        decision.state is PaymentTruthState.PAYMENT_FAILED
        and payment_attempt.current_state == PaymentState.FAILED.value
        and payment_attempt.recovery_stopped_at is None
    )
    if decision.state in {
        PaymentTruthState.PAYMENT_CONFIRMED,
        PaymentTruthState.LATE_AUTHORIZATION,
        PaymentTruthState.RECOVERY_CONFIRMED,
    }:
        payment_attempt.recovery_stopped_at = payment_attempt.recovery_stopped_at or resolved_at
        if payment_attempt.recovery_stop_reason is None:
            payment_attempt.recovery_stop_reason = f"truth_{decision.state.value}"


async def resolve_and_persist_payment_truth(
    session: AsyncSession,
    *,
    payment_attempt: PaymentAttempt,
    resolved_at: datetime,
    recovery_case_id: UUID | None = None,
) -> PaymentTruthPersistenceResult:
    """Resolve all stored evidence and append a snapshot only when truth changes."""
    locked_result = await session.execute(
        select(PaymentAttempt).where(PaymentAttempt.id == payment_attempt.id).with_for_update(),
    )
    locked_attempt = locked_result.scalar_one()
    evidence_result = await session.execute(
        select(PaymentEvidenceRecord)
        .where(PaymentEvidenceRecord.payment_attempt_id == payment_attempt.id)
        .order_by(PaymentEvidenceRecord.observed_at, PaymentEvidenceRecord.id),
    )
    evidence = tuple(evidence_result.scalars().all())
    decision = resolve_payment_truth(
        tuple(_as_domain_evidence(item) for item in evidence),
        resolved_at=resolved_at,
    )
    digest = _decision_digest(decision, evidence)

    latest_result = await session.execute(
        select(PaymentTruthSnapshotRecord)
        .where(PaymentTruthSnapshotRecord.payment_attempt_id == payment_attempt.id)
        .order_by(PaymentTruthSnapshotRecord.version.desc())
        .limit(1),
    )
    latest = latest_result.scalar_one_or_none()
    if (
        latest is not None
        and latest.evidence_digest == digest
        and latest.state == decision.state.value
    ):
        _apply_truth_gate(locked_attempt, decision, resolved_at=resolved_at)
        return PaymentTruthPersistenceResult(snapshot=latest, created=False)

    snapshot = PaymentTruthSnapshotRecord(
        id=uuid4(),
        payment_attempt_id=locked_attempt.id,
        recovery_case_id=recovery_case_id,
        version=1 if latest is None else latest.version + 1,
        state=decision.state.value,
        evidence_refs=list(decision.evidence_refs),
        conflict_codes=list(decision.conflict_codes),
        evidence_digest=digest,
        resolver_version=TRUTH_RESOLVER_VERSION,
        resolved_at=resolved_at,
    )
    session.add(snapshot)
    _apply_truth_gate(locked_attempt, decision, resolved_at=resolved_at)
    await session.flush()
    return PaymentTruthPersistenceResult(snapshot=snapshot, created=True)


async def record_webhook_transition_truth(
    session: AsyncSession,
    *,
    payment_attempt: PaymentAttempt,
    event: PaymentLifecycleEvent,
    transition: PaymentStateTransition,
    observed_at: datetime,
    content_sha256: str | None = None,
) -> PaymentTruthPersistenceResult:
    """Turn a normalized, signed webhook transition into reproducible truth."""
    payload_digest = content_sha256 or canonical_sha256(
        {
            "provider": event.provider,
            "provider_event_id": event.provider_event_id,
            "payment_id": event.payment_id,
            "order_id": event.order_id,
            "state": event.state.value,
            "amount_minor": event.amount_minor,
            "currency": event.currency,
            "event_created_at": event.event_created_at.isoformat(),
        }
    )
    await record_payment_evidence(
        session,
        PaymentEvidenceWrite(
            payment_attempt_id=payment_attempt.id,
            source=PaymentEvidenceSource.VERIFIED_WEBHOOK,
            source_reference=event.provider_event_id,
            fact_name="payment.status",
            fact_value=event.state.value,
            content_sha256=payload_digest,
            event_at=event.event_created_at,
            observed_at=observed_at,
            verified=True,
        ),
    )
    if transition.late_authorization:
        await record_payment_evidence(
            session,
            PaymentEvidenceWrite(
                payment_attempt_id=payment_attempt.id,
                source=PaymentEvidenceSource.VERIFIED_WEBHOOK,
                source_reference=event.provider_event_id,
                fact_name="payment.late_authorization",
                fact_value="true",
                content_sha256=payload_digest,
                event_at=event.event_created_at,
                observed_at=observed_at,
                verified=True,
            ),
        )
    return await resolve_and_persist_payment_truth(
        session,
        payment_attempt=payment_attempt,
        resolved_at=observed_at,
    )
