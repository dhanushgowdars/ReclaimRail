from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models.payment import PaymentAttempt
from app.db.models.recovery import (
    RecoveryAction,
    RecoveryActionStatus,
    RecoveryAuditActor,
    RecoveryAuditEvent,
    RecoveryCase,
)
from app.domain.recovery import (
    RecoveryActionType,
    RecoveryCaseStatus,
)
from app.domain.recovery.outcome_classifier import (
    RecoveryOutcomeReconciliationInput,
    RecoveryPaymentLinkOutcomeState,
    reconcile_recovery_outcome,
)
from app.domain.recovery.outcomes import (
    RecoveryOutcomeAttribution,
    RecoveryOutcomeProof,
    RecoveryOutcomeStatus,
)
from app.integrations.razorpay.payment_links import (
    RazorpayPaymentLink,
    RazorpayPaymentLinkProvider,
    RazorpayPaymentLinkProviderError,
    RazorpayPaymentLinkStatus,
)
from app.services.recovery_action_executor import (
    build_payment_link_reference_id,
)
from app.services.recovery_audit_store import (
    RecoveryAuditAppendRequest,
    append_recovery_audit_event,
)
from app.services.recovery_outcome_service import (
    persist_recovery_outcome_proof,
)

SessionFactory = async_sessionmaker[AsyncSession]


class RecoveryOutcomeReconciliationCaseNotFoundError(LookupError):
    pass


class RecoveryOutcomeReconciliationPaymentNotFoundError(LookupError):
    pass


class RecoveryOutcomeReconciliationActionNotFoundError(LookupError):
    pass


class RecoveryOutcomeReconciliationNotReadyError(ValueError):
    pass


class RecoveryOutcomeProviderEvidenceError(ValueError):
    pass


class RecoveryOutcomeReconciliationProviderFailure(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        retryable: bool,
        status_code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.retryable = retryable
        self.status_code = status_code


@dataclass(frozen=True, slots=True)
class PreparedRecoveryOutcomeReconciliation:
    recovery_case_id: UUID
    payment_attempt_id: UUID
    recovery_action_id: UUID

    provider_payment_id: str
    payment_link_id: str
    reference_id: str

    original_amount_minor: int
    currency: str


@dataclass(frozen=True, slots=True)
class RecoveryOutcomeReconciliationResult:
    recovery_case_id: UUID
    recovery_action_id: UUID
    payment_link_id: str

    outcome_status: RecoveryOutcomeStatus
    attribution: RecoveryOutcomeAttribution
    provider_status: RazorpayPaymentLinkStatus

    recovery_outcome_id: UUID
    recovery_outcome_observation_id: UUID | None
    projection_created: bool
    projection_updated: bool
    observation_created: bool

    case_marked_recovered: bool


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
        raise RecoveryOutcomeReconciliationCaseNotFoundError(
            f"Recovery case {recovery_case_id} does not exist",
        )

    return recovery_case


async def _load_payment_attempt(
    session: AsyncSession,
    *,
    payment_attempt_id: UUID,
) -> PaymentAttempt:
    result = await session.execute(
        select(PaymentAttempt)
        .where(
            PaymentAttempt.id == payment_attempt_id,
        )
        .with_for_update(),
    )
    payment_attempt = result.scalar_one_or_none()

    if payment_attempt is None:
        raise RecoveryOutcomeReconciliationPaymentNotFoundError(
            f"Payment attempt {payment_attempt_id} does not exist",
        )

    return payment_attempt


async def _load_payment_link_action(
    session: AsyncSession,
    *,
    recovery_action_id: UUID,
) -> RecoveryAction:
    result = await session.execute(
        select(RecoveryAction)
        .where(
            RecoveryAction.id == recovery_action_id,
        )
        .with_for_update(),
    )
    recovery_action = result.scalar_one_or_none()

    if recovery_action is None:
        raise RecoveryOutcomeReconciliationActionNotFoundError(
            f"Recovery action {recovery_action_id} does not exist",
        )

    return recovery_action


def _validate_payment_link_action(
    *,
    recovery_case: RecoveryCase,
    payment_attempt: PaymentAttempt,
    recovery_action: RecoveryAction,
) -> None:
    if recovery_action.recovery_case_id != recovery_case.id:
        raise RecoveryOutcomeProviderEvidenceError(
            "Recovery action does not belong to the recovery case",
        )

    if recovery_action.action_type != RecoveryActionType.CREATE_PAYMENT_LINK.value:
        raise RecoveryOutcomeReconciliationNotReadyError(
            "Outcome reconciliation requires a create-payment-link action",
        )

    if recovery_action.status != RecoveryActionStatus.SUCCEEDED.value:
        raise RecoveryOutcomeReconciliationNotReadyError(
            "Outcome reconciliation requires a successful Payment Link action",
        )

    if recovery_action.provider_action_id is None:
        raise RecoveryOutcomeReconciliationNotReadyError(
            "Successful Payment Link action has no provider Payment Link ID",
        )

    if recovery_action.amount_minor != recovery_case.amount_minor:
        raise RecoveryOutcomeProviderEvidenceError(
            "Recovery action amount does not match the recovery case",
        )

    if recovery_action.currency != recovery_case.currency:
        raise RecoveryOutcomeProviderEvidenceError(
            "Recovery action currency does not match the recovery case",
        )

    if payment_attempt.id != recovery_case.payment_attempt_id:
        raise RecoveryOutcomeProviderEvidenceError(
            "Payment attempt does not match the recovery case",
        )


async def prepare_recovery_outcome_reconciliation(
    session: AsyncSession,
    *,
    recovery_case_id: UUID,
    recovery_action_id: UUID,
) -> PreparedRecoveryOutcomeReconciliation:
    """
    Load one successful Payment Link action before making a provider request.

    This transaction intentionally ends before the Razorpay API call. We do
    not hold database locks while waiting for an external network response.
    """
    recovery_case = await _load_recovery_case(
        session,
        recovery_case_id=recovery_case_id,
    )
    payment_attempt = await _load_payment_attempt(
        session,
        payment_attempt_id=recovery_case.payment_attempt_id,
    )
    recovery_action = await _load_payment_link_action(
        session,
        recovery_action_id=recovery_action_id,
    )

    _validate_payment_link_action(
        recovery_case=recovery_case,
        payment_attempt=payment_attempt,
        recovery_action=recovery_action,
    )

    payment_link_id = recovery_action.provider_action_id

    if payment_link_id is None:
        raise RuntimeError(
            "Payment Link action unexpectedly has no provider action ID",
        )

    return PreparedRecoveryOutcomeReconciliation(
        recovery_case_id=recovery_case.id,
        payment_attempt_id=payment_attempt.id,
        recovery_action_id=recovery_action.id,
        provider_payment_id=payment_attempt.provider_payment_id,
        payment_link_id=payment_link_id,
        reference_id=build_payment_link_reference_id(
            recovery_action.id,
        ),
        original_amount_minor=recovery_case.amount_minor,
        currency=recovery_case.currency,
    )


def _validate_provider_payment_link(
    *,
    prepared: PreparedRecoveryOutcomeReconciliation,
    payment_link: RazorpayPaymentLink,
) -> None:
    if payment_link.payment_link_id != prepared.payment_link_id:
        raise RecoveryOutcomeProviderEvidenceError(
            "Fetched Payment Link ID did not match the recovery action",
        )

    if payment_link.reference_id != prepared.reference_id:
        raise RecoveryOutcomeProviderEvidenceError(
            "Fetched Payment Link reference did not match the recovery action",
        )

    if payment_link.amount_minor != prepared.original_amount_minor:
        raise RecoveryOutcomeProviderEvidenceError(
            "Fetched Payment Link amount did not match the recovery case",
        )

    if payment_link.currency != prepared.currency:
        raise RecoveryOutcomeProviderEvidenceError(
            "Fetched Payment Link currency did not match the recovery case",
        )


def _provider_observed_at(
    *,
    payment_link: RazorpayPaymentLink,
    reconciled_at: datetime,
) -> datetime:
    _require_timezone_aware(
        reconciled_at,
        field_name="Reconciliation time",
    )

    if payment_link.provider_updated_at is None:
        return reconciled_at

    return datetime.fromtimestamp(
        payment_link.provider_updated_at,
        tz=UTC,
    )


def _provider_evidence_event_id(
    payment_link: RazorpayPaymentLink,
) -> str:
    """
    Stable, PII-free evidence identifier.

    The identifier changes only when Razorpay's observable Payment Link state
    changes, making repeated reconciliation idempotent.
    """
    updated_at = (
        str(payment_link.provider_updated_at)
        if payment_link.provider_updated_at is not None
        else "unknown"
    )

    return (
        "razorpay:payment_link:"
        f"{payment_link.payment_link_id}:"
        f"status:{payment_link.status.value}:"
        f"amount_paid:{payment_link.amount_paid_minor}:"
        f"updated_at:{updated_at}"
    )


def _link_state(
    status: RazorpayPaymentLinkStatus,
) -> RecoveryPaymentLinkOutcomeState:
    return {
        RazorpayPaymentLinkStatus.CREATED: (RecoveryPaymentLinkOutcomeState.PENDING),
        RazorpayPaymentLinkStatus.PAID: (RecoveryPaymentLinkOutcomeState.PAID),
        RazorpayPaymentLinkStatus.EXPIRED: (RecoveryPaymentLinkOutcomeState.EXPIRED),
        RazorpayPaymentLinkStatus.CANCELLED: (RecoveryPaymentLinkOutcomeState.CANCELLED),
    }[status]


def _build_unresolved_partial_payment_proof(
    *,
    prepared: PreparedRecoveryOutcomeReconciliation,
    observed_at: datetime,
    evidence_event_id: str,
) -> RecoveryOutcomeProof:
    """
    Do not report partially paid links as recovered revenue.

    The current ledger intentionally has no partial-recovery financial state.
    A partial payment is preserved as evidence but escalated to unresolved
    reconciliation until a final provider state is available.
    """
    return RecoveryOutcomeProof(
        recovery_case_id=prepared.recovery_case_id,
        payment_attempt_id=prepared.payment_attempt_id,
        recovery_action_id=prepared.recovery_action_id,
        provider_payment_id=prepared.provider_payment_id,
        payment_link_id=prepared.payment_link_id,
        status=RecoveryOutcomeStatus.UNRESOLVED,
        attribution=RecoveryOutcomeAttribution.NONE,
        original_amount_minor=prepared.original_amount_minor,
        currency=prepared.currency,
        occurred_at=observed_at,
        evidence_event_ids=(evidence_event_id,),
    )


def _build_outcome_proof(
    *,
    prepared: PreparedRecoveryOutcomeReconciliation,
    recovery_case: RecoveryCase,
    payment_attempt: PaymentAttempt,
    payment_link: RazorpayPaymentLink,
    reconciled_at: datetime,
) -> RecoveryOutcomeProof:
    observed_at = _provider_observed_at(
        payment_link=payment_link,
        reconciled_at=reconciled_at,
    )
    evidence_event_id = _provider_evidence_event_id(
        payment_link,
    )

    if payment_link.status is RazorpayPaymentLinkStatus.PARTIALLY_PAID:
        return _build_unresolved_partial_payment_proof(
            prepared=prepared,
            observed_at=observed_at,
            evidence_event_id=evidence_event_id,
        )

    if (
        payment_link.status is RazorpayPaymentLinkStatus.PAID
        and payment_link.amount_paid_minor == 0
    ):
        raise RecoveryOutcomeProviderEvidenceError(
            "Razorpay reported a paid Payment Link with zero paid amount",
        )

    reconciliation_input = RecoveryOutcomeReconciliationInput(
        recovery_case_id=prepared.recovery_case_id,
        payment_attempt_id=prepared.payment_attempt_id,
        recovery_action_id=prepared.recovery_action_id,
        provider_payment_id=prepared.provider_payment_id,
        payment_link_id=prepared.payment_link_id,
        original_amount_minor=prepared.original_amount_minor,
        currency=prepared.currency,
        payment_link_state=_link_state(
            payment_link.status,
        ),
        observed_at=observed_at,
        evidence_event_ids=(evidence_event_id,),
        payment_link_paid_amount_minor=payment_link.amount_paid_minor,
        late_authorization_detected_at=(
            payment_attempt.late_authorization_detected_at
            or recovery_case.late_authorization_detected_at
        ),
    )

    return reconcile_recovery_outcome(
        reconciliation_input,
    )


def _mark_case_recovered(
    *,
    recovery_case: RecoveryCase,
    recovered_at: datetime,
) -> bool:
    if (
        recovery_case.status == RecoveryCaseStatus.RECOVERED.value
        and recovery_case.recovered_at == recovered_at
        and recovery_case.closed_at == recovered_at
        and recovery_case.active_payment_link_id is None
    ):
        return False

    recovery_case.status = RecoveryCaseStatus.RECOVERED.value
    recovery_case.recovered_at = recovered_at
    recovery_case.closed_at = recovered_at
    recovery_case.close_reason = "payment_link_recovered"
    recovery_case.active_payment_link_id = None
    recovery_case.next_action_at = None
    recovery_case.version += 1

    return True


def _mark_case_closed_without_recovery(
    *,
    recovery_case: RecoveryCase,
    outcome_status: RecoveryOutcomeStatus,
    closed_at: datetime,
) -> bool:
    close_reasons = {
        RecoveryOutcomeStatus.PAYMENT_LINK_EXPIRED: "payment_link_expired_without_recovery",
        RecoveryOutcomeStatus.PAYMENT_LINK_CANCELLED: "payment_link_cancelled_without_recovery",
        RecoveryOutcomeStatus.DUPLICATE_COLLECTION_PREVENTED: "duplicate_collection_prevented",
    }
    close_reason = close_reasons.get(outcome_status)
    if close_reason is None:
        return False
    if (
        recovery_case.status == RecoveryCaseStatus.CANCELLED.value
        and recovery_case.closed_at == closed_at
        and recovery_case.close_reason == close_reason
        and recovery_case.active_payment_link_id is None
    ):
        return False
    recovery_case.status = RecoveryCaseStatus.CANCELLED.value
    recovery_case.closed_at = closed_at
    recovery_case.close_reason = close_reason
    recovery_case.active_payment_link_id = None
    recovery_case.next_action_at = None
    recovery_case.version += 1
    return True


async def complete_recovery_outcome_reconciliation(
    session: AsyncSession,
    *,
    prepared: PreparedRecoveryOutcomeReconciliation,
    payment_link: RazorpayPaymentLink,
    reconciled_at: datetime,
    evidence_source: str = "provider_poll",
    provider_event_id: str | None = None,
) -> RecoveryOutcomeReconciliationResult:
    """
    Verify fetched provider evidence, persist its proof, and audit it.

    All database changes below occur in one transaction. Replayed evidence
    creates neither a duplicate observation nor a duplicate audit event.
    """
    _require_timezone_aware(
        reconciled_at,
        field_name="Reconciliation time",
    )
    _validate_provider_payment_link(
        prepared=prepared,
        payment_link=payment_link,
    )

    recovery_case = await _load_recovery_case(
        session,
        recovery_case_id=prepared.recovery_case_id,
    )
    payment_attempt = await _load_payment_attempt(
        session,
        payment_attempt_id=prepared.payment_attempt_id,
    )
    recovery_action = await _load_payment_link_action(
        session,
        recovery_action_id=prepared.recovery_action_id,
    )

    _validate_payment_link_action(
        recovery_case=recovery_case,
        payment_attempt=payment_attempt,
        recovery_action=recovery_action,
    )

    if recovery_action.provider_action_id != prepared.payment_link_id:
        raise RecoveryOutcomeProviderEvidenceError(
            "Recovery Payment Link changed while provider evidence was fetched",
        )

    proof = _build_outcome_proof(
        prepared=prepared,
        recovery_case=recovery_case,
        payment_attempt=payment_attempt,
        payment_link=payment_link,
        reconciled_at=reconciled_at,
    )
    persistence = await persist_recovery_outcome_proof(
        session,
        proof=proof,
    )

    recovery_action.provider_action_status = payment_link.status.value

    case_marked_recovered = False

    if persistence.projection_updated and proof.status is RecoveryOutcomeStatus.RECOVERED:
        case_marked_recovered = _mark_case_recovered(
            recovery_case=recovery_case,
            recovered_at=proof.occurred_at,
        )
    elif persistence.projection_updated:
        _mark_case_closed_without_recovery(
            recovery_case=recovery_case,
            outcome_status=proof.status,
            closed_at=proof.occurred_at,
        )

    should_audit_provider_progress = not await _has_recorded_pending_provider_progress(
        session,
        recovery_action_id=recovery_action.id,
        outcome_status=proof.status,
    )
    if persistence.observation_created and should_audit_provider_progress:
        await append_recovery_audit_event(
            session,
            recovery_case_id=recovery_case.id,
            request=RecoveryAuditAppendRequest(
                event_type="outcome.payment_link.reconciled",
                actor_type=RecoveryAuditActor.RAZORPAY,
                recovery_action_id=recovery_action.id,
                agent_run_id=recovery_action.agent_run_id,
                event_data={
                    "outcome_status": proof.status.value,
                    "attribution": proof.attribution.value,
                    "provider_status": payment_link.status.value,
                    "amount_paid_minor": payment_link.amount_paid_minor,
                    "provider_updated_at": payment_link.provider_updated_at,
                    "outcome_fingerprint": (proof.evidence_event_ids[0]),
                    "projection_created": persistence.projection_created,
                    "projection_updated": persistence.projection_updated,
                    "evidence_source": evidence_source,
                    "provider_event_id": provider_event_id,
                },
                occurred_at=proof.occurred_at,
            ),
        )

    return RecoveryOutcomeReconciliationResult(
        recovery_case_id=recovery_case.id,
        recovery_action_id=recovery_action.id,
        payment_link_id=payment_link.payment_link_id,
        outcome_status=proof.status,
        attribution=proof.attribution,
        provider_status=payment_link.status,
        recovery_outcome_id=persistence.recovery_outcome_id,
        recovery_outcome_observation_id=(persistence.recovery_outcome_observation_id),
        projection_created=persistence.projection_created,
        projection_updated=persistence.projection_updated,
        observation_created=persistence.observation_created,
        case_marked_recovered=case_marked_recovered,
    )


async def _has_recorded_pending_provider_progress(
    session: AsyncSession,
    *,
    recovery_action_id: UUID,
    outcome_status: RecoveryOutcomeStatus,
) -> bool:
    """Keep the audit trail focused on provider-state transitions, not polls."""
    if outcome_status is not RecoveryOutcomeStatus.PAYMENT_LINK_PENDING:
        return False

    result = await session.execute(
        select(RecoveryAuditEvent.event_data)
        .where(
            RecoveryAuditEvent.recovery_action_id == recovery_action_id,
            RecoveryAuditEvent.event_type == "outcome.payment_link.reconciled",
        )
        .order_by(RecoveryAuditEvent.sequence_number.desc())
        .limit(1),
    )
    event_data = result.scalar_one_or_none()
    return isinstance(event_data, dict) and event_data.get("outcome_status") == (
        RecoveryOutcomeStatus.PAYMENT_LINK_PENDING.value
    )


async def reconcile_recovery_payment_link_webhook(
    session: AsyncSession,
    *,
    payment_link: RazorpayPaymentLink,
    provider_event_id: str,
    reconciled_at: datetime,
) -> RecoveryOutcomeReconciliationResult | None:
    """Reconcile a signed Payment Link event when it belongs to ReclaimRail.

    Events for unrelated merchant links are deliberately ignored.  The
    provider-link ID is only a correlation key; the normal reconciliation
    path still validates the reference, amount, currency and case linkage.
    """

    _require_timezone_aware(reconciled_at, field_name="Reconciliation time")
    result = await session.execute(
        select(RecoveryAction)
        .where(
            RecoveryAction.action_type == RecoveryActionType.CREATE_PAYMENT_LINK.value,
            RecoveryAction.provider_action_id == payment_link.payment_link_id,
        )
        .with_for_update(),
    )
    recovery_action = result.scalar_one_or_none()
    if recovery_action is None:
        return None

    prepared = await prepare_recovery_outcome_reconciliation(
        session,
        recovery_case_id=recovery_action.recovery_case_id,
        recovery_action_id=recovery_action.id,
    )
    return await complete_recovery_outcome_reconciliation(
        session,
        prepared=prepared,
        payment_link=payment_link,
        reconciled_at=reconciled_at,
        evidence_source="signed_webhook",
        provider_event_id=provider_event_id,
    )


async def reconcile_recovery_payment_link_outcome(
    session_factory: SessionFactory,
    *,
    recovery_case_id: UUID,
    recovery_action_id: UUID,
    provider: RazorpayPaymentLinkProvider,
    reconciled_at: datetime,
) -> RecoveryOutcomeReconciliationResult:
    """
    Fetch and reconcile one successful Razorpay Payment Link.

    The provider request is deliberately outside database transactions. The
    fetched state is validated again before its outcome proof is committed.
    """
    _require_timezone_aware(
        reconciled_at,
        field_name="Reconciliation time",
    )

    async with session_factory.begin() as session:
        prepared = await prepare_recovery_outcome_reconciliation(
            session,
            recovery_case_id=recovery_case_id,
            recovery_action_id=recovery_action_id,
        )

    try:
        payment_link = await provider.fetch_payment_link(
            prepared.payment_link_id,
        )
    except RazorpayPaymentLinkProviderError as error:
        raise RecoveryOutcomeReconciliationProviderFailure(
            "Razorpay Payment Link outcome fetch failed",
            retryable=error.retryable,
            status_code=error.status_code,
        ) from error

    async with session_factory.begin() as session:
        return await complete_recovery_outcome_reconciliation(
            session,
            prepared=prepared,
            payment_link=payment_link,
            reconciled_at=reconciled_at,
        )
