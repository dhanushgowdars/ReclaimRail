import asyncio
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
)

from app.domain.incidents import IncidentDetectorPolicy
from app.domain.incidents.detector import (
    DEFAULT_INCIDENT_DETECTOR_POLICY,
)
from app.services.incident_detection_runner import (
    IncidentDetectionRunResult,
    run_payment_method_incident_detection,
)
from app.services.incident_window_aggregator import (
    DEFAULT_BASELINE_WINDOW_COUNT,
    DEFAULT_WINDOW_SIZE,
)


@dataclass(frozen=True, slots=True)
class PaymentMethodDetectionFailure:
    payment_method: str
    error_type: str
    error_message: str


@dataclass(frozen=True, slots=True)
class IncidentDetectionBatchResult:
    detector_run_id: UUID
    reference_time: datetime
    currency: str
    successful_results: tuple[
        IncidentDetectionRunResult,
        ...,
    ]
    failures: tuple[PaymentMethodDetectionFailure, ...]

    @property
    def attempted(self) -> int:
        return len(self.successful_results) + len(
            self.failures,
        )

    @property
    def succeeded(self) -> int:
        return len(self.successful_results)

    @property
    def failed(self) -> int:
        return len(self.failures)


def normalize_payment_methods(
    payment_methods: Sequence[str],
) -> tuple[str, ...]:
    normalized_methods: list[str] = []
    seen: set[str] = set()

    for payment_method in payment_methods:
        normalized_method = payment_method.strip().casefold()

        if not normalized_method:
            raise ValueError(
                "Payment methods cannot contain empty values",
            )

        if normalized_method in seen:
            continue

        seen.add(normalized_method)
        normalized_methods.append(normalized_method)

    if not normalized_methods:
        raise ValueError(
            "At least one payment method is required",
        )

    return tuple(normalized_methods)


async def run_incident_detection_batch(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    payment_methods: Sequence[str],
    currency: str,
    reference_time: datetime,
    detector_run_id: UUID | None = None,
    window_size: timedelta = DEFAULT_WINDOW_SIZE,
    baseline_window_count: int = DEFAULT_BASELINE_WINDOW_COUNT,
    policy: IncidentDetectorPolicy = (DEFAULT_INCIDENT_DETECTOR_POLICY),
) -> IncidentDetectionBatchResult:
    normalized_methods = normalize_payment_methods(
        payment_methods,
    )
    normalized_currency = currency.strip().upper()

    if len(normalized_currency) != 3:
        raise ValueError(
            "Currency must be a three-letter code",
        )

    resolved_run_id = detector_run_id or uuid4()

    successful_results: list[IncidentDetectionRunResult] = []
    failures: list[PaymentMethodDetectionFailure] = []

    for payment_method in normalized_methods:
        try:
            async with (
                session_factory() as session,
                session.begin(),
            ):
                result = await run_payment_method_incident_detection(
                    session,
                    payment_method=payment_method,
                    currency=normalized_currency,
                    reference_time=reference_time,
                    detector_run_id=resolved_run_id,
                    detected_at=reference_time,
                    window_size=window_size,
                    baseline_window_count=(baseline_window_count),
                    policy=policy,
                )

            successful_results.append(result)

        except asyncio.CancelledError:
            raise

        except Exception as error:
            failures.append(
                PaymentMethodDetectionFailure(
                    payment_method=payment_method,
                    error_type=type(error).__name__,
                    error_message=str(error),
                ),
            )

    return IncidentDetectionBatchResult(
        detector_run_id=resolved_run_id,
        reference_time=reference_time,
        currency=normalized_currency,
        successful_results=tuple(successful_results),
        failures=tuple(failures),
    )
