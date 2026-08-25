import asyncio
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
)

from app.db.models.recovery import (
    RecoveryAction,
    RecoveryActionStatus,
)
from app.db.models.recovery_outcome import (
    RecoveryOutcome,
)
from app.db.models.recovery_outcome import (
    RecoveryOutcomeStatus as RecoveryOutcomeModelStatus,
)
from app.domain.recovery import RecoveryActionType
from app.domain.recovery.outcomes import RecoveryOutcomeStatus
from app.integrations.razorpay.payment_links import (
    RazorpayPaymentLinkProvider,
)
from app.services.recovery_outcome_reconciler import (
    RecoveryOutcomeReconciliationActionNotFoundError,
    RecoveryOutcomeReconciliationCaseNotFoundError,
    RecoveryOutcomeReconciliationNotReadyError,
    RecoveryOutcomeReconciliationProviderFailure,
    RecoveryOutcomeReconciliationResult,
    reconcile_recovery_payment_link_outcome,
)

SessionFactory = async_sessionmaker[AsyncSession]

RECONCILABLE_OUTCOME_STATUSES = frozenset(
    {
        RecoveryOutcomeModelStatus.PAYMENT_LINK_PENDING.value,
        RecoveryOutcomeModelStatus.UNRESOLVED.value,
    },
)


@dataclass(frozen=True, slots=True)
class RecoveryOutcomeBatchFailure:
    recovery_action_id: UUID
    error_type: str
    retryable: bool


@dataclass(frozen=True, slots=True)
class RecoveryOutcomeBatchResult:
    discovered_action_ids: tuple[UUID, ...]
    reconciliation_results: tuple[
        RecoveryOutcomeReconciliationResult,
        ...,
    ]
    failures: tuple[RecoveryOutcomeBatchFailure, ...]
    skipped_action_ids: tuple[UUID, ...]

    @property
    def discovered(self) -> int:
        return len(self.discovered_action_ids)

    @property
    def reconciled(self) -> int:
        return sum(result.observation_created for result in self.reconciliation_results)

    @property
    def already_current(self) -> int:
        return sum(not result.observation_created for result in self.reconciliation_results)

    @property
    def recovered(self) -> int:
        return sum(
            result.outcome_status is RecoveryOutcomeStatus.RECOVERED and result.observation_created
            for result in self.reconciliation_results
        )

    @property
    def duplicate_collection_prevented(self) -> int:
        return sum(
            (result.outcome_status is RecoveryOutcomeStatus.DUPLICATE_COLLECTION_PREVENTED)
            and result.observation_created
            for result in self.reconciliation_results
        )

    @property
    def retryable_failures(self) -> int:
        return sum(failure.retryable for failure in self.failures)

    @property
    def permanent_failures(self) -> int:
        return sum(not failure.retryable for failure in self.failures)

    @property
    def skipped(self) -> int:
        return len(self.skipped_action_ids)


def _require_timezone_aware(
    value: datetime,
) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(
            "Recovery outcome batch time must be timezone-aware",
        )


async def discover_reconcilable_recovery_action_ids(
    session: AsyncSession,
    *,
    reference_time: datetime,
    batch_size: int,
) -> tuple[UUID, ...]:
    """
    Find successful Payment Link actions that have no outcome yet or whose
    current outcome is still pending/unresolved.

    Terminal outcomes are deliberately excluded so the worker does not keep
    polling paid, expired, cancelled, or duplicate-prevented links.
    """
    _require_timezone_aware(reference_time)

    if not 1 <= batch_size <= 100:
        raise ValueError(
            "Recovery outcome batch size must be between 1 and 100",
        )

    result = await session.execute(
        select(RecoveryAction.id)
        .outerjoin(
            RecoveryOutcome,
            RecoveryOutcome.recovery_action_id == RecoveryAction.id,
        )
        .where(
            RecoveryAction.action_type == RecoveryActionType.CREATE_PAYMENT_LINK.value,
            RecoveryAction.status == RecoveryActionStatus.SUCCEEDED.value,
            RecoveryAction.provider_action_id.is_not(None),
            or_(
                RecoveryOutcome.id.is_(None),
                RecoveryOutcome.status.in_(
                    RECONCILABLE_OUTCOME_STATUSES,
                ),
            ),
        )
        .order_by(
            RecoveryAction.completed_at.asc().nulls_first(),
            RecoveryAction.id,
        )
        .limit(batch_size),
    )

    return tuple(result.scalars().all())


async def run_recovery_outcome_batch(
    session_factory: SessionFactory,
    *,
    provider: RazorpayPaymentLinkProvider,
    reference_time: datetime,
    batch_size: int = 25,
) -> RecoveryOutcomeBatchResult:
    """
    Reconcile a small provider-evidence batch without double-counting money.

    Each individual reconciliation owns its short database transactions; no
    database lock is held while waiting for Razorpay.
    """
    _require_timezone_aware(reference_time)

    async with session_factory() as discovery_session:
        action_ids = await discover_reconcilable_recovery_action_ids(
            discovery_session,
            reference_time=reference_time,
            batch_size=batch_size,
        )

    reconciliation_results: list[RecoveryOutcomeReconciliationResult] = []
    failures: list[RecoveryOutcomeBatchFailure] = []
    skipped_action_ids: list[UUID] = []

    for action_id in action_ids:
        try:
            result = await reconcile_recovery_payment_link_outcome(
                session_factory,
                recovery_case_id=await _load_recovery_case_id(
                    session_factory,
                    recovery_action_id=action_id,
                ),
                recovery_action_id=action_id,
                provider=provider,
                reconciled_at=reference_time,
            )
            reconciliation_results.append(result)
        except asyncio.CancelledError:
            raise
        except RecoveryOutcomeReconciliationProviderFailure as error:
            failures.append(
                RecoveryOutcomeBatchFailure(
                    recovery_action_id=action_id,
                    error_type=type(error).__name__,
                    retryable=error.retryable,
                ),
            )
        except (
            RecoveryOutcomeReconciliationActionNotFoundError,
            RecoveryOutcomeReconciliationCaseNotFoundError,
            RecoveryOutcomeReconciliationNotReadyError,
        ):
            skipped_action_ids.append(action_id)
        except Exception as error:
            failures.append(
                RecoveryOutcomeBatchFailure(
                    recovery_action_id=action_id,
                    error_type=type(error).__name__,
                    retryable=False,
                ),
            )

    return RecoveryOutcomeBatchResult(
        discovered_action_ids=action_ids,
        reconciliation_results=tuple(reconciliation_results),
        failures=tuple(failures),
        skipped_action_ids=tuple(skipped_action_ids),
    )


async def _load_recovery_case_id(
    session_factory: SessionFactory,
    *,
    recovery_action_id: UUID,
) -> UUID:
    async with session_factory() as session:
        result = await session.execute(
            select(RecoveryAction.recovery_case_id).where(
                RecoveryAction.id == recovery_action_id,
            ),
        )
        recovery_case_id = result.scalar_one_or_none()

    if recovery_case_id is None:
        raise RecoveryOutcomeReconciliationActionNotFoundError(
            f"Recovery action {recovery_action_id} does not exist",
        )

    return recovery_case_id
