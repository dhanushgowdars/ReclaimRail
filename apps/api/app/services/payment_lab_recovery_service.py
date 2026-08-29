import asyncio
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models.payment_lab import PaymentLabRun, PaymentLabRunStatus
from app.db.models.recovery import RecoveryCase
from app.domain.recovery import RecoveryCaseStatus, RecoveryChannel
from app.integrations.gemini import (
    GeminiRecoveryPlanProvider,
    RecoveryPlannerSource,
)
from app.services.recovery_agent_service import (
    RecoveryAgentExecution,
    execute_recovery_agent,
)
from app.services.recovery_approval_service import (
    DEFAULT_APPROVAL_THRESHOLD_MINOR,
    DEFAULT_APPROVAL_WINDOW,
)
from app.services.recovery_case_service import (
    RecoveryCaseCreationDisposition,
    RecoveryCaseIneligibilityReason,
    create_or_get_recovery_case,
)

SessionFactory = async_sessionmaker[AsyncSession]

PLANNABLE_CASE_STATUSES = {
    RecoveryCaseStatus.OPEN,
    RecoveryCaseStatus.WAITING,
}
DEFAULT_PAYMENT_LAB_RECOVERY_CLAIM_TIMEOUT = timedelta(seconds=60)


class PaymentLabRecoveryError(RuntimeError):
    """Base error for starting a bounded Payment Lab recovery."""


class PaymentLabRecoveryRunNotFoundError(PaymentLabRecoveryError):
    pass


class PaymentLabRecoveryRunNotReadyError(PaymentLabRecoveryError):
    pass


class PaymentLabRecoveryConflictError(PaymentLabRecoveryError):
    pass


class PaymentLabRecoveryIneligibleError(PaymentLabRecoveryError):
    def __init__(
        self,
        reasons: tuple[RecoveryCaseIneligibilityReason, ...],
    ) -> None:
        super().__init__("Payment Lab payment is not eligible for recovery")
        self.reasons = reasons


class PaymentLabRecoveryStartDisposition(StrEnum):
    STARTED = "started"
    ALREADY_RUNNING = "already_running"
    ALREADY_PLANNED = "already_planned"


@dataclass(frozen=True, slots=True)
class PaymentLabRecoveryStartResult:
    payment_lab_run_id: UUID
    payment_attempt_id: UUID
    recovery_case_id: UUID
    disposition: PaymentLabRecoveryStartDisposition
    recovery_case_created: bool
    planner_source: RecoveryPlannerSource | None
    planner_fallback_used: bool | None


@dataclass(frozen=True, slots=True)
class _PaymentLabRecoveryClaim:
    payment_lab_run_id: UUID
    payment_attempt_id: UUID
    recovery_case_id: UUID
    disposition: PaymentLabRecoveryStartDisposition
    recovery_case_created: bool
    should_execute_agent: bool


def _require_timezone_aware(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Payment Lab recovery time must be timezone-aware")


async def _find_recovery_case(
    session: AsyncSession,
    *,
    payment_attempt_id: UUID,
) -> RecoveryCase | None:
    result = await session.execute(
        select(RecoveryCase).where(
            RecoveryCase.payment_attempt_id == payment_attempt_id,
        ),
    )
    return result.scalar_one_or_none()


async def _claim_payment_lab_recovery(
    session: AsyncSession,
    *,
    payment_lab_run_id: UUID,
    started_at: datetime,
    customer_contact_allowed: bool,
    claim_timeout: timedelta = DEFAULT_PAYMENT_LAB_RECOVERY_CLAIM_TIMEOUT,
) -> _PaymentLabRecoveryClaim:
    if claim_timeout <= timedelta(0):
        raise ValueError("Payment Lab recovery claim timeout must be positive")

    run_result = await session.execute(
        select(PaymentLabRun).where(PaymentLabRun.id == payment_lab_run_id).with_for_update(),
    )
    payment_lab_run = run_result.scalar_one_or_none()

    if payment_lab_run is None:
        raise PaymentLabRecoveryRunNotFoundError(
            f"Payment Lab run {payment_lab_run_id} does not exist",
        )

    try:
        run_status = PaymentLabRunStatus(payment_lab_run.status)
    except ValueError as error:
        raise PaymentLabRecoveryConflictError(
            "Payment Lab run contains an invalid status",
        ) from error

    if payment_lab_run.payment_attempt_id is None:
        raise PaymentLabRecoveryConflictError(
            "Payment Lab run has no verified payment attempt",
        )

    payment_attempt_id = payment_lab_run.payment_attempt_id

    if run_status is PaymentLabRunStatus.RECOVERY_RUNNING:
        recovery_case = await _find_recovery_case(
            session,
            payment_attempt_id=payment_attempt_id,
        )

        if recovery_case is None:
            raise PaymentLabRecoveryConflictError(
                "Recovery-running Payment Lab run has no recovery case",
            )

        try:
            recovery_case_status = RecoveryCaseStatus(recovery_case.status)
        except ValueError as error:
            raise PaymentLabRecoveryConflictError(
                "Payment Lab recovery case contains an invalid status",
            ) from error

        claim_is_stale = payment_lab_run.updated_at <= started_at - claim_timeout
        if not claim_is_stale:
            return _PaymentLabRecoveryClaim(
                payment_lab_run_id=payment_lab_run.id,
                payment_attempt_id=payment_attempt_id,
                recovery_case_id=recovery_case.id,
                disposition=PaymentLabRecoveryStartDisposition.ALREADY_RUNNING,
                recovery_case_created=False,
                should_execute_agent=False,
            )
        if (
            recovery_case_status is RecoveryCaseStatus.WAITING
            and recovery_case.next_action_at is not None
            and recovery_case.next_action_at > started_at
        ):
            return _PaymentLabRecoveryClaim(
                payment_lab_run_id=payment_lab_run.id,
                payment_attempt_id=payment_attempt_id,
                recovery_case_id=recovery_case.id,
                disposition=PaymentLabRecoveryStartDisposition.ALREADY_PLANNED,
                recovery_case_created=False,
                should_execute_agent=False,
            )
        if recovery_case_status not in PLANNABLE_CASE_STATUSES:
            return _PaymentLabRecoveryClaim(
                payment_lab_run_id=payment_lab_run.id,
                payment_attempt_id=payment_attempt_id,
                recovery_case_id=recovery_case.id,
                disposition=PaymentLabRecoveryStartDisposition.ALREADY_PLANNED,
                recovery_case_created=False,
                should_execute_agent=False,
            )

        # A process may die after claiming a run and before persisting an agent
        # result. Re-enter the normal, row-locked creation path after the lease
        # expires instead of leaving the run permanently stuck.
        payment_lab_run.status = PaymentLabRunStatus.PAYMENT_ATTEMPTED.value
        run_status = PaymentLabRunStatus.PAYMENT_ATTEMPTED

    if run_status is not PaymentLabRunStatus.PAYMENT_ATTEMPTED:
        raise PaymentLabRecoveryRunNotReadyError(
            f"Payment Lab run cannot start recovery from {run_status.value}",
        )

    creation = await create_or_get_recovery_case(
        session,
        payment_attempt_id=payment_attempt_id,
        opened_at=started_at,
        customer_contact_allowed=customer_contact_allowed,
    )

    if creation.disposition is RecoveryCaseCreationDisposition.INELIGIBLE:
        raise PaymentLabRecoveryIneligibleError(
            creation.ineligibility_reasons,
        )

    recovery_case = creation.recovery_case

    if recovery_case is None:
        raise PaymentLabRecoveryConflictError(
            "Eligible Payment Lab recovery did not resolve a recovery case",
        )

    try:
        case_status = RecoveryCaseStatus(recovery_case.status)
    except ValueError as error:
        raise PaymentLabRecoveryConflictError(
            "Payment Lab recovery case contains an invalid status",
        ) from error

    should_execute_agent = case_status in PLANNABLE_CASE_STATUSES
    disposition = (
        PaymentLabRecoveryStartDisposition.STARTED
        if should_execute_agent
        else PaymentLabRecoveryStartDisposition.ALREADY_PLANNED
    )

    payment_lab_run.status = PaymentLabRunStatus.RECOVERY_RUNNING.value
    payment_lab_run.updated_at = started_at
    payment_lab_run.version += 1

    return _PaymentLabRecoveryClaim(
        payment_lab_run_id=payment_lab_run.id,
        payment_attempt_id=payment_attempt_id,
        recovery_case_id=recovery_case.id,
        disposition=disposition,
        recovery_case_created=(creation.disposition is RecoveryCaseCreationDisposition.CREATED),
        should_execute_agent=should_execute_agent,
    )


async def _release_failed_claim(
    session_factory: SessionFactory,
    *,
    payment_lab_run_id: UUID,
    recovery_case_id: UUID,
    released_at: datetime,
) -> None:
    async with session_factory.begin() as session:
        run_result = await session.execute(
            select(PaymentLabRun).where(PaymentLabRun.id == payment_lab_run_id).with_for_update(),
        )
        payment_lab_run = run_result.scalar_one_or_none()

        case_result = await session.execute(
            select(RecoveryCase).where(RecoveryCase.id == recovery_case_id).with_for_update(),
        )
        recovery_case = case_result.scalar_one_or_none()

        if payment_lab_run is None or recovery_case is None:
            return

        if payment_lab_run.status != PaymentLabRunStatus.RECOVERY_RUNNING.value:
            return

        try:
            case_status = RecoveryCaseStatus(recovery_case.status)
        except ValueError:
            return

        if case_status not in PLANNABLE_CASE_STATUSES:
            return

        payment_lab_run.status = PaymentLabRunStatus.PAYMENT_ATTEMPTED.value
        payment_lab_run.updated_at = released_at
        payment_lab_run.version += 1


async def start_payment_lab_recovery(
    session_factory: SessionFactory,
    *,
    payment_lab_run_id: UUID,
    started_at: datetime,
    customer_contact_allowed: bool,
    available_channels: Sequence[RecoveryChannel],
    alternate_payment_methods: Sequence[str],
    provider: GeminiRecoveryPlanProvider | None,
    claim_timeout: timedelta = DEFAULT_PAYMENT_LAB_RECOVERY_CLAIM_TIMEOUT,
    approval_threshold_minor: int = DEFAULT_APPROVAL_THRESHOLD_MINOR,
    approval_window: timedelta = DEFAULT_APPROVAL_WINDOW,
) -> PaymentLabRecoveryStartResult:
    """Claim a verified failure and start the existing bounded recovery agent."""

    _require_timezone_aware(started_at)

    async with session_factory.begin() as session:
        claim = await _claim_payment_lab_recovery(
            session,
            payment_lab_run_id=payment_lab_run_id,
            started_at=started_at,
            customer_contact_allowed=customer_contact_allowed,
            claim_timeout=claim_timeout,
        )

    if not claim.should_execute_agent:
        return PaymentLabRecoveryStartResult(
            payment_lab_run_id=claim.payment_lab_run_id,
            payment_attempt_id=claim.payment_attempt_id,
            recovery_case_id=claim.recovery_case_id,
            disposition=claim.disposition,
            recovery_case_created=claim.recovery_case_created,
            planner_source=None,
            planner_fallback_used=None,
        )

    execution: RecoveryAgentExecution

    try:
        execution = await execute_recovery_agent(
            session_factory,
            recovery_case_id=claim.recovery_case_id,
            available_channels=available_channels,
            alternate_payment_methods=alternate_payment_methods,
            planned_at=started_at,
            provider=provider,
            approval_threshold_minor=approval_threshold_minor,
            approval_window=approval_window,
        )
    except asyncio.CancelledError:
        await asyncio.shield(
            _release_failed_claim(
                session_factory,
                payment_lab_run_id=claim.payment_lab_run_id,
                recovery_case_id=claim.recovery_case_id,
                released_at=started_at,
            ),
        )
        raise
    except Exception:
        await _release_failed_claim(
            session_factory,
            payment_lab_run_id=claim.payment_lab_run_id,
            recovery_case_id=claim.recovery_case_id,
            released_at=started_at,
        )
        raise

    return PaymentLabRecoveryStartResult(
        payment_lab_run_id=claim.payment_lab_run_id,
        payment_attempt_id=claim.payment_attempt_id,
        recovery_case_id=claim.recovery_case_id,
        disposition=claim.disposition,
        recovery_case_created=claim.recovery_case_created,
        planner_source=execution.planner_result.source,
        planner_fallback_used=execution.planner_result.fallback_used,
    )
