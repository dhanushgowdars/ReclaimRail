"""Persistence and orchestration for versioned payment truth."""

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from string import hexdigits
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.investigation import RecoveryInvestigationSession
from app.db.models.payment import PaymentAttempt, PaymentStateTransition
from app.db.models.payment_lab import PaymentLabRun
from app.db.models.payment_truth import (
    PaymentEvidenceRecord,
    PaymentTruthSnapshotRecord,
)
from app.db.models.recovery import (
    RecoveryAction,
    RecoveryActionStatus,
    RecoveryAgentRun,
    RecoveryAgentRunStatus,
    RecoveryApproval,
    RecoveryApprovalStatus,
    RecoveryCase,
)
from app.db.models.recovery_outcome import RecoveryOutcome
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
    signature_verified: bool | None = None
    normalized_fields: dict[str, object] | None = None
    reliability: str = "corroborating"
    unavailable_reason: str | None = None

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
        if self.reliability not in {"authoritative", "corroborating", "weak"}:
            raise ValueError("reliability must be authoritative, corroborating, or weak")
        if self.unavailable_reason is not None and not self.unavailable_reason.strip():
            raise ValueError("unavailable_reason cannot be blank")


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
            signature_verified=request.signature_verified,
            normalized_fields=request.normalized_fields or {},
            reliability=request.reliability,
            unavailable_reason=request.unavailable_reason,
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
        reliability=record.reliability,
        unavailable_reason=record.unavailable_reason,
    )


async def record_linked_runtime_evidence(
    session: AsyncSession,
    *,
    payment_attempt: PaymentAttempt,
    observed_at: datetime,
) -> None:
    """Snapshot every local source linked to an attempt into the immutable ledger."""
    internal_payload = {
        "state": payment_attempt.current_state,
        "version": payment_attempt.state_version,
        "provider_payment_id": payment_attempt.provider_payment_id,
        "provider_order_id": payment_attempt.provider_order_id,
    }
    await record_payment_evidence(
        session,
        PaymentEvidenceWrite(
            payment_attempt_id=payment_attempt.id,
            source=PaymentEvidenceSource.MERCHANT_DATABASE,
            source_reference=f"payment-attempt:{payment_attempt.id}:v{payment_attempt.state_version}",
            fact_name="payment.status",
            fact_value=payment_attempt.current_state,
            content_sha256=canonical_sha256(internal_payload),
            observed_at=observed_at,
            normalized_fields=internal_payload,
            verified=True,
            reliability="corroborating",
        ),
    )

    lab_result = await session.execute(
        select(PaymentLabRun).where(
            (PaymentLabRun.payment_attempt_id == payment_attempt.id)
            | (
                (PaymentLabRun.payment_attempt_id.is_(None))
                & (PaymentLabRun.provider_order_id == payment_attempt.provider_order_id)
            ),
        ),
    )
    for run in lab_result.scalars():
        payload: dict[str, object] = {
            "run_id": str(run.id),
            "status": run.status,
            "mode": run.mode,
            "provenance": run.provenance,
            "order_id": run.provider_order_id,
        }
        await record_payment_evidence(
            session,
            PaymentEvidenceWrite(
                payment_attempt_id=payment_attempt.id,
                source=PaymentEvidenceSource.PAYMENT_LAB,
                source_reference=f"payment-lab:{run.id}:v{run.version}",
                fact_name="payment_lab.status",
                fact_value=run.status,
                content_sha256=canonical_sha256(payload),
                observed_at=observed_at,
                normalized_fields=payload,
                verified=True,
                reliability="corroborating",
            ),
        )
        if run.provider_order_status:
            await record_payment_evidence(
                session,
                PaymentEvidenceWrite(
                    payment_attempt_id=payment_attempt.id,
                    source=PaymentEvidenceSource.PROVIDER_ORDER_API,
                    source_reference=f"provider-order:{run.provider_order_id}:{run.provider_order_status}",
                    fact_name="order.status",
                    fact_value=run.provider_order_status,
                    content_sha256=canonical_sha256(payload),
                    observed_at=observed_at,
                    event_at=run.provider_created_at,
                    normalized_fields=payload,
                    verified=True,
                    reliability="authoritative",
                ),
            )

    case_result = await session.execute(
        select(RecoveryCase).where(RecoveryCase.payment_attempt_id == payment_attempt.id),
    )
    recovery_case = case_result.scalar_one_or_none()
    if recovery_case is None:
        return
    recovery_payload: dict[str, object] = {
        "case_id": str(recovery_case.id),
        "status": recovery_case.status,
        "version": recovery_case.version,
        "active_payment_link_id": recovery_case.active_payment_link_id,
    }
    await record_payment_evidence(
        session,
        PaymentEvidenceWrite(
            payment_attempt_id=payment_attempt.id,
            recovery_case_id=recovery_case.id,
            source=PaymentEvidenceSource.RECOVERY_STATE,
            source_reference=f"recovery-case:{recovery_case.id}:v{recovery_case.version}",
            fact_name="recovery.status",
            fact_value=recovery_case.status,
            content_sha256=canonical_sha256(recovery_payload),
            observed_at=observed_at,
            normalized_fields=recovery_payload,
            verified=True,
            reliability="corroborating",
        ),
    )
    if recovery_case.active_payment_link_id:
        await record_payment_evidence(
            session,
            PaymentEvidenceWrite(
                payment_attempt_id=payment_attempt.id,
                recovery_case_id=recovery_case.id,
                source=PaymentEvidenceSource.RECOVERY_LINK,
                source_reference=recovery_case.active_payment_link_id,
                fact_name="recovery_link.status",
                fact_value="active",
                content_sha256=canonical_sha256(recovery_payload),
                observed_at=observed_at,
                normalized_fields=recovery_payload,
                verified=True,
                reliability="corroborating",
            ),
        )
    outcome_result = await session.execute(
        select(RecoveryOutcome).where(RecoveryOutcome.recovery_case_id == recovery_case.id),
    )
    outcome = outcome_result.scalar_one_or_none()
    if outcome is not None:
        outcome_payload = {
            "outcome_id": str(outcome.id),
            "status": outcome.status,
            "version": outcome.version,
            "payment_link_id": outcome.payment_link_id,
            "provider_outcome_id": outcome.provider_outcome_id,
        }
        await record_payment_evidence(
            session,
            PaymentEvidenceWrite(
                payment_attempt_id=payment_attempt.id,
                recovery_case_id=recovery_case.id,
                source=PaymentEvidenceSource.RECONCILIATION,
                source_reference=f"recovery-outcome:{outcome.id}:v{outcome.version}",
                fact_name="recovery.status",
                fact_value=("verified" if outcome.status == "recovered" else outcome.status),
                content_sha256=canonical_sha256(outcome_payload),
                observed_at=observed_at,
                normalized_fields=outcome_payload,
                verified=True,
                reliability="authoritative" if outcome.status == "recovered" else "corroborating",
            ),
        )


async def _invalidate_stale_recovery_plan(
    session: AsyncSession,
    *,
    payment_attempt_id: UUID,
    new_truth_version: int,
    resolved_at: datetime,
) -> None:
    result = await session.execute(
        select(RecoveryCase)
        .where(RecoveryCase.payment_attempt_id == payment_attempt_id)
        .with_for_update(),
    )
    recovery_case = result.scalar_one_or_none()
    if recovery_case is None:
        return
    recovery_case.version += 1
    await session.execute(
        update(RecoveryInvestigationSession)
        .where(
            RecoveryInvestigationSession.recovery_case_id == recovery_case.id,
            RecoveryInvestigationSession.status == "running",
        )
        .values(
            status="failed_safe",
            terminal_reason="superseded_by_new_evidence",
            result_summary=f"Superseded by payment truth version {new_truth_version}.",
            completed_at=resolved_at,
        ),
    )
    await session.execute(
        update(RecoveryAgentRun)
        .where(
            RecoveryAgentRun.recovery_case_id == recovery_case.id,
            RecoveryAgentRun.status == RecoveryAgentRunStatus.SUCCEEDED.value,
        )
        .values(status=RecoveryAgentRunStatus.SUPERSEDED.value, completed_at=resolved_at),
    )
    await session.execute(
        update(RecoveryAction)
        .where(
            RecoveryAction.recovery_case_id == recovery_case.id,
            RecoveryAction.status.in_(
                (
                    RecoveryActionStatus.ALLOWED.value,
                    RecoveryActionStatus.APPROVAL_REQUIRED.value,
                    RecoveryActionStatus.SCHEDULED.value,
                ),
            ),
        )
        .values(
            status=RecoveryActionStatus.CANCELLED.value,
            last_error=f"Invalidated by payment truth version {new_truth_version}",
        ),
    )
    await session.execute(
        update(RecoveryApproval)
        .where(
            RecoveryApproval.recovery_case_id == recovery_case.id,
            RecoveryApproval.status.in_(
                (RecoveryApprovalStatus.PENDING.value, RecoveryApprovalStatus.APPROVED.value),
            ),
        )
        .values(
            status=RecoveryApprovalStatus.EXPIRED.value,
            decided_at=resolved_at,
            decided_by=None,
            decision_reason=f"Invalidated by payment truth version {new_truth_version}",
        ),
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
    if latest is not None:
        await _invalidate_stale_recovery_plan(
            session,
            payment_attempt_id=locked_attempt.id,
            new_truth_version=snapshot.version,
            resolved_at=resolved_at,
        )
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
    evidence_source: PaymentEvidenceSource = PaymentEvidenceSource.VERIFIED_WEBHOOK,
) -> PaymentTruthPersistenceResult:
    """Turn a normalized provider event into reproducible payment truth."""
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
            source=evidence_source,
            source_reference=event.provider_event_id,
            fact_name="payment.status",
            fact_value=event.state.value,
            content_sha256=payload_digest,
            event_at=event.event_created_at,
            observed_at=observed_at,
            verified=True,
            signature_verified=(
                True if evidence_source is PaymentEvidenceSource.VERIFIED_WEBHOOK else None
            ),
            normalized_fields={
                "payment_id": event.payment_id,
                "order_id": event.order_id,
                "amount_minor": event.amount_minor,
                "currency": event.currency,
            },
            reliability=(
                "authoritative"
                if evidence_source is PaymentEvidenceSource.PROVIDER_PAYMENT_API
                else "corroborating"
            ),
        ),
    )
    if transition.late_authorization:
        await record_payment_evidence(
            session,
            PaymentEvidenceWrite(
                payment_attempt_id=payment_attempt.id,
                source=evidence_source,
                source_reference=event.provider_event_id,
                fact_name="payment.late_authorization",
                fact_value="true",
                content_sha256=payload_digest,
                event_at=event.event_created_at,
                observed_at=observed_at,
                verified=True,
            ),
        )
    await record_linked_runtime_evidence(
        session,
        payment_attempt=payment_attempt,
        observed_at=observed_at,
    )
    return await resolve_and_persist_payment_truth(
        session,
        payment_attempt=payment_attempt,
        resolved_at=observed_at,
    )
