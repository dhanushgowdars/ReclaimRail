from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Final, cast

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.payment import PaymentAttempt, PaymentStateTransition
from app.domain.incidents import IncidentScope, PaymentWindowMetrics

DEFAULT_WINDOW_SIZE: Final = timedelta(minutes=5)
DEFAULT_BASELINE_WINDOW_COUNT: Final = 12

SUPPORTED_PAYMENT_OUTCOMES: Final = (
    "failed",
    "authorized",
    "captured",
)

EPOCH: Final = datetime(1970, 1, 1, tzinfo=UTC)


@dataclass(frozen=True, slots=True)
class PaymentOutcomeSample:
    occurred_at: datetime
    amount_minor: int
    failed: bool

    def __post_init__(self) -> None:
        if self.occurred_at.tzinfo is None or self.occurred_at.utcoffset() is None:
            raise ValueError("Sample timestamp must be timezone-aware")

        if self.amount_minor < 0:
            raise ValueError("Sample amount cannot be negative")


@dataclass(frozen=True, slots=True)
class PaymentWindowSeries:
    baseline_windows: tuple[PaymentWindowMetrics, ...]
    current_window: PaymentWindowMetrics


def _validate_window_configuration(
    window_size: timedelta,
    baseline_window_count: int,
) -> int:
    window_seconds = window_size.total_seconds()

    if window_seconds <= 0:
        raise ValueError("Window size must be positive")

    if not window_seconds.is_integer():
        raise ValueError("Window size must use whole seconds")

    if baseline_window_count < 1:
        raise ValueError("Baseline window count must be positive")

    return int(window_seconds)


def resolve_latest_closed_window_end(
    reference_time: datetime,
    window_size: timedelta = DEFAULT_WINDOW_SIZE,
) -> datetime:
    if reference_time.tzinfo is None or reference_time.utcoffset() is None:
        raise ValueError("Reference time must be timezone-aware")

    window_seconds = _validate_window_configuration(
        window_size,
        baseline_window_count=1,
    )

    reference_utc = reference_time.astimezone(UTC)
    elapsed_seconds = int(
        (reference_utc - EPOCH).total_seconds(),
    )
    closed_boundary_seconds = (elapsed_seconds // window_seconds) * window_seconds

    return EPOCH + timedelta(
        seconds=closed_boundary_seconds,
    )


def build_payment_window_series(
    samples: Sequence[PaymentOutcomeSample],
    *,
    scope: IncidentScope,
    dimension_value: str,
    current_window_end: datetime,
    window_size: timedelta = DEFAULT_WINDOW_SIZE,
    baseline_window_count: int = DEFAULT_BASELINE_WINDOW_COUNT,
) -> PaymentWindowSeries:
    window_seconds = _validate_window_configuration(
        window_size,
        baseline_window_count,
    )

    if current_window_end.tzinfo is None or current_window_end.utcoffset() is None:
        raise ValueError("Current window end must be timezone-aware")

    normalized_dimension = dimension_value.strip()

    if not normalized_dimension:
        raise ValueError("Dimension value cannot be empty")

    total_window_count = baseline_window_count + 1
    series_start = current_window_end - (window_size * total_window_count)

    bucket_samples: list[list[PaymentOutcomeSample]] = [[] for _ in range(total_window_count)]

    for sample in samples:
        if not series_start <= sample.occurred_at < current_window_end:
            continue

        offset_seconds = (sample.occurred_at - series_start).total_seconds()
        bucket_index = int(offset_seconds // window_seconds)

        bucket_samples[bucket_index].append(sample)

    windows: list[PaymentWindowMetrics] = []

    for index, bucket in enumerate(bucket_samples):
        window_start = series_start + window_size * index
        window_end = window_start + window_size

        failed_samples = [sample for sample in bucket if sample.failed]

        windows.append(
            PaymentWindowMetrics(
                scope=scope,
                dimension_value=normalized_dimension,
                window_start=window_start,
                window_end=window_end,
                total_attempts=len(bucket),
                failed_attempts=len(failed_samples),
                total_amount_minor=sum(sample.amount_minor for sample in bucket),
                failed_amount_minor=sum(sample.amount_minor for sample in failed_samples),
            ),
        )

    return PaymentWindowSeries(
        baseline_windows=tuple(windows[:-1]),
        current_window=windows[-1],
    )


async def load_payment_method_window_series(
    session: AsyncSession,
    *,
    payment_method: str,
    currency: str,
    current_window_end: datetime,
    window_size: timedelta = DEFAULT_WINDOW_SIZE,
    baseline_window_count: int = DEFAULT_BASELINE_WINDOW_COUNT,
) -> PaymentWindowSeries:
    normalized_method = payment_method.strip().casefold()
    normalized_currency = currency.strip().upper()

    if not normalized_method:
        raise ValueError("Payment method cannot be empty")

    if len(normalized_currency) != 3:
        raise ValueError("Currency must be a three-letter code")

    _validate_window_configuration(
        window_size,
        baseline_window_count,
    )

    series_start = current_window_end - (window_size * (baseline_window_count + 1))

    ranked_outcomes = (
        select(
            PaymentStateTransition.payment_attempt_id.label(
                "payment_attempt_id",
            ),
            PaymentStateTransition.event_created_at.label(
                "occurred_at",
            ),
            PaymentStateTransition.incoming_state.label(
                "incoming_state",
            ),
            PaymentAttempt.amount_minor.label(
                "amount_minor",
            ),
            func.row_number()
            .over(
                partition_by=(PaymentStateTransition.payment_attempt_id),
                order_by=(
                    PaymentStateTransition.event_created_at,
                    PaymentStateTransition.processed_at,
                    PaymentStateTransition.id,
                ),
            )
            .label("event_rank"),
        )
        .join(
            PaymentAttempt,
            PaymentAttempt.id == PaymentStateTransition.payment_attempt_id,
        )
        .where(
            PaymentStateTransition.outcome == "applied",
            PaymentStateTransition.incoming_state.in_(
                SUPPORTED_PAYMENT_OUTCOMES,
            ),
            func.upper(PaymentAttempt.currency) == normalized_currency,
            func.lower(
                func.coalesce(
                    PaymentAttempt.method,
                    "unknown",
                ),
            )
            == normalized_method,
        )
        .subquery("ranked_payment_outcomes")
    )

    statement = (
        select(
            ranked_outcomes.c.occurred_at,
            ranked_outcomes.c.amount_minor,
            ranked_outcomes.c.incoming_state,
        )
        .where(
            ranked_outcomes.c.event_rank == 1,
            ranked_outcomes.c.occurred_at >= series_start,
            ranked_outcomes.c.occurred_at < current_window_end,
        )
        .order_by(
            ranked_outcomes.c.occurred_at,
            ranked_outcomes.c.payment_attempt_id,
        )
    )

    result = await session.execute(statement)

    samples = [
        PaymentOutcomeSample(
            occurred_at=cast(datetime, row.occurred_at),
            amount_minor=int(row.amount_minor),
            failed=str(row.incoming_state) == "failed",
        )
        for row in result
    ]

    return build_payment_window_series(
        samples,
        scope=IncidentScope.PAYMENT_METHOD,
        dimension_value=normalized_method,
        current_window_end=current_window_end,
        window_size=window_size,
        baseline_window_count=baseline_window_count,
    )
