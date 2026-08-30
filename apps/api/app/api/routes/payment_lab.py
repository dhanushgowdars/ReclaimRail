import secrets
from datetime import UTC, datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Response, status
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.database import get_database_session
from app.db.models.payment_lab import (
    PaymentLabRunMode,
    PaymentLabRunProvenance,
)
from app.integrations.razorpay.orders import create_razorpay_order_provider
from app.services.payment_lab_service import (
    PaymentLabProviderError,
    PaymentLabRunConflictError,
    PaymentLabRunCreationResult,
    PaymentLabRunLimitError,
    create_payment_lab_run,
)

SettingsDependency = Annotated[Settings, Depends(get_settings)]
DatabaseSessionDependency = Annotated[
    AsyncSession,
    Depends(get_database_session),
]
PaymentLabTokenHeader = Annotated[
    str | None,
    Header(alias="X-ReclaimRail-Lab-Token"),
]

router = APIRouter(
    prefix="/payment-lab",
    tags=["payment-lab"],
)


class CreatePaymentLabRunRequest(BaseModel):
    client_request_id: UUID
    mode: PaymentLabRunMode
    amount_minor: int | None = Field(default=None, ge=10, le=100_000_000)
    payment_method: Literal["upi", "card", "netbanking", "wallet"] | None = None

    @model_validator(mode="after")
    def validate_mode_inputs(self) -> "CreatePaymentLabRunRequest":
        if self.mode is PaymentLabRunMode.GUIDED:
            if self.amount_minor is not None or self.payment_method is not None:
                raise ValueError("Guided runs use the locked amount and payment method")
        elif self.mode is PaymentLabRunMode.CUSTOM:
            if self.amount_minor is None or self.payment_method is None:
                raise ValueError("Custom runs require amount and payment method")
        else:
            raise ValueError("Replay runs use the verified replay endpoint")

        return self


class PaymentLabCheckoutResponse(BaseModel):
    key_id: str
    order_id: str
    amount_minor: int = Field(gt=0)
    currency: str = Field(min_length=3, max_length=3)
    name: str
    description: str
    timeout_seconds: int = Field(ge=60, le=1800)
    theme_color: str
    payment_method_hint: str


class PaymentLabRunResponse(BaseModel):
    payment_lab_run_id: UUID
    client_request_id: UUID
    mode: PaymentLabRunMode
    provenance: PaymentLabRunProvenance
    status: Literal["checkout_ready"]
    test_mode: Literal[True]
    checkout_expires_at: datetime
    checkout: PaymentLabCheckoutResponse


def require_payment_lab_access(
    settings: Settings,
    provided_token: str | None,
) -> None:
    configured_token = settings.payment_lab_access_token

    if configured_token is None or not configured_token.get_secret_value().strip():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Payment Lab access is not configured",
        )

    if provided_token is None or not secrets.compare_digest(
        provided_token,
        configured_token.get_secret_value(),
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Payment Lab access denied",
        )


def resolve_payment_lab_inputs(
    request: CreatePaymentLabRunRequest,
    settings: Settings,
) -> tuple[int, str]:
    if request.mode is PaymentLabRunMode.GUIDED:
        return settings.payment_lab_guided_amount_minor, "netbanking"

    if request.amount_minor is None or request.payment_method is None:
        raise RuntimeError("Validated custom run is missing required inputs")

    return request.amount_minor, request.payment_method


def build_payment_lab_response(
    result: PaymentLabRunCreationResult,
    *,
    checkout_key_id: str,
    timeout_seconds: int,
) -> PaymentLabRunResponse:
    return PaymentLabRunResponse(
        payment_lab_run_id=result.payment_lab_run_id,
        client_request_id=result.client_request_id,
        mode=result.mode,
        provenance=result.provenance,
        status="checkout_ready",
        test_mode=True,
        checkout_expires_at=result.checkout_expires_at,
        checkout=PaymentLabCheckoutResponse(
            key_id=checkout_key_id,
            order_id=result.provider_order_id,
            amount_minor=result.amount_minor,
            currency=result.currency,
            name="ReclaimRail Payment Lab",
            description="Razorpay Test Mode recovery scenario",
            timeout_seconds=timeout_seconds,
            theme_color="#0B5FFF",
            payment_method_hint=result.payment_method,
        ),
    )


@router.post(
    "/runs",
    response_model=PaymentLabRunResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a protected Razorpay Test Mode recovery run",
)
async def create_payment_lab_run_endpoint(
    request: CreatePaymentLabRunRequest,
    response: Response,
    session: DatabaseSessionDependency,
    settings: SettingsDependency,
    access_token: PaymentLabTokenHeader = None,
) -> PaymentLabRunResponse:
    require_payment_lab_access(settings, access_token)

    provider = create_razorpay_order_provider(settings)

    if provider is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Razorpay Test Mode Orders are unavailable",
        )

    amount_minor, payment_method = resolve_payment_lab_inputs(
        request,
        settings,
    )

    try:
        result = await create_payment_lab_run(
            session,
            provider=provider,
            client_request_id=request.client_request_id,
            mode=request.mode,
            amount_minor=amount_minor,
            currency="INR",
            payment_method=payment_method,
            reference_time=datetime.now(UTC),
            minimum_amount_minor=settings.payment_lab_min_amount_minor,
            maximum_amount_minor=settings.payment_lab_max_amount_minor,
            hourly_run_limit=settings.payment_lab_hourly_run_limit,
            maximum_active_runs=settings.payment_lab_max_active_runs,
            checkout_timeout_seconds=(settings.payment_lab_checkout_timeout_seconds),
        )
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(error),
        ) from error
    except PaymentLabRunLimitError as error:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=str(error),
        ) from error
    except PaymentLabRunConflictError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(error),
        ) from error
    except PaymentLabProviderError as error:
        raise HTTPException(
            status_code=(
                status.HTTP_503_SERVICE_UNAVAILABLE
                if error.retryable
                else status.HTTP_502_BAD_GATEWAY
            ),
            detail="Razorpay Test Mode order creation failed",
        ) from error

    if not result.created:
        response.status_code = status.HTTP_200_OK

    return build_payment_lab_response(
        result,
        checkout_key_id=provider.checkout_key_id,
        timeout_seconds=settings.payment_lab_checkout_timeout_seconds,
    )
