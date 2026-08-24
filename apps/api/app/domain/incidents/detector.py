from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from statistics import median
from typing import Final


class IncidentScope(StrEnum):
    GLOBAL = "global"
    PAYMENT_METHOD = "payment_method"
    ERROR_SIGNATURE = "error_signature"


class IncidentSeverity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class IncidentDetectionOutcome(StrEnum):
    NORMAL = "normal"
    INSUFFICIENT_DATA = "insufficient_data"
    INCIDENT = "incident"


class IncidentReason(StrEnum):
    FAILURE_RATE_THRESHOLD = "failure_rate_threshold"
    BASELINE_UPLIFT = "baseline_uplift"
    ROBUST_DEVIATION = "robust_deviation"
    RATE_MULTIPLIER = "rate_multiplier"
    REVENUE_AT_RISK = "revenue_at_risk"


@dataclass(frozen=True, slots=True)
class PaymentWindowMetrics:
    scope: IncidentScope
    dimension_value: str

    window_start: datetime
    window_end: datetime

    total_attempts: int
    failed_attempts: int

    total_amount_minor: int
    failed_amount_minor: int

    def __post_init__(self) -> None:
        if not self.dimension_value.strip():
            raise ValueError("Dimension value cannot be empty")

        if self.window_start.tzinfo is None:
            raise ValueError("Window start must be timezone-aware")

        if self.window_end.tzinfo is None:
            raise ValueError("Window end must be timezone-aware")

        if self.window_end <= self.window_start:
            raise ValueError("Window end must be after window start")

        if self.total_attempts < 0:
            raise ValueError("Total attempts cannot be negative")

        if self.failed_attempts < 0:
            raise ValueError("Failed attempts cannot be negative")

        if self.failed_attempts > self.total_attempts:
            raise ValueError(
                "Failed attempts cannot exceed total attempts",
            )

        if self.total_amount_minor < 0:
            raise ValueError("Total amount cannot be negative")

        if self.failed_amount_minor < 0:
            raise ValueError("Failed amount cannot be negative")

        if self.failed_amount_minor > self.total_amount_minor:
            raise ValueError(
                "Failed amount cannot exceed total amount",
            )

    @property
    def failure_rate(self) -> float:
        if self.total_attempts == 0:
            return 0.0

        return self.failed_attempts / self.total_attempts


@dataclass(frozen=True, slots=True)
class BaselineProfile:
    scope: IncidentScope
    dimension_value: str
    window_count: int
    median_failure_rate: float
    mad_failure_rate: float
    median_failed_amount_minor: int

    def __post_init__(self) -> None:
        if not self.dimension_value.strip():
            raise ValueError("Dimension value cannot be empty")

        if self.window_count < 1:
            raise ValueError(
                "Baseline must contain at least one window",
            )

        if not 0.0 <= self.median_failure_rate <= 1.0:
            raise ValueError(
                "Median failure rate must be between 0 and 1",
            )

        if self.mad_failure_rate < 0.0:
            raise ValueError("MAD cannot be negative")

        if self.median_failed_amount_minor < 0:
            raise ValueError(
                "Median failed amount cannot be negative",
            )


@dataclass(frozen=True, slots=True)
class IncidentDetectorPolicy:
    minimum_baseline_windows: int = 6
    minimum_attempts: int = 20
    minimum_failed_attempts: int = 5

    minimum_failure_rate: float = 0.15
    minimum_absolute_uplift: float = 0.08
    minimum_rate_multiplier: float = 2.0
    minimum_robust_z_score: float = 3.5
    mad_floor: float = 0.01

    minimum_failed_amount_minor: int = 50_000

    medium_failure_rate: float = 0.20
    high_failure_rate: float = 0.35
    critical_failure_rate: float = 0.60

    high_failed_amount_minor: int = 500_000
    critical_failed_amount_minor: int = 2_000_000

    high_robust_z_score: float = 6.0
    critical_robust_z_score: float = 10.0

    def __post_init__(self) -> None:
        if self.minimum_baseline_windows < 1:
            raise ValueError(
                "Minimum baseline windows must be positive",
            )

        if self.minimum_attempts < 1:
            raise ValueError("Minimum attempts must be positive")

        if self.minimum_failed_attempts < 1:
            raise ValueError(
                "Minimum failed attempts must be positive",
            )

        rate_values = (
            self.minimum_failure_rate,
            self.minimum_absolute_uplift,
            self.medium_failure_rate,
            self.high_failure_rate,
            self.critical_failure_rate,
        )

        if any(not 0.0 <= value <= 1.0 for value in rate_values):
            raise ValueError(
                "Rate thresholds must be between 0 and 1",
            )

        if self.minimum_rate_multiplier <= 1.0:
            raise ValueError(
                "Rate multiplier must be greater than one",
            )

        if self.minimum_robust_z_score <= 0.0:
            raise ValueError(
                "Robust z-score threshold must be positive",
            )

        if self.mad_floor <= 0.0:
            raise ValueError("MAD floor must be positive")

        if self.minimum_failed_amount_minor < 0:
            raise ValueError(
                "Minimum failed amount cannot be negative",
            )


@dataclass(frozen=True, slots=True)
class IncidentDetectionDecision:
    outcome: IncidentDetectionOutcome
    fingerprint: str
    scope: IncidentScope
    dimension_value: str

    severity: IncidentSeverity | None
    reason_codes: tuple[IncidentReason, ...]

    failure_rate: float
    baseline_failure_rate: float
    absolute_uplift: float
    rate_multiplier: float | None
    robust_z_score: float

    revenue_at_risk_minor: int
    confidence: float


DEFAULT_INCIDENT_DETECTOR_POLICY: Final = IncidentDetectorPolicy()

ROBUST_Z_SCALE: Final = 0.67448975


def normalize_dimension_value(value: str) -> str:
    return "-".join(
        value.strip().casefold().split(),
    )


def build_incident_fingerprint(
    scope: IncidentScope,
    dimension_value: str,
) -> str:
    normalized_value = normalize_dimension_value(
        dimension_value,
    )

    if not normalized_value:
        raise ValueError("Dimension value cannot be empty")

    return f"payment_degradation:{scope.value}:{normalized_value}"


def build_baseline_profile(
    windows: Sequence[PaymentWindowMetrics],
) -> BaselineProfile:
    if not windows:
        raise ValueError(
            "At least one historical window is required",
        )

    first_window = windows[0]
    expected_fingerprint = build_incident_fingerprint(
        first_window.scope,
        first_window.dimension_value,
    )

    for window in windows:
        fingerprint = build_incident_fingerprint(
            window.scope,
            window.dimension_value,
        )

        if fingerprint != expected_fingerprint:
            raise ValueError(
                "Baseline windows must use the same dimension",
            )

    failure_rates = [window.failure_rate for window in windows]
    median_failure_rate = float(
        median(failure_rates),
    )

    absolute_deviations = [abs(rate - median_failure_rate) for rate in failure_rates]
    mad_failure_rate = float(
        median(absolute_deviations),
    )

    median_failed_amount_minor = int(
        median(
            [window.failed_amount_minor for window in windows],
        ),
    )

    return BaselineProfile(
        scope=first_window.scope,
        dimension_value=first_window.dimension_value,
        window_count=len(windows),
        median_failure_rate=median_failure_rate,
        mad_failure_rate=mad_failure_rate,
        median_failed_amount_minor=(median_failed_amount_minor),
    )


def calculate_robust_z_score(
    failure_rate: float,
    baseline: BaselineProfile,
    policy: IncidentDetectorPolicy,
) -> float:
    deviation = failure_rate - baseline.median_failure_rate
    denominator = max(
        baseline.mad_failure_rate,
        policy.mad_floor,
    )

    return ROBUST_Z_SCALE * deviation / denominator


def calculate_detector_confidence(
    metrics: PaymentWindowMetrics,
    baseline: BaselineProfile,
    robust_z_score: float,
    policy: IncidentDetectorPolicy,
) -> float:
    sample_confidence = min(
        metrics.total_attempts / float(policy.minimum_attempts * 4),
        1.0,
    )
    baseline_confidence = min(
        baseline.window_count / float(policy.minimum_baseline_windows * 2),
        1.0,
    )
    deviation_confidence = min(
        max(robust_z_score, 0.0) / (policy.minimum_robust_z_score * 2),
        1.0,
    )

    confidence = 0.35 * sample_confidence + 0.25 * baseline_confidence + 0.40 * deviation_confidence

    return round(
        max(0.0, min(confidence, 1.0)),
        4,
    )


def determine_incident_severity(
    metrics: PaymentWindowMetrics,
    robust_z_score: float,
    policy: IncidentDetectorPolicy,
) -> IncidentSeverity:
    if metrics.failed_amount_minor >= policy.critical_failed_amount_minor or (
        metrics.failure_rate >= policy.critical_failure_rate
        and robust_z_score >= policy.critical_robust_z_score
    ):
        return IncidentSeverity.CRITICAL

    if (
        metrics.failed_amount_minor >= policy.high_failed_amount_minor
        or metrics.failure_rate >= policy.high_failure_rate
        or robust_z_score >= policy.high_robust_z_score
    ):
        return IncidentSeverity.HIGH

    if metrics.failure_rate >= policy.medium_failure_rate:
        return IncidentSeverity.MEDIUM

    return IncidentSeverity.LOW


def detect_payment_degradation(
    metrics: PaymentWindowMetrics,
    baseline: BaselineProfile,
    policy: IncidentDetectorPolicy = (DEFAULT_INCIDENT_DETECTOR_POLICY),
) -> IncidentDetectionDecision:
    fingerprint = build_incident_fingerprint(
        metrics.scope,
        metrics.dimension_value,
    )
    baseline_fingerprint = build_incident_fingerprint(
        baseline.scope,
        baseline.dimension_value,
    )

    if fingerprint != baseline_fingerprint:
        raise ValueError(
            "Metrics and baseline dimensions do not match",
        )

    failure_rate = metrics.failure_rate
    uplift = failure_rate - baseline.median_failure_rate

    rate_multiplier = (
        failure_rate / baseline.median_failure_rate if baseline.median_failure_rate > 0.0 else None
    )

    robust_z_score = calculate_robust_z_score(
        failure_rate,
        baseline,
        policy,
    )

    confidence = calculate_detector_confidence(
        metrics,
        baseline,
        robust_z_score,
        policy,
    )

    insufficient_data = (
        baseline.window_count < policy.minimum_baseline_windows
        or metrics.total_attempts < policy.minimum_attempts
        or metrics.failed_attempts < policy.minimum_failed_attempts
    )

    if insufficient_data:
        return IncidentDetectionDecision(
            outcome=(IncidentDetectionOutcome.INSUFFICIENT_DATA),
            fingerprint=fingerprint,
            scope=metrics.scope,
            dimension_value=metrics.dimension_value,
            severity=None,
            reason_codes=(),
            failure_rate=round(failure_rate, 6),
            baseline_failure_rate=round(
                baseline.median_failure_rate,
                6,
            ),
            absolute_uplift=round(uplift, 6),
            rate_multiplier=(round(rate_multiplier, 4) if rate_multiplier is not None else None),
            robust_z_score=round(robust_z_score, 4),
            revenue_at_risk_minor=(metrics.failed_amount_minor),
            confidence=confidence,
        )

    meets_rate_floor = failure_rate >= policy.minimum_failure_rate
    meets_uplift = uplift >= policy.minimum_absolute_uplift
    meets_revenue_floor = metrics.failed_amount_minor >= policy.minimum_failed_amount_minor
    robust_deviation = robust_z_score >= policy.minimum_robust_z_score
    rate_multiplier_signal = (
        rate_multiplier is not None and rate_multiplier >= policy.minimum_rate_multiplier
    )

    incident_detected = (
        meets_rate_floor
        and meets_uplift
        and meets_revenue_floor
        and (robust_deviation or rate_multiplier_signal)
    )

    if not incident_detected:
        return IncidentDetectionDecision(
            outcome=IncidentDetectionOutcome.NORMAL,
            fingerprint=fingerprint,
            scope=metrics.scope,
            dimension_value=metrics.dimension_value,
            severity=None,
            reason_codes=(),
            failure_rate=round(failure_rate, 6),
            baseline_failure_rate=round(
                baseline.median_failure_rate,
                6,
            ),
            absolute_uplift=round(uplift, 6),
            rate_multiplier=(round(rate_multiplier, 4) if rate_multiplier is not None else None),
            robust_z_score=round(robust_z_score, 4),
            revenue_at_risk_minor=(metrics.failed_amount_minor),
            confidence=confidence,
        )

    reason_codes = [
        IncidentReason.FAILURE_RATE_THRESHOLD,
        IncidentReason.BASELINE_UPLIFT,
        IncidentReason.REVENUE_AT_RISK,
    ]

    if robust_deviation:
        reason_codes.append(
            IncidentReason.ROBUST_DEVIATION,
        )

    if rate_multiplier_signal:
        reason_codes.append(
            IncidentReason.RATE_MULTIPLIER,
        )

    severity = determine_incident_severity(
        metrics,
        robust_z_score,
        policy,
    )

    return IncidentDetectionDecision(
        outcome=IncidentDetectionOutcome.INCIDENT,
        fingerprint=fingerprint,
        scope=metrics.scope,
        dimension_value=metrics.dimension_value,
        severity=severity,
        reason_codes=tuple(reason_codes),
        failure_rate=round(failure_rate, 6),
        baseline_failure_rate=round(
            baseline.median_failure_rate,
            6,
        ),
        absolute_uplift=round(uplift, 6),
        rate_multiplier=(round(rate_multiplier, 4) if rate_multiplier is not None else None),
        robust_z_score=round(robust_z_score, 4),
        revenue_at_risk_minor=(metrics.failed_amount_minor),
        confidence=confidence,
    )
