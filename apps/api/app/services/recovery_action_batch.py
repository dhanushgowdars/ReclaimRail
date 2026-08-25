import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
)

from app.db.models.recovery import (
    RecoveryAction,
    RecoveryActionStatus,
)
from app.domain.recovery import RecoveryActionType
from app.integrations.razorpay.payment_links import (
    RazorpayPaymentLinkProvider,
)
from app.services.recovery_action_executor import (
    DEFAULT_ACTION_CLAIM_TIMEOUT,
    DEFAULT_MAXIMUM_EXECUTION_ATTEMPTS,
    RecoveryActionExecutionDisposition,
    RecoveryActionExecutionResult,
    RecoveryActionInProgressError,
    RecoveryActionNotDueError,
    RecoveryActionNotExecutableError,
    RecoveryActionProviderFailure,
    execute_recovery_payment_link_action,
)

SessionFactory = async_sessionmaker[AsyncSession]


@dataclass(frozen=True, slots=True)
class RecoveryActionBatchFailure:
    action_id: UUID
    error_type: str
    retryable: bool


@dataclass(frozen=True, slots=True)
class RecoveryActionBatchResult:
    discovered_action_ids: tuple[UUID, ...]
    execution_results: tuple[
        RecoveryActionExecutionResult,
        ...,
    ]
    failures: tuple[
        RecoveryActionBatchFailure,
        ...,
    ]
    skipped_action_ids: tuple[UUID, ...]

    @property
    def discovered(self) -> int:
        return len(
            self.discovered_action_ids,
        )

    @property
    def succeeded(self) -> int:
        return sum(
            result.disposition is RecoveryActionExecutionDisposition.SUCCEEDED
            for result in self.execution_results
        )

    @property
    def already_succeeded(self) -> int:
        return sum(
            result.disposition is RecoveryActionExecutionDisposition.ALREADY_SUCCEEDED
            for result in self.execution_results
        )

    @property
    def policy_denied(self) -> int:
        denied = {
            RecoveryActionExecutionDisposition.POLICY_BLOCKED,
            RecoveryActionExecutionDisposition.POLICY_ESCALATED,
            RecoveryActionExecutionDisposition.POLICY_STOPPED,
        }

        return sum(result.disposition in denied for result in self.execution_results)

    @property
    def retryable_failures(self) -> int:
        return sum(failure.retryable for failure in self.failures)

    @property
    def permanent_failures(self) -> int:
        return sum(not failure.retryable for failure in self.failures)

    @property
    def skipped(self) -> int:
        return len(
            self.skipped_action_ids,
        )


def _require_timezone_aware(
    value: datetime,
) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(
            "Recovery action batch time must be timezone-aware",
        )


async def discover_executable_recovery_action_ids(
    session: AsyncSession,
    *,
    reference_time: datetime,
    batch_size: int,
    claim_timeout: timedelta = (DEFAULT_ACTION_CLAIM_TIMEOUT),
    maximum_attempts: int = (DEFAULT_MAXIMUM_EXECUTION_ATTEMPTS),
) -> tuple[UUID, ...]:
    _require_timezone_aware(
        reference_time,
    )

    if not 1 <= batch_size <= 100:
        raise ValueError(
            "Recovery action batch size must be between 1 and 100",
        )

    if claim_timeout <= timedelta(0):
        raise ValueError(
            "Recovery action claim timeout must be positive",
        )

    if maximum_attempts < 1:
        raise ValueError(
            "Maximum execution attempts must be positive",
        )

    stale_before = reference_time - claim_timeout

    result = await session.execute(
        select(RecoveryAction.id)
        .where(
            RecoveryAction.action_type == RecoveryActionType.CREATE_PAYMENT_LINK.value,
            RecoveryAction.execution_attempt_count < maximum_attempts,
            or_(
                RecoveryAction.status == RecoveryActionStatus.ALLOWED.value,
                and_(
                    RecoveryAction.status == RecoveryActionStatus.SCHEDULED.value,
                    RecoveryAction.execute_after.is_not(None),
                    RecoveryAction.execute_after <= reference_time,
                ),
                RecoveryAction.status == RecoveryActionStatus.FAILED.value,
                and_(
                    RecoveryAction.status == RecoveryActionStatus.EXECUTING.value,
                    or_(
                        RecoveryAction.started_at.is_(None),
                        RecoveryAction.started_at <= stale_before,
                    ),
                ),
            ),
        )
        .order_by(
            RecoveryAction.execute_after.asc().nulls_first(),
            RecoveryAction.created_at,
            RecoveryAction.id,
        )
        .limit(batch_size),
    )

    return tuple(
        result.scalars().all(),
    )


async def run_recovery_action_batch(
    session_factory: SessionFactory,
    *,
    provider: RazorpayPaymentLinkProvider,
    reference_time: datetime,
    batch_size: int = 25,
    claim_timeout: timedelta = (DEFAULT_ACTION_CLAIM_TIMEOUT),
    maximum_attempts: int = (DEFAULT_MAXIMUM_EXECUTION_ATTEMPTS),
) -> RecoveryActionBatchResult:
    _require_timezone_aware(
        reference_time,
    )

    async with session_factory() as discovery_session:
        action_ids = await discover_executable_recovery_action_ids(
            discovery_session,
            reference_time=reference_time,
            batch_size=batch_size,
            claim_timeout=claim_timeout,
            maximum_attempts=maximum_attempts,
        )

    execution_results: list[RecoveryActionExecutionResult] = []

    failures: list[RecoveryActionBatchFailure] = []

    skipped_action_ids: list[UUID] = []

    for action_id in action_ids:
        try:
            result = await execute_recovery_payment_link_action(
                session_factory,
                action_id=action_id,
                provider=provider,
                executed_at=reference_time,
                claim_timeout=claim_timeout,
                maximum_attempts=maximum_attempts,
            )

            execution_results.append(
                result,
            )
        except asyncio.CancelledError:
            raise
        except RecoveryActionProviderFailure as error:
            failures.append(
                RecoveryActionBatchFailure(
                    action_id=action_id,
                    error_type=type(error).__name__,
                    retryable=error.retryable,
                ),
            )
        except (
            RecoveryActionInProgressError,
            RecoveryActionNotDueError,
            RecoveryActionNotExecutableError,
        ):
            skipped_action_ids.append(
                action_id,
            )
        except Exception as error:
            failures.append(
                RecoveryActionBatchFailure(
                    action_id=action_id,
                    error_type=type(error).__name__,
                    retryable=False,
                ),
            )

    return RecoveryActionBatchResult(
        discovered_action_ids=action_ids,
        execution_results=tuple(
            execution_results,
        ),
        failures=tuple(
            failures,
        ),
        skipped_action_ids=tuple(
            skipped_action_ids,
        ),
    )
