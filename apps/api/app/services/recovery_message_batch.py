from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import or_, select

from app.db.models.recovery import (
    RecoveryAction,
    RecoveryActionStatus,
    RecoveryCase,
)
from app.domain.recovery import (
    RecoveryActionType,
    RecoveryCaseStatus,
)
from app.integrations.razorpay.payment_customers import (
    RazorpayPaymentCustomerProvider,
)
from app.integrations.razorpay.payment_link_notifications import (
    RazorpayPaymentLinkNotificationProvider,
)
from app.services.recovery_action_executor import (
    DEFAULT_ACTION_CLAIM_TIMEOUT,
    DEFAULT_MAXIMUM_EXECUTION_ATTEMPTS,
    RecoveryActionExecutionDisposition,
    RecoveryActionNotDueError,
    RecoveryActionNotExecutableError,
)
from app.services.recovery_message_executor import (
    RecoveryMessageProviderFailure,
    SessionFactory,
    execute_recovery_message_action,
)


@dataclass(frozen=True, slots=True)
class RecoveryMessageBatchFailure:
    action_id: UUID
    error_type: str
    retryable: bool


@dataclass(frozen=True, slots=True)
class RecoveryMessageBatchResult:
    discovered: int
    succeeded: int
    already_succeeded: int
    policy_denied: int
    retryable_failures: int
    permanent_failures: int
    skipped: int
    failures: tuple[RecoveryMessageBatchFailure, ...] = ()


async def discover_recovery_message_action_ids(
    session_factory: SessionFactory,
    *,
    reference_time: datetime,
    batch_size: int,
) -> tuple[UUID, ...]:
    if reference_time.tzinfo is None or reference_time.utcoffset() is None:
        raise ValueError("Message batch reference time must be timezone-aware")

    if batch_size < 1:
        raise ValueError("Message batch size must be positive")

    async with session_factory() as session:
        result = await session.execute(
            select(RecoveryAction.id)
            .join(
                RecoveryCase,
                RecoveryCase.id == RecoveryAction.recovery_case_id,
            )
            .where(
                RecoveryAction.action_type == RecoveryActionType.SEND_RECOVERY_MESSAGE.value,
                RecoveryAction.status.in_(
                    (
                        RecoveryActionStatus.ALLOWED.value,
                        RecoveryActionStatus.SCHEDULED.value,
                        RecoveryActionStatus.FAILED.value,
                    ),
                ),
                RecoveryCase.status == RecoveryCaseStatus.READY.value,
                RecoveryCase.active_payment_link_id.is_not(None),
                or_(
                    RecoveryAction.status != RecoveryActionStatus.SCHEDULED.value,
                    RecoveryAction.execute_after.is_(None),
                    RecoveryAction.execute_after <= reference_time,
                ),
            )
            .order_by(
                RecoveryAction.execute_after,
                RecoveryAction.created_at,
                RecoveryAction.id,
            )
            .limit(batch_size),
        )

        return tuple(result.scalars().all())


async def run_recovery_message_batch(
    session_factory: SessionFactory,
    *,
    customer_provider: RazorpayPaymentCustomerProvider,
    notification_provider: RazorpayPaymentLinkNotificationProvider,
    reference_time: datetime,
    batch_size: int,
    claim_timeout: timedelta = DEFAULT_ACTION_CLAIM_TIMEOUT,
    maximum_attempts: int = DEFAULT_MAXIMUM_EXECUTION_ATTEMPTS,
) -> RecoveryMessageBatchResult:
    action_ids = await discover_recovery_message_action_ids(
        session_factory,
        reference_time=reference_time,
        batch_size=batch_size,
    )

    succeeded = 0
    already_succeeded = 0
    policy_denied = 0
    retryable_failures = 0
    permanent_failures = 0
    skipped = 0
    failures: list[RecoveryMessageBatchFailure] = []

    for action_id in action_ids:
        try:
            result = await execute_recovery_message_action(
                session_factory,
                action_id=action_id,
                customer_provider=customer_provider,
                notification_provider=notification_provider,
                executed_at=reference_time,
                claim_timeout=claim_timeout,
                maximum_attempts=maximum_attempts,
            )
        except RecoveryMessageProviderFailure as error:
            failures.append(
                RecoveryMessageBatchFailure(
                    action_id=action_id,
                    error_type=type(error).__name__,
                    retryable=error.retryable,
                ),
            )

            if error.retryable:
                retryable_failures += 1
            else:
                permanent_failures += 1

            continue
        except (
            RecoveryActionNotDueError,
            RecoveryActionNotExecutableError,
        ):
            skipped += 1
            continue

        if result.disposition is RecoveryActionExecutionDisposition.SUCCEEDED:
            succeeded += 1
        elif result.disposition is RecoveryActionExecutionDisposition.ALREADY_SUCCEEDED:
            already_succeeded += 1
        else:
            policy_denied += 1

    return RecoveryMessageBatchResult(
        discovered=len(action_ids),
        succeeded=succeeded,
        already_succeeded=already_succeeded,
        policy_denied=policy_denied,
        retryable_failures=retryable_failures,
        permanent_failures=permanent_failures,
        skipped=skipped,
        failures=tuple(failures),
    )
