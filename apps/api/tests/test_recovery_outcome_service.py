from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest

from app.domain.recovery.outcomes import (
    RecoveryOutcomeAttribution,
    RecoveryOutcomeProof,
    RecoveryOutcomeStatus,
)
from app.services import recovery_outcome_service
from app.services.recovery_outcome_service import (
    RecoveryOutcomeConflictError,
    RecoveryOutcomePaymentMismatchError,
    _validate_proof_against_case,
    build_recovery_outcome_fingerprint,
    persist_recovery_outcome_proof,
)

NOW = datetime(2026, 8, 25, 12, 0, tzinfo=UTC)

CASE_ID = UUID("10000000-0000-0000-0000-000000000001")
PAYMENT_ATTEMPT_ID = UUID("20000000-0000-0000-0000-000000000001")
ACTION_ID = UUID("30000000-0000-0000-0000-000000000001")

OUTCOME_ID = UUID("40000000-0000-0000-0000-000000000001")
OBSERVATION_ID = UUID("50000000-0000-0000-0000-000000000001")


def build_proof(
    **changes: object,
) -> RecoveryOutcomeProof:
    values: dict[str, object] = {
        "recovery_case_id": CASE_ID,
        "payment_attempt_id": PAYMENT_ATTEMPT_ID,
        "provider_payment_id": "pay_rr_service_001",
        "status": RecoveryOutcomeStatus.RECOVERED,
        "attribution": RecoveryOutcomeAttribution.DIRECT_PAYMENT_LINK,
        "occurred_at": NOW,
        "original_amount_minor": 45_000,
        "currency": "INR",
        "recovery_action_id": ACTION_ID,
        "payment_link_id": "plink_rr_service_001",
        "provider_outcome_id": "pay_rr_recovered_001",
        "gross_recovered_minor": 45_000,
        "evidence_event_ids": ("evt_rr_payment_link_paid_001",),
    }
    values.update(changes)

    return RecoveryOutcomeProof(**values)


def build_recovery_case() -> SimpleNamespace:
    return SimpleNamespace(
        id=CASE_ID,
        payment_attempt_id=PAYMENT_ATTEMPT_ID,
        amount_minor=45_000,
        currency="INR",
    )


def build_projection(
    *,
    fingerprint: str,
    occurred_at: datetime = NOW,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=OUTCOME_ID,
        outcome_fingerprint=fingerprint,
        occurred_at=occurred_at,
        version=0,
    )


def configure_common_dependencies(
    monkeypatch: pytest.MonkeyPatch,
    *,
    recovery_case: SimpleNamespace | None = None,
) -> None:
    monkeypatch.setattr(
        recovery_outcome_service,
        "_load_recovery_case",
        AsyncMock(
            return_value=recovery_case or build_recovery_case(),
        ),
    )
    monkeypatch.setattr(
        recovery_outcome_service,
        "_validate_recovery_action",
        AsyncMock(),
    )


def test_outcome_fingerprint_is_stable_across_evidence_order() -> None:
    first = build_proof(
        evidence_event_ids=(
            "evt_rr_payment_link_paid_001",
            "evt_rr_webhook_001",
        ),
    )
    second = build_proof(
        evidence_event_ids=(
            "evt_rr_webhook_001",
            "evt_rr_payment_link_paid_001",
        ),
    )

    assert build_recovery_outcome_fingerprint(first) == build_recovery_outcome_fingerprint(second)


def test_outcome_fingerprint_changes_when_financial_evidence_changes() -> None:
    original = build_proof()
    changed = build_proof(
        provider_outcome_id="pay_rr_recovered_002",
    )

    assert build_recovery_outcome_fingerprint(original) != build_recovery_outcome_fingerprint(
        changed
    )


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        (
            {
                "payment_attempt_id": UUID("20000000-0000-0000-0000-000000000099"),
            },
            "payment attempt",
        ),
        (
            {"original_amount_minor": 45_001},
            "amount",
        ),
        (
            {"currency": "USD"},
            "currency",
        ),
    ],
)
def test_proof_must_match_recovery_case(
    changes: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(
        RecoveryOutcomePaymentMismatchError,
        match=message,
    ):
        _validate_proof_against_case(
            build_proof(**changes),
            build_recovery_case(),
        )


@pytest.mark.asyncio
async def test_persist_creates_projection_and_first_observation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    proof = build_proof()
    fingerprint = build_recovery_outcome_fingerprint(proof)
    projection = build_projection(
        fingerprint=fingerprint,
    )
    observation = SimpleNamespace(
        id=OBSERVATION_ID,
    )
    session = MagicMock()
    session.flush = AsyncMock()

    configure_common_dependencies(monkeypatch)

    monkeypatch.setattr(
        recovery_outcome_service,
        "_load_projection",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(
        recovery_outcome_service,
        "_new_projection",
        MagicMock(return_value=projection),
    )
    monkeypatch.setattr(
        recovery_outcome_service,
        "_load_observation",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(
        recovery_outcome_service,
        "_new_observation",
        MagicMock(return_value=observation),
    )

    result = await persist_recovery_outcome_proof(
        session,
        proof=proof,
    )

    assert result.recovery_outcome_id == OUTCOME_ID
    assert result.recovery_outcome_observation_id == OBSERVATION_ID
    assert result.projection_created is True
    assert result.projection_updated is True
    assert result.observation_created is True

    assert session.add.call_count == 2
    assert session.flush.await_count == 2


@pytest.mark.asyncio
async def test_identical_replay_does_not_create_duplicate_observation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    proof = build_proof()
    fingerprint = build_recovery_outcome_fingerprint(proof)
    projection = build_projection(
        fingerprint=fingerprint,
    )
    observation = SimpleNamespace(
        id=OBSERVATION_ID,
    )
    session = MagicMock()
    session.flush = AsyncMock()

    configure_common_dependencies(monkeypatch)

    monkeypatch.setattr(
        recovery_outcome_service,
        "_load_projection",
        AsyncMock(return_value=projection),
    )
    monkeypatch.setattr(
        recovery_outcome_service,
        "_load_observation",
        AsyncMock(return_value=observation),
    )

    result = await persist_recovery_outcome_proof(
        session,
        proof=proof,
    )

    assert result.recovery_outcome_id == OUTCOME_ID
    assert result.recovery_outcome_observation_id == OBSERVATION_ID
    assert result.projection_created is False
    assert result.projection_updated is False
    assert result.observation_created is False

    session.add.assert_not_called()
    session.flush.assert_not_awaited()


@pytest.mark.asyncio
async def test_newer_proof_updates_projection_and_adds_observation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    proof = build_proof(
        occurred_at=NOW + timedelta(minutes=1),
    )
    old_proof = build_proof()
    old_fingerprint = build_recovery_outcome_fingerprint(
        old_proof,
    )
    projection = build_projection(
        fingerprint=old_fingerprint,
        occurred_at=NOW,
    )
    observation = SimpleNamespace(
        id=OBSERVATION_ID,
    )
    session = MagicMock()
    session.flush = AsyncMock()

    configure_common_dependencies(monkeypatch)

    monkeypatch.setattr(
        recovery_outcome_service,
        "_load_projection",
        AsyncMock(return_value=projection),
    )
    apply_proof = MagicMock()
    monkeypatch.setattr(
        recovery_outcome_service,
        "_apply_proof_to_projection",
        apply_proof,
    )
    monkeypatch.setattr(
        recovery_outcome_service,
        "_load_observation",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(
        recovery_outcome_service,
        "_new_observation",
        MagicMock(return_value=observation),
    )

    result = await persist_recovery_outcome_proof(
        session,
        proof=proof,
    )

    assert result.projection_created is False
    assert result.projection_updated is True
    assert result.observation_created is True

    apply_proof.assert_called_once()
    assert projection.version == 1
    session.add.assert_called_once_with(observation)
    session.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_out_of_order_proof_is_audited_without_regressing_projection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    proof = build_proof(
        occurred_at=NOW,
    )
    newer_proof = build_proof(
        occurred_at=NOW + timedelta(minutes=1),
    )
    projection = build_projection(
        fingerprint=build_recovery_outcome_fingerprint(
            newer_proof,
        ),
        occurred_at=NOW + timedelta(minutes=1),
    )
    observation = SimpleNamespace(
        id=OBSERVATION_ID,
    )
    session = MagicMock()
    session.flush = AsyncMock()

    configure_common_dependencies(monkeypatch)

    monkeypatch.setattr(
        recovery_outcome_service,
        "_load_projection",
        AsyncMock(return_value=projection),
    )
    apply_proof = MagicMock()
    monkeypatch.setattr(
        recovery_outcome_service,
        "_apply_proof_to_projection",
        apply_proof,
    )
    monkeypatch.setattr(
        recovery_outcome_service,
        "_load_observation",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(
        recovery_outcome_service,
        "_new_observation",
        MagicMock(return_value=observation),
    )

    result = await persist_recovery_outcome_proof(
        session,
        proof=proof,
    )

    assert result.projection_updated is False
    assert result.observation_created is True
    assert projection.version == 0

    apply_proof.assert_not_called()
    session.add.assert_called_once_with(observation)
    session.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_conflicting_same_time_proof_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    proof = build_proof(
        provider_outcome_id="pay_rr_recovered_002",
    )
    different_proof = build_proof()
    projection = build_projection(
        fingerprint=build_recovery_outcome_fingerprint(
            different_proof,
        ),
        occurred_at=NOW,
    )
    session = MagicMock()
    session.flush = AsyncMock()

    configure_common_dependencies(monkeypatch)

    monkeypatch.setattr(
        recovery_outcome_service,
        "_load_projection",
        AsyncMock(return_value=projection),
    )

    with pytest.raises(
        RecoveryOutcomeConflictError,
        match="same timestamp",
    ):
        await persist_recovery_outcome_proof(
            session,
            proof=proof,
        )

    session.add.assert_not_called()
    session.flush.assert_not_awaited()


@pytest.mark.asyncio
async def test_recovery_action_validation_receives_case_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    proof = build_proof()
    fingerprint = build_recovery_outcome_fingerprint(proof)
    projection = build_projection(
        fingerprint=fingerprint,
    )
    observation = SimpleNamespace(
        id=OBSERVATION_ID,
    )
    session = MagicMock()
    session.flush = AsyncMock()

    configure_common_dependencies(monkeypatch)

    validate_action = recovery_outcome_service._validate_recovery_action

    monkeypatch.setattr(
        recovery_outcome_service,
        "_load_projection",
        AsyncMock(return_value=projection),
    )
    monkeypatch.setattr(
        recovery_outcome_service,
        "_load_observation",
        AsyncMock(return_value=observation),
    )

    await persist_recovery_outcome_proof(
        session,
        proof=proof,
    )

    validate_action.assert_awaited_once_with(
        session,
        recovery_action_id=ACTION_ID,
        recovery_case_id=CASE_ID,
    )
