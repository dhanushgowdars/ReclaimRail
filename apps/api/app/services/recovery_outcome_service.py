import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.recovery import (
    RecoveryAction,
    RecoveryCase,
)
from app.db.models.recovery_outcome import (
    RecoveryOutcome,
    RecoveryOutcomeObservation,
)
from app.domain.recovery.outcomes import (
    RecoveryOutcomeProof,
)


class RecoveryOutcomeCaseNotFoundError(RuntimeError):
    pass


class RecoveryOutcomeActionNotFoundError(RuntimeError):
    pass


class RecoveryOutcomeActionCaseMismatchError(RuntimeError):
    pass


class RecoveryOutcomePaymentMismatchError(RuntimeError):
    pass


class RecoveryOutcomeConflictError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class RecoveryOutcomePersistenceResult:
    recovery_outcome_id: UUID
    recovery_outcome_observation_id: UUID | None
    projection_created: bool
    projection_updated: bool
    observation_created: bool


def _canonical_outcome_payload(
    proof: RecoveryOutcomeProof,
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "recovery_case_id": str(proof.recovery_case_id),
        "payment_attempt_id": str(proof.payment_attempt_id),
        "provider_payment_id": proof.provider_payment_id,
        "recovery_action_id": (
            str(proof.recovery_action_id) if proof.recovery_action_id is not None else None
        ),
        "payment_link_id": proof.payment_link_id,
        "provider_outcome_id": proof.provider_outcome_id,
        "status": proof.status.value,
        "attribution": proof.attribution.value,
        "original_amount_minor": proof.original_amount_minor,
        "currency": proof.currency,
        "gross_recovered_minor": proof.gross_recovered_minor,
        "reversed_minor": proof.reversed_minor,
        "duplicate_collection_prevented_minor": (proof.duplicate_collection_prevented_minor),
        "evidence_event_ids": sorted(proof.evidence_event_ids),
        "occurred_at": proof.occurred_at.isoformat(),
    }


def build_recovery_outcome_fingerprint(
    proof: RecoveryOutcomeProof,
) -> str:
    payload = _canonical_outcome_payload(proof)

    canonical_json = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )

    return hashlib.sha256(
        canonical_json.encode("utf-8"),
    ).hexdigest()


def _require_timezone_aware(
    value: datetime,
    *,
    field_name: str,
) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(
            f"{field_name} must be timezone-aware",
        )


async def _load_recovery_case(
    session: AsyncSession,
    *,
    recovery_case_id: UUID,
) -> RecoveryCase:
    result = await session.execute(
        select(RecoveryCase)
        .where(
            RecoveryCase.id == recovery_case_id,
        )
        .with_for_update(),
    )
    recovery_case = result.scalar_one_or_none()

    if recovery_case is None:
        raise RecoveryOutcomeCaseNotFoundError(
            f"Recovery case {recovery_case_id} does not exist",
        )

    return recovery_case


async def _validate_recovery_action(
    session: AsyncSession,
    *,
    recovery_action_id: UUID | None,
    recovery_case_id: UUID,
) -> None:
    if recovery_action_id is None:
        return

    result = await session.execute(
        select(RecoveryAction)
        .where(
            RecoveryAction.id == recovery_action_id,
        )
        .with_for_update(),
    )
    recovery_action = result.scalar_one_or_none()

    if recovery_action is None:
        raise RecoveryOutcomeActionNotFoundError(
            f"Recovery action {recovery_action_id} does not exist",
        )

    if recovery_action.recovery_case_id != recovery_case_id:
        raise RecoveryOutcomeActionCaseMismatchError(
            (
                f"Recovery action {recovery_action_id} does not belong to "
                f"recovery case {recovery_case_id}"
            ),
        )


def _validate_proof_against_case(
    proof: RecoveryOutcomeProof,
    recovery_case: RecoveryCase,
) -> None:
    if proof.payment_attempt_id != recovery_case.payment_attempt_id:
        raise RecoveryOutcomePaymentMismatchError(
            "Outcome proof payment attempt does not match recovery case",
        )

    if proof.original_amount_minor != recovery_case.amount_minor:
        raise RecoveryOutcomePaymentMismatchError(
            "Outcome proof amount does not match recovery case",
        )

    if proof.currency != recovery_case.currency:
        raise RecoveryOutcomePaymentMismatchError(
            "Outcome proof currency does not match recovery case",
        )


def _apply_proof_to_projection(
    projection: RecoveryOutcome,
    *,
    proof: RecoveryOutcomeProof,
    fingerprint: str,
) -> None:
    projection.recovery_action_id = proof.recovery_action_id
    projection.provider_payment_id = proof.provider_payment_id
    projection.payment_link_id = proof.payment_link_id
    projection.provider_outcome_id = proof.provider_outcome_id
    projection.status = proof.status.value
    projection.attribution = proof.attribution.value
    projection.original_amount_minor = proof.original_amount_minor
    projection.currency = proof.currency
    projection.gross_recovered_minor = proof.gross_recovered_minor
    projection.reversed_minor = proof.reversed_minor
    projection.duplicate_collection_prevented_minor = proof.duplicate_collection_prevented_minor
    projection.evidence_event_ids = list(proof.evidence_event_ids)
    projection.outcome_fingerprint = fingerprint
    projection.occurred_at = proof.occurred_at
    projection.updated_at = proof.occurred_at


def _new_projection(
    proof: RecoveryOutcomeProof,
    *,
    fingerprint: str,
) -> RecoveryOutcome:
    return RecoveryOutcome(
        recovery_case_id=proof.recovery_case_id,
        payment_attempt_id=proof.payment_attempt_id,
        recovery_action_id=proof.recovery_action_id,
        provider_payment_id=proof.provider_payment_id,
        payment_link_id=proof.payment_link_id,
        provider_outcome_id=proof.provider_outcome_id,
        status=proof.status.value,
        attribution=proof.attribution.value,
        original_amount_minor=proof.original_amount_minor,
        currency=proof.currency,
        gross_recovered_minor=proof.gross_recovered_minor,
        reversed_minor=proof.reversed_minor,
        duplicate_collection_prevented_minor=(proof.duplicate_collection_prevented_minor),
        evidence_event_ids=list(proof.evidence_event_ids),
        outcome_fingerprint=fingerprint,
        occurred_at=proof.occurred_at,
        updated_at=proof.occurred_at,
    )


async def _load_projection(
    session: AsyncSession,
    *,
    recovery_case_id: UUID,
) -> RecoveryOutcome | None:
    result = await session.execute(
        select(RecoveryOutcome)
        .where(
            RecoveryOutcome.recovery_case_id == recovery_case_id,
        )
        .with_for_update(),
    )

    return result.scalar_one_or_none()


async def _load_observation(
    session: AsyncSession,
    *,
    recovery_outcome_id: UUID,
    fingerprint: str,
) -> RecoveryOutcomeObservation | None:
    result = await session.execute(
        select(RecoveryOutcomeObservation).where(
            RecoveryOutcomeObservation.recovery_outcome_id == recovery_outcome_id,
            RecoveryOutcomeObservation.observation_fingerprint == fingerprint,
        ),
    )

    return result.scalar_one_or_none()


def _new_observation(
    proof: RecoveryOutcomeProof,
    *,
    recovery_outcome_id: UUID,
    fingerprint: str,
) -> RecoveryOutcomeObservation:
    return RecoveryOutcomeObservation(
        recovery_outcome_id=recovery_outcome_id,
        recovery_action_id=proof.recovery_action_id,
        status=proof.status.value,
        attribution=proof.attribution.value,
        gross_recovered_minor=proof.gross_recovered_minor,
        reversed_minor=proof.reversed_minor,
        duplicate_collection_prevented_minor=(proof.duplicate_collection_prevented_minor),
        payment_link_id=proof.payment_link_id,
        provider_outcome_id=proof.provider_outcome_id,
        evidence_event_ids=list(proof.evidence_event_ids),
        observation_fingerprint=fingerprint,
        occurred_at=proof.occurred_at,
    )


async def persist_recovery_outcome_proof(
    session: AsyncSession,
    *,
    proof: RecoveryOutcomeProof,
) -> RecoveryOutcomePersistenceResult:
    """
    Persist an outcome projection and immutable evidence observation.

    Replayed identical provider facts are idempotent. A newer observation may
    update the current projection. A different fact with the exact same
    timestamp is rejected for human review rather than silently changing
    financial reporting.
    """
    _require_timezone_aware(
        proof.occurred_at,
        field_name="Outcome proof timestamp",
    )

    recovery_case = await _load_recovery_case(
        session,
        recovery_case_id=proof.recovery_case_id,
    )
    _validate_proof_against_case(
        proof,
        recovery_case,
    )
    await _validate_recovery_action(
        session,
        recovery_action_id=proof.recovery_action_id,
        recovery_case_id=recovery_case.id,
    )

    fingerprint = build_recovery_outcome_fingerprint(proof)

    projection = await _load_projection(
        session,
        recovery_case_id=recovery_case.id,
    )

    projection_created = False
    projection_updated = False

    if projection is None:
        projection = _new_projection(
            proof,
            fingerprint=fingerprint,
        )
        session.add(projection)
        await session.flush()

        projection_created = True
        projection_updated = True
    elif projection.outcome_fingerprint != fingerprint:
        if proof.occurred_at < projection.occurred_at:
            projection_updated = False
        elif proof.occurred_at == projection.occurred_at:
            raise RecoveryOutcomeConflictError(
                ("Conflicting outcome proof has the same timestamp as the current projection"),
            )
        else:
            _apply_proof_to_projection(
                projection,
                proof=proof,
                fingerprint=fingerprint,
            )
            projection.version += 1
            projection_updated = True

    existing_observation = await _load_observation(
        session,
        recovery_outcome_id=projection.id,
        fingerprint=fingerprint,
    )

    if existing_observation is not None:
        return RecoveryOutcomePersistenceResult(
            recovery_outcome_id=projection.id,
            recovery_outcome_observation_id=(existing_observation.id),
            projection_created=projection_created,
            projection_updated=projection_updated,
            observation_created=False,
        )

    observation = _new_observation(
        proof,
        recovery_outcome_id=projection.id,
        fingerprint=fingerprint,
    )
    session.add(observation)
    await session.flush()

    return RecoveryOutcomePersistenceResult(
        recovery_outcome_id=projection.id,
        recovery_outcome_observation_id=observation.id,
        projection_created=projection_created,
        projection_updated=projection_updated,
        observation_created=True,
    )
