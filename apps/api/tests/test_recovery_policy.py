from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from app.domain.incidents import IncidentSeverity
from app.domain.payments import PaymentState
from app.domain.recovery import (
    RecoveryActionProposal,
    RecoveryActionType,
    RecoveryCaseSnapshot,
    RecoveryCaseStatus,
    RecoveryChannel,
    RecoveryGuardrail,
    RecoveryPolicy,
    RecoveryPolicyOutcome,
    build_recovery_policy_checks,
    evaluate_recovery_proposal,
)

NOW = datetime(
    2026,
    8,
    25,
    10,
    0,
    tzinfo=UTC,
)


def create_case() -> RecoveryCaseSnapshot:
    return RecoveryCaseSnapshot(
        case_id=UUID(
            "70000000-0000-0000-0000-000000000001",
        ),
        payment_attempt_id=UUID(
            "70000000-0000-0000-0000-000000000002",
        ),
        provider_payment_id="pay_recovery_001",
        payment_state=PaymentState.FAILED,
        amount_minor=250_000,
        currency="INR",
        payment_method="upi",
        status=RecoveryCaseStatus.OPEN,
        recovery_attempt_count=0,
        customer_contact_allowed=True,
    )


def create_payment_link_proposal(
    *,
    amount_minor: int = 250_000,
    currency: str = "INR",
) -> RecoveryActionProposal:
    return RecoveryActionProposal(
        action_type=RecoveryActionType.CREATE_PAYMENT_LINK,
        reason="Create a bounded recovery link",
        amount_minor=amount_minor,
        currency=currency,
    )


def create_message_proposal() -> RecoveryActionProposal:
    return RecoveryActionProposal(
        action_type=RecoveryActionType.SEND_RECOVERY_MESSAGE,
        reason="Notify the customer once",
        channel=RecoveryChannel.EMAIL,
    )


def test_allows_safe_payment_link_proposal() -> None:
    decision = evaluate_recovery_proposal(
        create_case(),
        create_payment_link_proposal(),
        evaluated_at=NOW,
    )

    assert decision.outcome is RecoveryPolicyOutcome.ALLOW
    assert decision.guardrails == ()
    assert "passed" in decision.explanation


def test_persists_the_evidence_for_every_safe_payment_link_check() -> None:
    checks = build_recovery_policy_checks(
        create_case(),
        create_payment_link_proposal(),
        evaluated_at=NOW,
    )

    check_by_code = {check.code: check for check in checks}

    assert check_by_code["amount_matches_original"].result == "passed"
    assert check_by_code["amount_matches_original"].actual_value == (
        "Proposed 250000; original 250000"
    )
    assert check_by_code["customer_contact_consent"].result == "not_applicable"
    assert check_by_code["incident_circuit_breaker"].rule == (
        "High or critical rail incidents block automated recovery"
    )


def test_policy_checks_show_the_exact_active_quiet_period() -> None:
    checks = build_recovery_policy_checks(
        replace(
            create_case(),
            last_customer_contact_at=NOW - timedelta(hours=1),
        ),
        create_message_proposal(),
        evaluated_at=NOW,
    )

    check_by_code = {check.code: check for check in checks}

    assert check_by_code["customer_quiet_period"].result == "failed"
    assert "Active until" in check_by_code["customer_quiet_period"].actual_value


@pytest.mark.parametrize(
    "payment_state",
    [
        PaymentState.AUTHORIZED,
        PaymentState.CAPTURED,
        PaymentState.REFUNDED,
    ],
)
def test_stops_when_payment_is_already_complete(
    payment_state: PaymentState,
) -> None:
    case = replace(
        create_case(),
        payment_state=payment_state,
    )

    decision = evaluate_recovery_proposal(
        case,
        create_payment_link_proposal(),
        evaluated_at=NOW,
    )

    assert decision.outcome is RecoveryPolicyOutcome.STOP
    assert RecoveryGuardrail.PAYMENT_ALREADY_COMPLETED in (decision.guardrails)


def test_late_authorization_evidence_stops_recovery() -> None:
    case = replace(
        create_case(),
        late_authorization_detected_at=(NOW - timedelta(minutes=1)),
    )

    decision = evaluate_recovery_proposal(
        case,
        create_payment_link_proposal(),
        evaluated_at=NOW,
    )

    assert decision.outcome is RecoveryPolicyOutcome.STOP
    assert decision.guardrails == (RecoveryGuardrail.LATE_AUTHORIZATION_DETECTED,)


def test_terminal_case_stops_recovery() -> None:
    case = replace(
        create_case(),
        status=RecoveryCaseStatus.CANCELLED,
    )

    decision = evaluate_recovery_proposal(
        case,
        create_payment_link_proposal(),
        evaluated_at=NOW,
    )

    assert decision.outcome is RecoveryPolicyOutcome.STOP
    assert decision.guardrails == (RecoveryGuardrail.CASE_TERMINAL,)


def test_attempt_limit_stops_more_automation() -> None:
    case = replace(
        create_case(),
        recovery_attempt_count=3,
    )

    decision = evaluate_recovery_proposal(
        case,
        create_message_proposal(),
        evaluated_at=NOW,
    )

    assert decision.outcome is RecoveryPolicyOutcome.STOP
    assert decision.guardrails == (RecoveryGuardrail.MAX_ATTEMPTS_REACHED,)


def test_active_incident_blocks_automatic_intervention() -> None:
    case = replace(
        create_case(),
        active_incident_severity=IncidentSeverity.HIGH,
    )

    decision = evaluate_recovery_proposal(
        case,
        create_payment_link_proposal(),
        evaluated_at=NOW,
    )

    assert decision.outcome is RecoveryPolicyOutcome.BLOCK
    assert decision.guardrails == (RecoveryGuardrail.INCIDENT_CIRCUIT_BREAKER,)


def test_duplicate_payment_link_is_blocked() -> None:
    case = replace(
        create_case(),
        active_payment_link_id="plink_existing",
    )

    decision = evaluate_recovery_proposal(
        case,
        create_payment_link_proposal(),
        evaluated_at=NOW,
    )

    assert decision.outcome is RecoveryPolicyOutcome.BLOCK
    assert decision.guardrails == (RecoveryGuardrail.DUPLICATE_PAYMENT_LINK,)


@pytest.mark.parametrize(
    ("proposal", "expected_guardrail"),
    [
        (
            create_payment_link_proposal(
                amount_minor=200_000,
            ),
            RecoveryGuardrail.AMOUNT_MISMATCH,
        ),
        (
            create_payment_link_proposal(
                currency="USD",
            ),
            RecoveryGuardrail.CURRENCY_MISMATCH,
        ),
    ],
)
def test_payment_link_must_match_original_payment(
    proposal: RecoveryActionProposal,
    expected_guardrail: RecoveryGuardrail,
) -> None:
    decision = evaluate_recovery_proposal(
        create_case(),
        proposal,
        evaluated_at=NOW,
    )

    assert decision.outcome is RecoveryPolicyOutcome.BLOCK
    assert expected_guardrail in decision.guardrails


def test_action_above_hard_amount_limit_requires_human_escalation() -> None:
    case = replace(
        create_case(),
        amount_minor=5_000_001,
    )
    proposal = create_payment_link_proposal(
        amount_minor=5_000_001,
    )

    decision = evaluate_recovery_proposal(
        case,
        proposal,
        evaluated_at=NOW,
    )

    assert decision.outcome is RecoveryPolicyOutcome.ESCALATE
    assert decision.guardrails == (RecoveryGuardrail.AUTOMATIC_AMOUNT_LIMIT,)


def test_missing_consent_and_quiet_period_are_both_audited() -> None:
    case = replace(
        create_case(),
        customer_contact_allowed=False,
        last_customer_contact_at=(NOW - timedelta(hours=1)),
    )

    decision = evaluate_recovery_proposal(
        case,
        create_message_proposal(),
        evaluated_at=NOW,
    )

    assert decision.outcome is RecoveryPolicyOutcome.BLOCK
    assert decision.guardrails == (
        RecoveryGuardrail.CONTACT_CONSENT_MISSING,
        RecoveryGuardrail.QUIET_PERIOD_ACTIVE,
    )


def test_wait_is_safe_during_incident_and_quiet_period() -> None:
    case = replace(
        create_case(),
        active_incident_severity=IncidentSeverity.CRITICAL,
        last_customer_contact_at=(NOW - timedelta(minutes=30)),
    )
    proposal = RecoveryActionProposal(
        action_type=RecoveryActionType.WAIT,
        reason="Pause while the payment rail recovers",
        execute_after=NOW + timedelta(hours=1),
    )

    decision = evaluate_recovery_proposal(
        case,
        proposal,
        evaluated_at=NOW,
    )

    assert decision.outcome is RecoveryPolicyOutcome.ALLOW


@pytest.mark.parametrize(
    ("action_type", "expected_outcome", "guardrail"),
    [
        (
            RecoveryActionType.ESCALATE_HUMAN,
            RecoveryPolicyOutcome.ESCALATE,
            RecoveryGuardrail.AGENT_REQUESTED_ESCALATION,
        ),
        (
            RecoveryActionType.STOP_RECOVERY,
            RecoveryPolicyOutcome.STOP,
            RecoveryGuardrail.AGENT_REQUESTED_STOP,
        ),
    ],
)
def test_respects_bounded_agent_control_actions(
    action_type: RecoveryActionType,
    expected_outcome: RecoveryPolicyOutcome,
    guardrail: RecoveryGuardrail,
) -> None:
    proposal = RecoveryActionProposal(
        action_type=action_type,
        reason="Agent selected a bounded control action",
    )

    decision = evaluate_recovery_proposal(
        create_case(),
        proposal,
        evaluated_at=NOW,
    )

    assert decision.outcome is expected_outcome
    assert decision.guardrails == (guardrail,)


def test_rejects_invalid_policy_configuration() -> None:
    with pytest.raises(
        ValueError,
        match="attempts",
    ):
        RecoveryPolicy(
            maximum_recovery_attempts=0,
        )


def test_requires_timezone_aware_evaluation_time() -> None:
    with pytest.raises(
        ValueError,
        match="timezone-aware",
    ):
        evaluate_recovery_proposal(
            create_case(),
            create_payment_link_proposal(),
            evaluated_at=datetime(2026, 8, 25, 10, 0),
        )
