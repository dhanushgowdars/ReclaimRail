import asyncio
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models.payment_lab import PaymentLabRun, PaymentLabRunStatus
from app.db.models.recovery import RecoveryCase
from app.domain.recovery import (
    DEFAULT_RECOVERY_PLANNER_POLICY,
    RecoveryCaseStatus,
    RecoveryChannel,
    RecoveryPlannerPolicy,
)
from app.integrations.gemini import (
    GeminiRecoveryPlanProvider,
    RecoveryPlannerSource,
)
from app.services.payment_lab_recovery_service import (
    DEFAULT_PAYMENT_LAB_RECOVERY_CLAIM_TIMEOUT,
    PaymentLabRecoveryConflictError,
    PaymentLabRecoveryIneligibleError,
    PaymentLabRecoveryRunNotFoundError,
    PaymentLabRecoveryRunNotReadyError,
    PaymentLabRecoveryStartDisposition,
    PaymentLabRecoveryStartResult,
    start_payment_lab_recovery,
)
from app.services.recovery_approval_service import (
    DEFAULT_APPROVAL_THRESHOLD_MINOR,
    DEFAULT_APPROVAL_WINDOW,
)

SessionFactory = async_sessionmaker[AsyncSession]

DEFAULT_ALTERNATE_PAYMENT_METHODS = (
    "upi",
    "card",
    "netbanking",
    "wallet",
)

# Give signed failure projection a short, real stabilization window before the
# agent claims the run. This keeps provider evidence and recovery execution as
# distinct persisted states and avoids racing duplicate/out-of-order webhooks.
SIGNED_FAILURE_STABILIZATION_DELAY = timedelta(seconds=5)


@dataclass(frozen=True, slots=True)
class PaymentLabRecoveryCandidate:
    payment_lab_run_id: UUID
    payment_method: str
    test_email_contact_consent: bool


@dataclass(frozen=True, slots=True)
class PaymentLabRecoveryBatchFailure:
    payment_lab_run_id: UUID
    error_type: str
    retryable: bool


@dataclass(frozen=True, slots=True)
class PaymentLabRecoveryBatchResult:
    discovered_run_ids: tuple[UUID, ...]
    start_results: tuple[PaymentLabRecoveryStartResult, ...]
    failures: tuple[PaymentLabRecoveryBatchFailure, ...]
    skipped_run_ids: tuple[UUID, ...]

    @property
    def discovered(self) -> int:
        return len(self.discovered_run_ids)

    @property
    def started(self) -> int:
        return sum(
            result.disposition is PaymentLabRecoveryStartDisposition.STARTED
            for result in self.start_results
        )

    @property
    def already_running(self) -> int:
        return sum(
            result.disposition is PaymentLabRecoveryStartDisposition.ALREADY_RUNNING
            for result in self.start_results
        )

    @property
    def already_planned(self) -> int:
        return sum(
            result.disposition is PaymentLabRecoveryStartDisposition.ALREADY_PLANNED
            for result in self.start_results
        )

    @property
    def gemini_plans(self) -> int:
        return sum(
            result.planner_source is RecoveryPlannerSource.GEMINI for result in self.start_results
        )

    @property
    def deterministic_plans(self) -> int:
        return sum(
            result.planner_source is RecoveryPlannerSource.DETERMINISTIC
            for result in self.start_results
        )

    @property
    def fallback_plans(self) -> int:
        return sum(result.planner_fallback_used is True for result in self.start_results)

    @property
    def retryable_failures(self) -> int:
        return sum(failure.retryable for failure in self.failures)

    @property
    def permanent_failures(self) -> int:
        return sum(not failure.retryable for failure in self.failures)

    @property
    def skipped(self) -> int:
        return len(self.skipped_run_ids)


def _require_timezone_aware(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Payment Lab recovery batch time must be timezone-aware")


def build_alternate_payment_methods(
    payment_method: str,
    *,
    supported_methods: Sequence[str] = DEFAULT_ALTERNATE_PAYMENT_METHODS,
) -> tuple[str, ...]:
    normalized_method = payment_method.strip().lower()
    normalized_supported = tuple(
        dict.fromkeys(method.strip().lower() for method in supported_methods if method.strip()),
    )
    return tuple(method for method in normalized_supported if method != normalized_method)


async def discover_payment_lab_recovery_candidates(
    session: AsyncSession,
    *,
    reference_time: datetime,
    batch_size: int,
    claim_timeout: timedelta = DEFAULT_PAYMENT_LAB_RECOVERY_CLAIM_TIMEOUT,
) -> tuple[PaymentLabRecoveryCandidate, ...]:
    _require_timezone_aware(reference_time)

    if not 1 <= batch_size <= 100:
        raise ValueError("Payment Lab recovery batch size must be between 1 and 100")
    if claim_timeout <= timedelta(0):
        raise ValueError("Payment Lab recovery claim timeout must be positive")

    result = await session.execute(
        select(
            PaymentLabRun.id,
            PaymentLabRun.payment_method,
            PaymentLabRun.test_email_contact_consent,
        )
        .outerjoin(
            RecoveryCase,
            RecoveryCase.payment_attempt_id == PaymentLabRun.payment_attempt_id,
        )
        .where(
            PaymentLabRun.payment_attempt_id.is_not(None),
            or_(
                and_(
                    PaymentLabRun.status == PaymentLabRunStatus.PAYMENT_ATTEMPTED.value,
                    PaymentLabRun.updated_at <= reference_time - SIGNED_FAILURE_STABILIZATION_DELAY,
                ),
                and_(
                    PaymentLabRun.status == PaymentLabRunStatus.RECOVERY_RUNNING.value,
                    PaymentLabRun.updated_at <= reference_time - claim_timeout,
                    or_(
                        RecoveryCase.id.is_(None),
                        RecoveryCase.status.in_(
                            (
                                RecoveryCaseStatus.OPEN.value,
                                RecoveryCaseStatus.PLANNING.value,
                            ),
                        ),
                    ),
                ),
                and_(
                    PaymentLabRun.status == PaymentLabRunStatus.RECOVERY_RUNNING.value,
                    RecoveryCase.status == RecoveryCaseStatus.WAITING.value,
                    RecoveryCase.next_action_at.is_not(None),
                    RecoveryCase.next_action_at <= reference_time,
                ),
            ),
        )
        .order_by(
            PaymentLabRun.updated_at,
            PaymentLabRun.id,
        )
        .limit(batch_size),
    )

    return tuple(
        PaymentLabRecoveryCandidate(
            payment_lab_run_id=run_id,
            payment_method=payment_method,
            test_email_contact_consent=test_email_contact_consent,
        )
        for run_id, payment_method, test_email_contact_consent in result.all()
    )


async def run_payment_lab_recovery_batch(
    session_factory: SessionFactory,
    *,
    reference_time: datetime,
    provider: GeminiRecoveryPlanProvider | None,
    batch_size: int = 25,
    supported_payment_methods: Sequence[str] = DEFAULT_ALTERNATE_PAYMENT_METHODS,
    claim_timeout: timedelta = DEFAULT_PAYMENT_LAB_RECOVERY_CLAIM_TIMEOUT,
    approval_threshold_minor: int = DEFAULT_APPROVAL_THRESHOLD_MINOR,
    approval_window: timedelta = DEFAULT_APPROVAL_WINDOW,
    planner_policy: RecoveryPlannerPolicy = DEFAULT_RECOVERY_PLANNER_POLICY,
) -> PaymentLabRecoveryBatchResult:
    """Start bounded recovery for verified Payment Lab failures.

    Customer contact remains disabled unless the individual Test Mode run has
    explicitly recorded test-email consent. This keeps the normal lab safe
    while allowing one auditable, controlled notification scenario.
    """

    _require_timezone_aware(reference_time)

    async with session_factory() as discovery_session:
        candidates = await discover_payment_lab_recovery_candidates(
            discovery_session,
            reference_time=reference_time,
            batch_size=batch_size,
            claim_timeout=claim_timeout,
        )

    start_results: list[PaymentLabRecoveryStartResult] = []
    failures: list[PaymentLabRecoveryBatchFailure] = []
    skipped_run_ids: list[UUID] = []

    for candidate in candidates:
        try:
            result = await start_payment_lab_recovery(
                session_factory,
                payment_lab_run_id=candidate.payment_lab_run_id,
                started_at=reference_time,
                customer_contact_allowed=candidate.test_email_contact_consent,
                available_channels=(
                    (RecoveryChannel.EMAIL,) if candidate.test_email_contact_consent else ()
                ),
                alternate_payment_methods=build_alternate_payment_methods(
                    candidate.payment_method,
                    supported_methods=supported_payment_methods,
                ),
                provider=provider,
                claim_timeout=claim_timeout,
                approval_threshold_minor=approval_threshold_minor,
                approval_window=approval_window,
                planner_policy=planner_policy,
            )
            start_results.append(result)
        except asyncio.CancelledError:
            raise
        except (
            PaymentLabRecoveryRunNotFoundError,
            PaymentLabRecoveryRunNotReadyError,
        ):
            skipped_run_ids.append(candidate.payment_lab_run_id)
        except (
            PaymentLabRecoveryConflictError,
            PaymentLabRecoveryIneligibleError,
        ) as error:
            failures.append(
                PaymentLabRecoveryBatchFailure(
                    payment_lab_run_id=candidate.payment_lab_run_id,
                    error_type=type(error).__name__,
                    retryable=False,
                ),
            )
        except Exception as error:
            failures.append(
                PaymentLabRecoveryBatchFailure(
                    payment_lab_run_id=candidate.payment_lab_run_id,
                    error_type=type(error).__name__,
                    retryable=True,
                ),
            )

    return PaymentLabRecoveryBatchResult(
        discovered_run_ids=tuple(candidate.payment_lab_run_id for candidate in candidates),
        start_results=tuple(start_results),
        failures=tuple(failures),
        skipped_run_ids=tuple(skipped_run_ids),
    )
