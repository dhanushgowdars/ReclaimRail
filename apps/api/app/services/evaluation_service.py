"""Reproducible, policy-backed evaluation evidence. Never writes merchant outcomes."""

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.evaluation import EvaluationRun, EvaluationScenario
from app.domain.incidents import IncidentSeverity
from app.domain.payments import PaymentState
from app.domain.recovery import (
    RecoveryActionProposal,
    RecoveryActionType,
    RecoveryCaseSnapshot,
    RecoveryCaseStatus,
    RecoveryChannel,
    RecoveryPolicyOutcome,
    evaluate_recovery_proposal,
)

SYNTHETIC_PROVENANCE = "controlled_synthetic"
DEFAULT_RUN_KEY = "track3-policy-evidence-v2"
POLICY_VERSION = "deterministic-recovery-policy-v1"


@dataclass(frozen=True, slots=True)
class EvaluationMetrics:
    payments_evaluated: int
    failed_or_at_risk: int
    recovery_eligible: int
    recovery_attempted: int
    successfully_recovered: int
    recovered_minor: int
    baseline_recovered_minor: int
    incremental_recovered_minor: int
    pending_minor: int
    unsafe_actions_blocked: int
    duplicate_recovery_blocked: int
    late_authorization_stops: int
    recovery_rate_percent: float


def _hash(payload: dict[str, object]) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _controlled_spec(number: int) -> dict[str, object]:
    """48 deterministic cases covering recoveries and policy safety branches."""
    method = ("upi", "card", "netbanking", "wallet")[(number - 1) % 4]
    amount = (59_900, 79_900, 99_900, 119_900)[(number - 1) % 4]
    spec: dict[str, object] = {
        "number": number,
        "method": method,
        "amount": amount,
        "at_risk": False,
        "eligible": False,
        "attempted": False,
        "condition": "Payment healthy; no recovery intervention needed",
        "recommendation": "Wait and continue normal payment monitoring",
        "action": RecoveryActionType.WAIT,
        "expected": RecoveryPolicyOutcome.ALLOW,
        "outcome": "not_at_risk",
        "execution": "no_action_required",
        "active_link": False,
        "late_authorization": False,
        "consent": True,
        "quiet_period": False,
        "incident": None,
        "attempt_count": 0,
    }
    if number <= 10:
        spec.update(
            at_risk=True,
            eligible=True,
            attempted=True,
            condition="Payment failed and recovery eligibility checks passed",
            recommendation="Create a single bounded recovery payment link",
            action=RecoveryActionType.CREATE_PAYMENT_LINK,
            expected=RecoveryPolicyOutcome.ALLOW,
            outcome="recovered",
            execution="simulated_provider_confirmation",
        )
    elif number <= 16:
        spec.update(
            at_risk=True,
            eligible=True,
            attempted=True,
            condition="Payment failed; provider evidence not yet reconciled",
            recommendation="Create one bounded recovery link and await provider proof",
            action=RecoveryActionType.CREATE_PAYMENT_LINK,
            expected=RecoveryPolicyOutcome.ALLOW,
            outcome="pending_provider_proof",
            execution="awaiting_simulated_provider_evidence",
        )
    elif number <= 20:
        spec.update(
            at_risk=True,
            eligible=True,
            condition="An active recovery payment link already exists",
            recommendation="Do not create another link; prevent duplicate collection",
            action=RecoveryActionType.CREATE_PAYMENT_LINK,
            expected=RecoveryPolicyOutcome.BLOCK,
            outcome="duplicate_prevented",
            execution="blocked_before_action",
            active_link=True,
        )
    elif number <= 23:
        spec.update(
            at_risk=True,
            eligible=True,
            condition="A late authorisation arrived after recovery started",
            recommendation="Stop recovery immediately to avoid duplicate collection",
            action=RecoveryActionType.CREATE_PAYMENT_LINK,
            expected=RecoveryPolicyOutcome.STOP,
            outcome="late_authorization_stopped",
            execution="stopped_before_action",
            late_authorization=True,
        )
    elif number <= 27:
        spec.update(
            at_risk=True,
            condition="Customer contact consent is missing",
            recommendation="Do not message the customer; request consent or human review",
            action=RecoveryActionType.SEND_RECOVERY_MESSAGE,
            expected=RecoveryPolicyOutcome.BLOCK,
            outcome="consent_blocked",
            execution="blocked_before_contact",
            consent=False,
        )
    elif number <= 30:
        spec.update(
            at_risk=True,
            condition="Customer was contacted inside the configured quiet period",
            recommendation="Wait until quiet hours end before sending a recovery message",
            action=RecoveryActionType.SEND_RECOVERY_MESSAGE,
            expected=RecoveryPolicyOutcome.BLOCK,
            outcome="quiet_hours_blocked",
            execution="blocked_before_contact",
            quiet_period=True,
        )
    elif number <= 33:
        spec.update(
            at_risk=True,
            condition="Payment rail incident circuit breaker is active",
            recommendation="Pause automated intervention and escalate the incident",
            action=RecoveryActionType.CREATE_PAYMENT_LINK,
            expected=RecoveryPolicyOutcome.BLOCK,
            outcome="incident_paused",
            execution="blocked_by_circuit_breaker",
            incident=IncidentSeverity.HIGH,
        )
    elif number <= 36:
        spec.update(
            at_risk=True,
            condition="Maximum safe recovery attempts have already been reached",
            recommendation="Stop automatic recovery and route the case to review",
            action=RecoveryActionType.CREATE_PAYMENT_LINK,
            expected=RecoveryPolicyOutcome.STOP,
            outcome="max_attempts_stopped",
            execution="stopped_before_action",
            attempt_count=3,
        )
    elif number <= 40:
        spec.update(
            at_risk=True,
            condition="Recovery requires a human decision due to customer context",
            recommendation="Escalate to a human reviewer; do not auto-contact",
            action=RecoveryActionType.ESCALATE_HUMAN,
            expected=RecoveryPolicyOutcome.ESCALATE,
            outcome="human_review_required",
            execution="queued_for_human_review",
        )
    return spec


def _proposal(spec: dict[str, object], now: datetime) -> RecoveryActionProposal:
    action = spec["action"]
    kwargs: dict[str, object] = {"action_type": action, "reason": str(spec["recommendation"])}
    if action is RecoveryActionType.CREATE_PAYMENT_LINK:
        kwargs.update(amount_minor=int(spec["amount"]), currency="INR")
    elif action is RecoveryActionType.SEND_RECOVERY_MESSAGE:
        kwargs.update(channel=RecoveryChannel.EMAIL)
    elif action is RecoveryActionType.WAIT:
        kwargs.update(execute_after=now + timedelta(minutes=15))
    return RecoveryActionProposal(**kwargs)


def _evaluate(spec: dict[str, object], now: datetime):
    snapshot = RecoveryCaseSnapshot(
        case_id=uuid4(),
        payment_attempt_id=uuid4(),
        provider_payment_id=f"controlled_{spec['number']}",
        payment_state=PaymentState.FAILED,
        amount_minor=int(spec["amount"]),
        currency="INR",
        payment_method=str(spec["method"]),
        status=RecoveryCaseStatus.OPEN,
        recovery_attempt_count=int(spec["attempt_count"]),
        customer_contact_allowed=bool(spec["consent"]),
        last_customer_contact_at=(
            now - timedelta(minutes=10) if bool(spec["quiet_period"]) else None
        ),
        active_payment_link_id=("controlled_active_link" if bool(spec["active_link"]) else None),
        active_incident_severity=spec["incident"],
        late_authorization_detected_at=(now if bool(spec["late_authorization"]) else None),
    )
    return evaluate_recovery_proposal(snapshot, _proposal(spec, now), evaluated_at=now)


async def create_or_load_controlled_evaluation(session: AsyncSession) -> EvaluationRun:
    existing = (
        await session.execute(select(EvaluationRun).where(EvaluationRun.run_key == DEFAULT_RUN_KEY))
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    created_at = datetime.now(UTC).replace(microsecond=0)
    run = EvaluationRun(
        run_key=DEFAULT_RUN_KEY,
        label="Policy Evidence Lab — controlled cohort",
        provenance=SYNTHETIC_PROVENANCE,
        currency="INR",
        scenario_count=48,
        policy_version=POLICY_VERSION,
        audit_root_hash="0" * 64,
    )
    session.add(run)
    await session.flush()
    previous_hash: str | None = None
    for number in range(1, 49):
        spec = _controlled_spec(number)
        evaluated_at = created_at + timedelta(milliseconds=number)
        decision = _evaluate(spec, evaluated_at)
        actual = decision.outcome.value
        expected = spec["expected"].value
        if actual != expected:
            raise RuntimeError(f"Controlled scenario {number} expected {expected}, got {actual}")
        outcome = str(spec["outcome"])
        amount = int(spec["amount"])
        event_hash = _hash(
            {
                "run_key": DEFAULT_RUN_KEY,
                "scenario": number,
                "condition": spec["condition"],
                "proposal": spec["recommendation"],
                "expected": expected,
                "actual": actual,
                "guardrails": [x.value for x in decision.guardrails],
                "previous": previous_hash,
            }
        )
        session.add(
            EvaluationScenario(
                evaluation_run_id=run.id,
                scenario_number=number,
                scenario_key=f"EVID-{number:03d}",
                payment_method=str(spec["method"]),
                original_amount_minor=amount,
                at_risk=bool(spec["at_risk"]),
                eligible=bool(spec["eligible"]),
                attempted=bool(spec["attempted"]),
                outcome=outcome,
                observed_condition=str(spec["condition"]),
                agent_recommendation=str(spec["recommendation"]),
                proposed_action=spec["action"].value,
                expected_policy_outcome=expected,
                policy_outcome=actual,
                policy_explanation=decision.explanation,
                execution_status=str(spec["execution"]),
                guardrails=[x.value for x in decision.guardrails],
                recovered_minor=(amount if outcome == "recovered" else 0),
                control_recovered_minor=0,
                pending_minor=(amount if outcome == "pending_provider_proof" else 0),
                protected_minor=(
                    amount
                    if outcome in {"duplicate_prevented", "late_authorization_stopped"}
                    else 0
                ),
                decision_latency_ms=20 + number,
                audit_previous_hash=previous_hash,
                audit_event_hash=event_hash,
                evaluated_at=evaluated_at,
            )
        )
        previous_hash = event_hash
    run.audit_root_hash = previous_hash or run.audit_root_hash
    await session.flush()
    return run


async def load_evaluation_metrics(
    session: AsyncSession, *, run: EvaluationRun
) -> EvaluationMetrics:
    rows = (
        (
            await session.execute(
                select(EvaluationScenario).where(EvaluationScenario.evaluation_run_id == run.id)
            )
        )
        .scalars()
        .all()
    )
    recovered = [row for row in rows if row.outcome == "recovered"]
    attempted = [row for row in rows if row.attempted]
    recovered_minor = sum(row.recovered_minor for row in rows)
    baseline = sum(row.control_recovered_minor for row in rows)
    return EvaluationMetrics(
        payments_evaluated=len(rows),
        failed_or_at_risk=sum(row.at_risk for row in rows),
        recovery_eligible=sum(row.eligible for row in rows),
        recovery_attempted=len(attempted),
        successfully_recovered=len(recovered),
        recovered_minor=recovered_minor,
        baseline_recovered_minor=baseline,
        incremental_recovered_minor=recovered_minor - baseline,
        pending_minor=sum(row.pending_minor for row in rows),
        unsafe_actions_blocked=sum(row.policy_outcome in {"block", "stop"} for row in rows),
        duplicate_recovery_blocked=sum(row.outcome == "duplicate_prevented" for row in rows),
        late_authorization_stops=sum(row.outcome == "late_authorization_stopped" for row in rows),
        recovery_rate_percent=round((len(recovered) / len(attempted) * 100) if attempted else 0, 1),
    )
