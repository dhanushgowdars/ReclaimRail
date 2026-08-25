from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.recovery.outcomes import (
    RecoveryOutcomeAttribution,
    RecoveryOutcomeStatus,
)
from app.services import recovery_outcome_batch
from app.services.recovery_outcome_batch import (
    RecoveryOutcomeBatchFailure,
    RecoveryOutcomeBatchResult,
    discover_reconcilable_recovery_action_ids,
    run_recovery_outcome_batch,
)
from app.services.recovery_outcome_reconciler import (
    RecoveryOutcomeReconciliationProviderFailure,
    RecoveryOutcomeReconciliationResult,
)

REFERENCE_TIME = datetime(
    2026,
    8,
    25,
    18,
    30,
    tzinfo=UTC,
)

ACTION_ID_ONE = "10000000-0000-0000-0000-000000000001"
ACTION_ID_TWO = "10000000-0000-0000-0000-000000000002"
CASE_ID_ONE = "20000000-0000-0000-0000-000000000001"
CASE_ID_TWO = "20000000-0000-0000-0000-000000000002"
OUTCOME_ID_ONE = "30000000-0000-0000-0000-000000000001"
OUTCOME_ID_TWO = "30000000-0000-0000-0000-000000000002"


class SessionContext:
    async def __aenter__(self) -> AsyncSession:
        return AsyncMock(spec=AsyncSession)

    async def __aexit__(
        self,
        exc_type: object,
        exc_value: object,
        traceback: object,
    ) -> bool:
        return False


class SessionFactory:
    def __call__(self) -> SessionContext:
        return SessionContext()


def build_result(
    *,
    action_id: str,
    case_id: str,
    outcome_id: str,
    status: RecoveryOutcomeStatus,
    attribution: RecoveryOutcomeAttribution,
    observation_created: bool,
) -> RecoveryOutcomeReconciliationResult:
    from uuid import UUID

    return RecoveryOutcomeReconciliationResult(
        recovery_case_id=UUID(case_id),
        recovery_action_id=UUID(action_id),
        payment_link_id=f"plink_{action_id[-4:]}",
        outcome_status=status,
        attribution=attribution,
        provider_status=("paid" if status is RecoveryOutcomeStatus.RECOVERED else "cancelled"),
        recovery_outcome_id=UUID(outcome_id),
        recovery_outcome_observation_id=UUID(outcome_id),
        projection_created=observation_created,
        projection_updated=observation_created,
        observation_created=observation_created,
        case_marked_recovered=(status is RecoveryOutcomeStatus.RECOVERED and observation_created),
    )


@pytest.mark.asyncio
async def test_rejects_naive_batch_time_before_database_access() -> None:
    session = AsyncMock(spec=AsyncSession)

    with pytest.raises(
        ValueError,
        match="timezone-aware",
    ):
        await discover_reconcilable_recovery_action_ids(
            session,
            reference_time=datetime(2026, 8, 25, 18, 30),
            batch_size=25,
        )

    session.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_discovers_reconcilable_action_ids_in_query_order() -> None:
    from uuid import UUID

    action_id_one = UUID(ACTION_ID_ONE)
    action_id_two = UUID(ACTION_ID_TWO)

    query_result = MagicMock()
    query_result.scalars.return_value.all.return_value = [
        action_id_one,
        action_id_two,
    ]

    session = AsyncMock(spec=AsyncSession)
    session.execute.return_value = query_result

    action_ids = await discover_reconcilable_recovery_action_ids(
        session,
        reference_time=REFERENCE_TIME,
        batch_size=25,
    )

    assert action_ids == (
        action_id_one,
        action_id_two,
    )
    session.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_batch_reconciles_verified_revenue_and_duplicate_prevention(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from uuid import UUID

    action_id_one = UUID(ACTION_ID_ONE)
    action_id_two = UUID(ACTION_ID_TWO)
    case_id_one = UUID(CASE_ID_ONE)
    case_id_two = UUID(CASE_ID_TWO)

    monkeypatch.setattr(
        recovery_outcome_batch,
        "discover_reconcilable_recovery_action_ids",
        AsyncMock(
            return_value=(
                action_id_one,
                action_id_two,
            ),
        ),
    )
    monkeypatch.setattr(
        recovery_outcome_batch,
        "_load_recovery_case_id",
        AsyncMock(
            side_effect=(
                case_id_one,
                case_id_two,
            ),
        ),
    )
    monkeypatch.setattr(
        recovery_outcome_batch,
        "reconcile_recovery_payment_link_outcome",
        AsyncMock(
            side_effect=(
                build_result(
                    action_id=ACTION_ID_ONE,
                    case_id=CASE_ID_ONE,
                    outcome_id=OUTCOME_ID_ONE,
                    status=RecoveryOutcomeStatus.RECOVERED,
                    attribution=(RecoveryOutcomeAttribution.DIRECT_PAYMENT_LINK),
                    observation_created=True,
                ),
                build_result(
                    action_id=ACTION_ID_TWO,
                    case_id=CASE_ID_TWO,
                    outcome_id=OUTCOME_ID_TWO,
                    status=(RecoveryOutcomeStatus.DUPLICATE_COLLECTION_PREVENTED),
                    attribution=(RecoveryOutcomeAttribution.LATE_AUTHORIZATION_SAFETY),
                    observation_created=True,
                ),
            ),
        ),
    )

    result = await run_recovery_outcome_batch(
        SessionFactory(),
        provider=MagicMock(),
        reference_time=REFERENCE_TIME,
    )

    assert result.discovered == 2
    assert result.reconciled == 2
    assert result.already_current == 0
    assert result.recovered == 1
    assert result.duplicate_collection_prevented == 1
    assert result.retryable_failures == 0
    assert result.permanent_failures == 0
    assert result.skipped == 0


@pytest.mark.asyncio
async def test_batch_classifies_retryable_provider_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from uuid import UUID

    action_id = UUID(ACTION_ID_ONE)
    case_id = UUID(CASE_ID_ONE)

    monkeypatch.setattr(
        recovery_outcome_batch,
        "discover_reconcilable_recovery_action_ids",
        AsyncMock(return_value=(action_id,)),
    )
    monkeypatch.setattr(
        recovery_outcome_batch,
        "_load_recovery_case_id",
        AsyncMock(return_value=case_id),
    )
    monkeypatch.setattr(
        recovery_outcome_batch,
        "reconcile_recovery_payment_link_outcome",
        AsyncMock(
            side_effect=RecoveryOutcomeReconciliationProviderFailure(
                "Razorpay temporarily unavailable",
                retryable=True,
                status_code=503,
            ),
        ),
    )

    result = await run_recovery_outcome_batch(
        SessionFactory(),
        provider=MagicMock(),
        reference_time=REFERENCE_TIME,
    )

    assert result.discovered == 1
    assert result.reconciled == 0
    assert result.retryable_failures == 1
    assert result.permanent_failures == 0
    assert result.failures == (
        RecoveryOutcomeBatchFailure(
            recovery_action_id=action_id,
            error_type="RecoveryOutcomeReconciliationProviderFailure",
            retryable=True,
        ),
    )


def test_batch_result_counts_replayed_evidence_as_already_current() -> None:
    result = RecoveryOutcomeBatchResult(
        discovered_action_ids=(),
        reconciliation_results=(
            build_result(
                action_id=ACTION_ID_ONE,
                case_id=CASE_ID_ONE,
                outcome_id=OUTCOME_ID_ONE,
                status=RecoveryOutcomeStatus.RECOVERED,
                attribution=RecoveryOutcomeAttribution.DIRECT_PAYMENT_LINK,
                observation_created=False,
            ),
        ),
        failures=(),
        skipped_action_ids=(),
    )

    assert result.reconciled == 0
    assert result.already_current == 1
    assert result.recovered == 0
