import asyncio
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
)

from app.db.models.payment import PaymentAttempt
from app.db.models.recovery import RecoveryCase
from app.domain.payments import STOP_RECOVERY_STATES
from app.domain.recovery import RecoveryCaseStatus
from app.integrations.razorpay.payment_links import (
    RazorpayPaymentLinkProvider,
)
from app.services.recovery_compensation_service import (
    RecoveryCompensationCaseNotFoundError,
    RecoveryCompensationDisposition,
    RecoveryCompensationNotRequiredError,
    RecoveryCompensationProviderFailure,
    RecoveryCompensationResult,
    compensate_late_authorized_recovery,
)

SessionFactory = async_sessionmaker[AsyncSession]

COMPENSATABLE_CASE_STATUSES = (
    RecoveryCaseStatus.READY.value,
    RecoveryCaseStatus.EXECUTING.value,
    RecoveryCaseStatus.WAITING.value,
)

STOP_RECOVERY_STATE_VALUES = tuple(state.value for state in STOP_RECOVERY_STATES)


@dataclass(frozen=True, slots=True)
class RecoveryCompensationBatchFailure:
    recovery_case_id: UUID
    error_type: str
    retryable: bool


@dataclass(frozen=True, slots=True)
class RecoveryCompensationBatchResult:
    discovered_case_ids: tuple[UUID, ...]
    compensation_results: tuple[
        RecoveryCompensationResult,
        ...,
    ]
    failures: tuple[
        RecoveryCompensationBatchFailure,
        ...,
    ]
    skipped_case_ids: tuple[UUID, ...]

    @property
    def discovered(self) -> int:
        return len(self.discovered_case_ids)

    @property
    def cancelled(self) -> int:
        return sum(
            result.disposition is RecoveryCompensationDisposition.CANCELLED
            for result in self.compensation_results
        )

    @property
    def already_cancelled(self) -> int:
        return sum(
            result.disposition is RecoveryCompensationDisposition.ALREADY_CANCELLED
            for result in self.compensation_results
        )

    @property
    def escalated(self) -> int:
        return sum(
            result.disposition is RecoveryCompensationDisposition.ESCALATED
            for result in self.compensation_results
        )

    @property
    def retryable_failures(self) -> int:
        return sum(failure.retryable for failure in self.failures)

    @property
    def permanent_failures(self) -> int:
        return sum(not failure.retryable for failure in self.failures)

    @property
    def skipped(self) -> int:
        return len(self.skipped_case_ids)


def _require_timezone_aware(
    value: datetime,
) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(
            "Recovery compensation batch time must be timezone-aware",
        )


async def discover_compensatable_recovery_case_ids(
    session: AsyncSession,
    *,
    reference_time: datetime,
    batch_size: int,
) -> tuple[UUID, ...]:
    _require_timezone_aware(reference_time)

    if not 1 <= batch_size <= 100:
        raise ValueError(
            "Recovery compensation batch size must be between 1 and 100",
        )

    result = await session.execute(
        select(RecoveryCase.id)
        .join(
            PaymentAttempt,
            PaymentAttempt.id == RecoveryCase.payment_attempt_id,
        )
        .where(
            RecoveryCase.active_payment_link_id.is_not(None),
            RecoveryCase.status.in_(
                COMPENSATABLE_CASE_STATUSES,
            ),
            or_(
                PaymentAttempt.current_state.in_(
                    STOP_RECOVERY_STATE_VALUES,
                ),
                PaymentAttempt.late_authorization_detected_at.is_not(None),
            ),
            or_(
                RecoveryCase.next_action_at.is_(None),
                RecoveryCase.next_action_at <= reference_time,
            ),
        )
        .order_by(
            RecoveryCase.next_action_at.asc().nulls_first(),
            RecoveryCase.updated_at,
            RecoveryCase.id,
        )
        .limit(batch_size),
    )

    return tuple(
        result.scalars().all(),
    )


async def run_recovery_compensation_batch(
    session_factory: SessionFactory,
    *,
    provider: RazorpayPaymentLinkProvider,
    reference_time: datetime,
    batch_size: int = 25,
) -> RecoveryCompensationBatchResult:
    _require_timezone_aware(reference_time)

    async with session_factory() as discovery_session:
        case_ids = await discover_compensatable_recovery_case_ids(
            discovery_session,
            reference_time=reference_time,
            batch_size=batch_size,
        )

    compensation_results: list[RecoveryCompensationResult] = []

    failures: list[RecoveryCompensationBatchFailure] = []

    skipped_case_ids: list[UUID] = []

    for recovery_case_id in case_ids:
        try:
            result = await compensate_late_authorized_recovery(
                session_factory,
                recovery_case_id=(recovery_case_id),
                provider=provider,
                compensated_at=reference_time,
            )

            compensation_results.append(result)

        except asyncio.CancelledError:
            raise

        except RecoveryCompensationProviderFailure as error:
            failures.append(
                RecoveryCompensationBatchFailure(
                    recovery_case_id=(recovery_case_id),
                    error_type=type(error).__name__,
                    retryable=error.retryable,
                ),
            )

        except (
            RecoveryCompensationCaseNotFoundError,
            RecoveryCompensationNotRequiredError,
        ):
            skipped_case_ids.append(
                recovery_case_id,
            )

        except Exception as error:
            failures.append(
                RecoveryCompensationBatchFailure(
                    recovery_case_id=(recovery_case_id),
                    error_type=type(error).__name__,
                    retryable=False,
                ),
            )

    return RecoveryCompensationBatchResult(
        discovered_case_ids=case_ids,
        compensation_results=tuple(
            compensation_results,
        ),
        failures=tuple(failures),
        skipped_case_ids=tuple(
            skipped_case_ids,
        ),
    )
