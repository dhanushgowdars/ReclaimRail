from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Final

from app.domain.incidents import IncidentSeverity
from app.domain.payments import STOP_RECOVERY_STATES
from app.domain.recovery.models import (
    RecoveryActionProposal,
    RecoveryActionType,
    RecoveryCaseSnapshot,
    RecoveryCaseStatus,
    RecoveryChannel,
)


class RecoveryPlanDecision(StrEnum):
    RECOVER = "recover"
    WAIT = "wait"
    ESCALATE = "escalate"
    STOP = "stop"


@dataclass(frozen=True, slots=True)
class PaymentFailureEvidence:
    error_code: str | None
    error_source: str | None
    error_step: str | None
    error_reason: str | None
    failure_count: int
    first_failed_at: datetime
    last_failed_at: datetime

    def __post_init__(self) -> None:
        if self.failure_count < 1:
            raise ValueError("Failure evidence requires at least one failure")

        for field_name, timestamp in (
            ("First failure", self.first_failed_at),
            ("Last failure", self.last_failed_at),
        ):
            if timestamp.tzinfo is None or timestamp.utcoffset() is None:
                raise ValueError(f"{field_name} must be timezone-aware")

        if self.last_failed_at < self.first_failed_at:
            raise ValueError("Last failure cannot be earlier than first failure")

        for attribute in (
            "error_code",
            "error_source",
            "error_step",
            "error_reason",
        ):
            value = getattr(self, attribute)
            if value is not None:
                normalized = value.strip().casefold()
                object.__setattr__(self, attribute, normalized or None)


@dataclass(frozen=True, slots=True)
class RecoveryPlanningContext:
    case: RecoveryCaseSnapshot
    failure: PaymentFailureEvidence
    available_channels: tuple[RecoveryChannel, ...]
    alternate_payment_methods: tuple[str, ...]
    planned_at: datetime

    def __post_init__(self) -> None:
        if self.planned_at.tzinfo is None or self.planned_at.utcoffset() is None:
            raise ValueError("Planning time must be timezone-aware")

        normalized_channels = tuple(dict.fromkeys(self.available_channels))
        object.__setattr__(self, "available_channels", normalized_channels)

        normalized_methods = tuple(
            dict.fromkeys(
                method.strip().casefold()
                for method in self.alternate_payment_methods
                if method.strip()
            ),
        )
        object.__setattr__(self, "alternate_payment_methods", normalized_methods)


@dataclass(frozen=True, slots=True)
class RecoveryPlannerPolicy:
    maximum_recovery_attempts: int = 3
    automatic_amount_limit_minor: int = 1_000_000
    incident_recheck_delay: timedelta = timedelta(minutes=15)
    maximum_plan_actions: int = 3

    def __post_init__(self) -> None:
        if self.maximum_recovery_attempts < 1:
            raise ValueError("Maximum recovery attempts must be positive")
        if self.automatic_amount_limit_minor < 1:
            raise ValueError("Automatic amount limit must be positive")
        if self.incident_recheck_delay <= timedelta(0):
            raise ValueError("Incident recheck delay must be positive")
        if not 1 <= self.maximum_plan_actions <= 3:
            raise ValueError("Maximum plan actions must be between one and three")


@dataclass(frozen=True, slots=True)
class RecoveryPlan:
    decision: RecoveryPlanDecision
    reasoning_summary: str
    proposals: tuple[RecoveryActionProposal, ...]
    evidence_codes: tuple[str, ...]
    generated_at: datetime
    planner_version: str = "deterministic-v1"

    def __post_init__(self) -> None:
        reasoning_summary = self.reasoning_summary.strip()
        planner_version = self.planner_version.strip()

        if not reasoning_summary:
            raise ValueError("Recovery plan requires a reasoning summary")
        if not planner_version:
            raise ValueError("Recovery plan requires a planner version")
        if not self.proposals:
            raise ValueError("Recovery plan requires at least one proposal")
        if len(self.proposals) > 3:
            raise ValueError("Recovery plan cannot contain more than three proposals")
        if not self.evidence_codes:
            raise ValueError("Recovery plan requires evidence codes")
        if self.generated_at.tzinfo is None or self.generated_at.utcoffset() is None:
            raise ValueError("Plan generation time must be timezone-aware")

        object.__setattr__(self, "reasoning_summary", reasoning_summary)
        object.__setattr__(self, "planner_version", planner_version)
        object.__setattr__(
            self,
            "evidence_codes",
            tuple(dict.fromkeys(code.strip() for code in self.evidence_codes if code.strip())),
        )


DEFAULT_RECOVERY_PLANNER_POLICY: Final = RecoveryPlannerPolicy()

TERMINAL_CASE_STATUSES: Final = frozenset(
    {
        RecoveryCaseStatus.RECOVERED,
        RecoveryCaseStatus.EXHAUSTED,
        RecoveryCaseStatus.CANCELLED,
    },
)

CIRCUIT_BREAKER_SEVERITIES: Final = frozenset(
    {
        IncidentSeverity.HIGH,
        IncidentSeverity.CRITICAL,
    },
)


def _failure_evidence_codes(
    context: RecoveryPlanningContext,
) -> tuple[str, ...]:
    evidence = [
        f"payment_state:{context.case.payment_state.value}",
        f"failure_count:{context.failure.failure_count}",
        f"contact_consent:{str(context.case.customer_contact_allowed).lower()}",
    ]

    if context.failure.error_code is not None:
        evidence.append(f"error_code:{context.failure.error_code}")
    if context.failure.error_reason is not None:
        evidence.append(f"error_reason:{context.failure.error_reason}")
    if context.case.active_incident_severity is not None:
        evidence.append(f"incident:{context.case.active_incident_severity.value}")
    if context.case.active_payment_link_id is not None:
        evidence.append("active_payment_link:true")

    return tuple(evidence)


def _bounded_plan(
    *,
    decision: RecoveryPlanDecision,
    reasoning_summary: str,
    proposals: tuple[RecoveryActionProposal, ...],
    context: RecoveryPlanningContext,
    policy: RecoveryPlannerPolicy,
) -> RecoveryPlan:
    return RecoveryPlan(
        decision=decision,
        reasoning_summary=reasoning_summary,
        proposals=proposals[: policy.maximum_plan_actions],
        evidence_codes=_failure_evidence_codes(context),
        generated_at=context.planned_at,
    )


def build_deterministic_recovery_plan(
    context: RecoveryPlanningContext,
    *,
    policy: RecoveryPlannerPolicy = DEFAULT_RECOVERY_PLANNER_POLICY,
) -> RecoveryPlan:
    case = context.case

    if (
        case.status in TERMINAL_CASE_STATUSES
        or case.payment_state in STOP_RECOVERY_STATES
        or case.late_authorization_detected_at is not None
    ):
        return _bounded_plan(
            decision=RecoveryPlanDecision.STOP,
            reasoning_summary="Payment or recovery case is already terminal; stop intervention",
            proposals=(
                RecoveryActionProposal(
                    action_type=RecoveryActionType.STOP_RECOVERY,
                    reason="Stop recovery because terminal payment evidence is present",
                ),
            ),
            context=context,
            policy=policy,
        )

    if (
        case.status is RecoveryCaseStatus.ESCALATED
        or case.recovery_attempt_count >= policy.maximum_recovery_attempts
        or case.amount_minor > policy.automatic_amount_limit_minor
    ):
        return _bounded_plan(
            decision=RecoveryPlanDecision.ESCALATE,
            reasoning_summary="Automation boundary reached; require human review",
            proposals=(
                RecoveryActionProposal(
                    action_type=RecoveryActionType.ESCALATE_HUMAN,
                    reason="Escalate because bounded automation limits were reached",
                ),
            ),
            context=context,
            policy=policy,
        )

    if case.active_incident_severity in CIRCUIT_BREAKER_SEVERITIES:
        return _bounded_plan(
            decision=RecoveryPlanDecision.WAIT,
            reasoning_summary="Payment rail is degraded; pause customer intervention",
            proposals=(
                RecoveryActionProposal(
                    action_type=RecoveryActionType.WAIT,
                    reason="Wait for the active payment incident to recover",
                    execute_after=context.planned_at + policy.incident_recheck_delay,
                ),
            ),
            context=context,
            policy=policy,
        )

    preferred_channel = context.available_channels[0] if context.available_channels else None

    if case.active_payment_link_id is not None:
        if case.customer_contact_allowed and preferred_channel is not None:
            return _bounded_plan(
                decision=RecoveryPlanDecision.RECOVER,
                reasoning_summary="Reuse the existing payment link and send one bounded reminder",
                proposals=(
                    RecoveryActionProposal(
                        action_type=RecoveryActionType.SEND_RECOVERY_MESSAGE,
                        reason="Send the existing recovery link through an approved channel",
                        channel=preferred_channel,
                    ),
                ),
                context=context,
                policy=policy,
            )

        return _bounded_plan(
            decision=RecoveryPlanDecision.WAIT,
            reasoning_summary="A payment link exists but no approved contact channel is available",
            proposals=(
                RecoveryActionProposal(
                    action_type=RecoveryActionType.WAIT,
                    reason="Wait for an approved customer recovery channel",
                    execute_after=context.planned_at + policy.incident_recheck_delay,
                ),
            ),
            context=context,
            policy=policy,
        )

    proposals: list[RecoveryActionProposal] = [
        RecoveryActionProposal(
            action_type=RecoveryActionType.CREATE_PAYMENT_LINK,
            reason="Create one idempotent payment link for the original amount",
            amount_minor=case.amount_minor,
            currency=case.currency,
        ),
    ]

    alternate_method = next(
        (method for method in context.alternate_payment_methods if method != case.payment_method),
        None,
    )

    if (
        case.customer_contact_allowed
        and preferred_channel is not None
        and alternate_method is not None
    ):
        proposals.append(
            RecoveryActionProposal(
                action_type=RecoveryActionType.OFFER_ALTERNATE_METHOD,
                reason="Offer one alternate payment method after the original failure",
                channel=preferred_channel,
                target_payment_method=alternate_method,
            ),
        )

    if case.customer_contact_allowed and preferred_channel is not None:
        proposals.append(
            RecoveryActionProposal(
                action_type=RecoveryActionType.SEND_RECOVERY_MESSAGE,
                reason="Send one recovery message through an approved channel",
                channel=preferred_channel,
            ),
        )

    return _bounded_plan(
        decision=RecoveryPlanDecision.RECOVER,
        reasoning_summary="Payment remains failed and is eligible for bounded recovery",
        proposals=tuple(proposals),
        context=context,
        policy=policy,
    )
