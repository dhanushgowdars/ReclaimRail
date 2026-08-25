from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.payment import PaymentAttempt
from app.db.models.recovery import (
    RecoveryAuditActor,
    RecoveryAuditEvent,
    RecoveryCase,
)
from app.domain.payments import PaymentState
from app.domain.recovery import RecoveryCaseStatus
from app.services.recovery_audit_store import (
    RecoveryAuditAppendRequest,
    append_recovery_audit_event,
)


class PaymentAttemptNotFoundError(LookupError):
    pass


class RecoveryCaseCreationDisposition(StrEnum):
    CREATED = "created"
    EXISTING = "existing"
    INELIGIBLE = "ineligible"


class RecoveryCaseIneligibilityReason(StrEnum):
    PAYMENT_NOT_FAILED = "payment_not_failed"
    RECOVERY_NOT_ELIGIBLE = "recovery_not_eligible"
    RECOVERY_ALREADY_STOPPED = "recovery_already_stopped"
    NONPOSITIVE_AMOUNT = "nonpositive_amount"


@dataclass(frozen=True, slots=True)
class RecoveryCaseCreationResult:
    disposition: RecoveryCaseCreationDisposition
    recovery_case: RecoveryCase | None
    audit_event: RecoveryAuditEvent | None
    ineligibility_reasons: tuple[RecoveryCaseIneligibilityReason, ...] = ()

    def __post_init__(self) -> None:
        if self.disposition is RecoveryCaseCreationDisposition.CREATED:
            if self.recovery_case is None or self.audit_event is None:
                raise ValueError("Created result requires a recovery case and audit event")
            if self.ineligibility_reasons:
                raise ValueError("Created result cannot contain ineligibility reasons")

        if self.disposition is RecoveryCaseCreationDisposition.EXISTING:
            if self.recovery_case is None:
                raise ValueError("Existing result requires a recovery case")
            if self.audit_event is not None or self.ineligibility_reasons:
                raise ValueError("Existing result cannot contain new audit evidence")

        if self.disposition is RecoveryCaseCreationDisposition.INELIGIBLE:
            if self.recovery_case is not None or self.audit_event is not None:
                raise ValueError("Ineligible result cannot contain persisted records")
            if not self.ineligibility_reasons:
                raise ValueError("Ineligible result requires reason evidence")


def evaluate_recovery_case_eligibility(
    payment_attempt: PaymentAttempt,
) -> tuple[RecoveryCaseIneligibilityReason, ...]:
    reasons: list[RecoveryCaseIneligibilityReason] = []

    if payment_attempt.current_state != PaymentState.FAILED.value:
        reasons.append(RecoveryCaseIneligibilityReason.PAYMENT_NOT_FAILED)

    if not payment_attempt.recovery_eligible:
        reasons.append(RecoveryCaseIneligibilityReason.RECOVERY_NOT_ELIGIBLE)

    if payment_attempt.recovery_stopped_at is not None:
        reasons.append(RecoveryCaseIneligibilityReason.RECOVERY_ALREADY_STOPPED)

    if payment_attempt.amount_minor <= 0:
        reasons.append(RecoveryCaseIneligibilityReason.NONPOSITIVE_AMOUNT)

    return tuple(reasons)


async def create_or_get_recovery_case(
    session: AsyncSession,
    *,
    payment_attempt_id: UUID,
    opened_at: datetime,
    customer_contact_allowed: bool,
    source_incident_id: UUID | None = None,
) -> RecoveryCaseCreationResult:
    if opened_at.tzinfo is None or opened_at.utcoffset() is None:
        raise ValueError("Recovery-case opening time must be timezone-aware")

    payment_result = await session.execute(
        select(PaymentAttempt).where(PaymentAttempt.id == payment_attempt_id).with_for_update(),
    )
    payment_attempt = payment_result.scalar_one_or_none()

    if payment_attempt is None:
        raise PaymentAttemptNotFoundError(
            f"Payment attempt {payment_attempt_id} does not exist",
        )

    existing_result = await session.execute(
        select(RecoveryCase).where(
            RecoveryCase.payment_attempt_id == payment_attempt_id,
        ),
    )
    existing_case = existing_result.scalar_one_or_none()

    if existing_case is not None:
        return RecoveryCaseCreationResult(
            disposition=RecoveryCaseCreationDisposition.EXISTING,
            recovery_case=existing_case,
            audit_event=None,
        )

    ineligibility_reasons = evaluate_recovery_case_eligibility(payment_attempt)

    if ineligibility_reasons:
        return RecoveryCaseCreationResult(
            disposition=RecoveryCaseCreationDisposition.INELIGIBLE,
            recovery_case=None,
            audit_event=None,
            ineligibility_reasons=ineligibility_reasons,
        )

    recovery_case = RecoveryCase(
        id=uuid4(),
        payment_attempt_id=payment_attempt.id,
        source_incident_id=source_incident_id,
        status=RecoveryCaseStatus.OPEN.value,
        amount_minor=payment_attempt.amount_minor,
        currency=payment_attempt.currency.strip().upper(),
        payment_method=(
            payment_attempt.method.strip().casefold()
            if payment_attempt.method is not None and payment_attempt.method.strip()
            else None
        ),
        recovery_attempt_count=0,
        version=0,
        customer_contact_allowed=customer_contact_allowed,
        opened_at=opened_at,
    )
    session.add(recovery_case)
    await session.flush()

    audit_event = await append_recovery_audit_event(
        session,
        recovery_case_id=recovery_case.id,
        request=RecoveryAuditAppendRequest(
            event_type="case.opened",
            actor_type=RecoveryAuditActor.SYSTEM,
            event_data={
                "payment_attempt_id": payment_attempt.id,
                "provider": payment_attempt.provider,
                "provider_payment_id": payment_attempt.provider_payment_id,
                "payment_state": payment_attempt.current_state,
                "amount_minor": payment_attempt.amount_minor,
                "currency": payment_attempt.currency.strip().upper(),
                "payment_method": recovery_case.payment_method,
                "customer_contact_allowed": customer_contact_allowed,
                "source_incident_id": source_incident_id,
            },
            occurred_at=opened_at,
        ),
    )

    return RecoveryCaseCreationResult(
        disposition=RecoveryCaseCreationDisposition.CREATED,
        recovery_case=recovery_case,
        audit_event=audit_event,
    )
