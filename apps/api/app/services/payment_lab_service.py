from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.payment_lab import (
    PaymentLabRun,
    PaymentLabRunMode,
    PaymentLabRunProvenance,
    PaymentLabRunStatus,
)
from app.integrations.razorpay.orders import (
    RazorpayOrder,
    RazorpayOrderProvider,
    RazorpayOrderProviderError,
    RazorpayOrderRequest,
    RazorpayOrderStatus,
)

ACTIVE_RUN_STATUSES = (
    PaymentLabRunStatus.CREATING.value,
    PaymentLabRunStatus.CHECKOUT_READY.value,
    PaymentLabRunStatus.PAYMENT_ATTEMPTED.value,
    PaymentLabRunStatus.RECOVERY_RUNNING.value,
)


@dataclass(frozen=True, slots=True)
class PaymentLabRunCreationResult:
    payment_lab_run_id: UUID
    client_request_id: UUID
    mode: PaymentLabRunMode
    provenance: PaymentLabRunProvenance
    amount_minor: int
    currency: str
    payment_method: str
    provider_order_id: str
    checkout_expires_at: datetime
    created: bool


class PaymentLabRunLimitError(RuntimeError):
    pass


class PaymentLabRunConflictError(RuntimeError):
    pass


class PaymentLabProviderError(RuntimeError):
    def __init__(self, *, retryable: bool) -> None:
        super().__init__("Test Mode order creation failed")
        self.retryable = retryable


def build_payment_lab_receipt(run_id: UUID) -> str:
    return f"rr_lab_{run_id.hex}"


def _validate_limits(
    *,
    amount_minor: int,
    minimum_amount_minor: int,
    maximum_amount_minor: int,
) -> None:
    if minimum_amount_minor > maximum_amount_minor:
        raise ValueError("Payment Lab amount limits are misconfigured")

    if amount_minor < minimum_amount_minor or amount_minor > maximum_amount_minor:
        raise ValueError(
            "Payment Lab amount is outside the configured bounds",
        )


def _matches_existing_request(
    run: PaymentLabRun,
    *,
    mode: PaymentLabRunMode,
    amount_minor: int,
    currency: str,
    payment_method: str,
) -> bool:
    return (
        run.mode == mode.value
        and run.amount_minor == amount_minor
        and run.currency == currency
        and run.payment_method == payment_method
    )


def _result_from_ready_run(
    run: PaymentLabRun,
    *,
    created: bool,
) -> PaymentLabRunCreationResult:
    if run.provider_order_id is None:
        raise RuntimeError("Checkout-ready Payment Lab run has no provider order")

    return PaymentLabRunCreationResult(
        payment_lab_run_id=run.id,
        client_request_id=run.client_request_id,
        mode=PaymentLabRunMode(run.mode),
        provenance=PaymentLabRunProvenance(run.provenance),
        amount_minor=run.amount_minor,
        currency=run.currency,
        payment_method=run.payment_method,
        provider_order_id=run.provider_order_id,
        checkout_expires_at=run.checkout_expires_at,
        created=created,
    )


async def _load_existing_run(
    session: AsyncSession,
    *,
    client_request_id: UUID,
) -> PaymentLabRun | None:
    result = await session.execute(
        select(PaymentLabRun).where(
            PaymentLabRun.client_request_id == client_request_id,
        ),
    )
    return result.scalar_one_or_none()


async def _enforce_run_limits(
    session: AsyncSession,
    *,
    reference_time: datetime,
    hourly_run_limit: int,
    maximum_active_runs: int,
) -> None:
    hourly_result = await session.execute(
        select(func.count(PaymentLabRun.id)).where(
            PaymentLabRun.created_at >= reference_time - timedelta(hours=1),
        ),
    )
    hourly_count = int(hourly_result.scalar_one())

    if hourly_count >= hourly_run_limit:
        raise PaymentLabRunLimitError("Payment Lab hourly run limit reached")

    active_result = await session.execute(
        select(func.count(PaymentLabRun.id)).where(
            PaymentLabRun.status.in_(ACTIVE_RUN_STATUSES),
            PaymentLabRun.checkout_expires_at > reference_time,
        ),
    )
    active_count = int(active_result.scalar_one())

    if active_count >= maximum_active_runs:
        raise PaymentLabRunLimitError("Payment Lab active run limit reached")


def _validate_provider_order(
    order: RazorpayOrder,
    *,
    amount_minor: int,
    currency: str,
    receipt: str,
) -> None:
    if order.status is not RazorpayOrderStatus.CREATED:
        raise PaymentLabProviderError(retryable=False)

    if (
        order.amount_minor != amount_minor
        or order.amount_due_minor != amount_minor
        or order.amount_paid_minor != 0
        or order.currency != currency
        or order.receipt != receipt
    ):
        raise PaymentLabProviderError(retryable=False)


async def create_payment_lab_run(
    session: AsyncSession,
    *,
    provider: RazorpayOrderProvider,
    client_request_id: UUID,
    mode: PaymentLabRunMode,
    amount_minor: int,
    currency: str,
    payment_method: str,
    reference_time: datetime,
    minimum_amount_minor: int,
    maximum_amount_minor: int,
    hourly_run_limit: int,
    maximum_active_runs: int,
    checkout_timeout_seconds: int,
) -> PaymentLabRunCreationResult:
    if reference_time.tzinfo is None or reference_time.utcoffset() is None:
        raise ValueError("Payment Lab reference time must be timezone-aware")

    normalized_currency = currency.strip().upper()
    normalized_method = payment_method.strip().lower()

    if normalized_currency != "INR":
        raise ValueError("Payment Lab currently supports INR only")

    if normalized_method not in {"upi", "card", "netbanking", "wallet"}:
        raise ValueError("Payment Lab payment method is invalid")

    _validate_limits(
        amount_minor=amount_minor,
        minimum_amount_minor=minimum_amount_minor,
        maximum_amount_minor=maximum_amount_minor,
    )

    existing = await _load_existing_run(
        session,
        client_request_id=client_request_id,
    )

    if existing is not None:
        if not _matches_existing_request(
            existing,
            mode=mode,
            amount_minor=amount_minor,
            currency=normalized_currency,
            payment_method=normalized_method,
        ):
            raise PaymentLabRunConflictError(
                "Client request ID was already used with different inputs",
            )

        if existing.status == PaymentLabRunStatus.CHECKOUT_READY.value:
            return _result_from_ready_run(existing, created=False)

        raise PaymentLabRunConflictError(
            "Client request ID is already in progress or previously failed",
        )

    await _enforce_run_limits(
        session,
        reference_time=reference_time,
        hourly_run_limit=hourly_run_limit,
        maximum_active_runs=maximum_active_runs,
    )

    run_id = uuid4()
    receipt = build_payment_lab_receipt(run_id)
    checkout_expires_at = reference_time + timedelta(
        seconds=checkout_timeout_seconds,
    )
    run = PaymentLabRun(
        id=run_id,
        client_request_id=client_request_id,
        mode=mode.value,
        provenance=PaymentLabRunProvenance.RAZORPAY_TEST.value,
        status=PaymentLabRunStatus.CREATING.value,
        amount_minor=amount_minor,
        currency=normalized_currency,
        payment_method=normalized_method,
        receipt=receipt,
        checkout_expires_at=checkout_expires_at,
        created_at=reference_time,
        updated_at=reference_time,
    )

    try:
        session.add(run)
        await session.commit()
    except IntegrityError as error:
        await session.rollback()
        raise PaymentLabRunConflictError(
            "Payment Lab request was submitted concurrently",
        ) from error
    except Exception:
        await session.rollback()
        raise

    request = RazorpayOrderRequest(
        amount_minor=amount_minor,
        currency=normalized_currency,
        receipt=receipt,
        notes={
            "reclaimrail_run_id": str(run_id),
            "provenance": PaymentLabRunProvenance.RAZORPAY_TEST.value,
        },
    )

    try:
        order = await provider.create_order(request)
        _validate_provider_order(
            order,
            amount_minor=amount_minor,
            currency=normalized_currency,
            receipt=receipt,
        )
    except (RazorpayOrderProviderError, PaymentLabProviderError) as error:
        retryable = isinstance(error, RazorpayOrderProviderError) and error.retryable
        run.status = PaymentLabRunStatus.PROVIDER_FAILED.value
        run.failure_code = "provider_retryable" if retryable else "provider_rejected"
        run.updated_at = datetime.now(UTC)
        run.version = (run.version or 0) + 1

        try:
            await session.commit()
        except Exception:
            await session.rollback()
            raise

        raise PaymentLabProviderError(retryable=retryable) from error

    run.status = PaymentLabRunStatus.CHECKOUT_READY.value
    run.provider_order_id = order.order_id
    run.provider_order_status = order.status.value
    run.provider_created_at = datetime.fromtimestamp(
        order.provider_created_at,
        tz=UTC,
    )
    run.updated_at = datetime.now(UTC)
    run.version = (run.version or 0) + 1

    try:
        await session.commit()
    except Exception:
        await session.rollback()
        raise

    return _result_from_ready_run(run, created=True)
