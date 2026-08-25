from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from app.domain.incidents import IncidentSeverity
from app.domain.payments import PaymentState
from app.domain.recovery import (
    PaymentFailureEvidence,
    RecoveryActionType,
    RecoveryCaseSnapshot,
    RecoveryCaseStatus,
    RecoveryChannel,
    RecoveryPlanDecision,
    RecoveryPlanningContext,
    build_deterministic_recovery_plan,
)

NOW = datetime(2026, 8, 25, 10, 0, tzinfo=UTC)


def create_case() -> RecoveryCaseSnapshot:
    return RecoveryCaseSnapshot(
        case_id=UUID("70000000-0000-0000-0000-000000000001"),
        payment_attempt_id=UUID("70000000-0000-0000-0000-000000000002"),
        provider_payment_id="pay_planner_001",
        payment_state=PaymentState.FAILED,
        amount_minor=250_000,
        currency="INR",
        payment_method="upi",
        status=RecoveryCaseStatus.OPEN,
        recovery_attempt_count=0,
        customer_contact_allowed=True,
    )


def create_context(
    *,
    case: RecoveryCaseSnapshot | None = None,
    channels: tuple[RecoveryChannel, ...] = (RecoveryChannel.EMAIL,),
    alternate_methods: tuple[str, ...] = ("card", "netbanking"),
) -> RecoveryPlanningContext:
    return RecoveryPlanningContext(
        case=case or create_case(),
        failure=PaymentFailureEvidence(
            error_code=" BAD_REQUEST_ERROR ",
            error_source="customer",
            error_step="payment_authentication",
            error_reason="payment_failed",
            failure_count=1,
            first_failed_at=NOW - timedelta(minutes=5),
            last_failed_at=NOW - timedelta(minutes=5),
        ),
        available_channels=channels,
        alternate_payment_methods=alternate_methods,
        planned_at=NOW,
    )


def test_builds_bounded_three_action_recovery_plan() -> None:
    plan = build_deterministic_recovery_plan(create_context())

    assert plan.decision is RecoveryPlanDecision.RECOVER
    assert [proposal.action_type for proposal in plan.proposals] == [
        RecoveryActionType.CREATE_PAYMENT_LINK,
        RecoveryActionType.OFFER_ALTERNATE_METHOD,
        RecoveryActionType.SEND_RECOVERY_MESSAGE,
    ]
    assert plan.proposals[0].amount_minor == 250_000
    assert plan.proposals[0].currency == "INR"
    assert plan.proposals[1].target_payment_method == "card"
    assert plan.proposals[2].channel is RecoveryChannel.EMAIL
    assert len(plan.proposals) == 3


def test_without_contact_consent_only_creates_link() -> None:
    case = replace(create_case(), customer_contact_allowed=False)

    plan = build_deterministic_recovery_plan(create_context(case=case))

    assert plan.decision is RecoveryPlanDecision.RECOVER
    assert len(plan.proposals) == 1
    assert plan.proposals[0].action_type is RecoveryActionType.CREATE_PAYMENT_LINK


def test_active_high_severity_incident_causes_wait() -> None:
    case = replace(
        create_case(),
        active_incident_severity=IncidentSeverity.HIGH,
    )

    plan = build_deterministic_recovery_plan(create_context(case=case))

    assert plan.decision is RecoveryPlanDecision.WAIT
    assert len(plan.proposals) == 1
    assert plan.proposals[0].action_type is RecoveryActionType.WAIT
    assert plan.proposals[0].execute_after == NOW + timedelta(minutes=15)
    assert "incident:high" in plan.evidence_codes


@pytest.mark.parametrize(
    "payment_state",
    [
        PaymentState.AUTHORIZED,
        PaymentState.CAPTURED,
        PaymentState.REFUNDED,
    ],
)
def test_completed_payment_causes_stop(payment_state: PaymentState) -> None:
    case = replace(create_case(), payment_state=payment_state)

    plan = build_deterministic_recovery_plan(create_context(case=case))

    assert plan.decision is RecoveryPlanDecision.STOP
    assert plan.proposals[0].action_type is RecoveryActionType.STOP_RECOVERY


def test_late_authorization_causes_stop() -> None:
    case = replace(
        create_case(),
        late_authorization_detected_at=NOW - timedelta(seconds=1),
    )

    plan = build_deterministic_recovery_plan(create_context(case=case))

    assert plan.decision is RecoveryPlanDecision.STOP


@pytest.mark.parametrize(
    "case",
    [
        replace(create_case(), recovery_attempt_count=3),
        replace(create_case(), amount_minor=1_500_000),
        replace(create_case(), status=RecoveryCaseStatus.ESCALATED),
    ],
)
def test_automation_boundaries_cause_escalation(
    case: RecoveryCaseSnapshot,
) -> None:
    plan = build_deterministic_recovery_plan(create_context(case=case))

    assert plan.decision is RecoveryPlanDecision.ESCALATE
    assert plan.proposals[0].action_type is RecoveryActionType.ESCALATE_HUMAN


def test_existing_link_is_reused_without_duplicate_creation() -> None:
    case = replace(
        create_case(),
        active_payment_link_id="plink_existing",
    )

    plan = build_deterministic_recovery_plan(create_context(case=case))

    assert plan.decision is RecoveryPlanDecision.RECOVER
    assert len(plan.proposals) == 1
    assert plan.proposals[0].action_type is RecoveryActionType.SEND_RECOVERY_MESSAGE
    assert "active_payment_link:true" in plan.evidence_codes


def test_existing_link_without_approved_channel_causes_wait() -> None:
    case = replace(
        create_case(),
        active_payment_link_id="plink_existing",
        customer_contact_allowed=False,
    )

    plan = build_deterministic_recovery_plan(
        create_context(case=case, channels=()),
    )

    assert plan.decision is RecoveryPlanDecision.WAIT
    assert plan.proposals[0].action_type is RecoveryActionType.WAIT


def test_context_normalizes_duplicate_methods_and_channels() -> None:
    context = create_context(
        channels=(RecoveryChannel.EMAIL, RecoveryChannel.EMAIL),
        alternate_methods=(" Card ", "card", " netbanking "),
    )

    assert context.available_channels == (RecoveryChannel.EMAIL,)
    assert context.alternate_payment_methods == ("card", "netbanking")


def test_failure_evidence_requires_ordered_aware_timestamps() -> None:
    with pytest.raises(ValueError, match="earlier"):
        PaymentFailureEvidence(
            error_code=None,
            error_source=None,
            error_step=None,
            error_reason=None,
            failure_count=1,
            first_failed_at=NOW,
            last_failed_at=NOW - timedelta(seconds=1),
        )

    with pytest.raises(ValueError, match="timezone-aware"):
        replace(
            create_context().failure,
            first_failed_at=datetime(2026, 8, 25, 10, 0),
        )
