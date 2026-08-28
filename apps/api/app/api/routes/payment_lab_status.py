from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.payment_lab import PaymentLabTokenHeader, require_payment_lab_access
from app.core.config import Settings, get_settings
from app.core.database import get_database_session
from app.services.payment_lab_live_run_service import (
    PaymentLabLiveRunNotFoundError,
    load_payment_lab_live_run,
)

SettingsDependency = Annotated[Settings, Depends(get_settings)]
DatabaseSessionDependency = Annotated[
    AsyncSession,
    Depends(get_database_session),
]

router = APIRouter(prefix="/payment-lab", tags=["payment-lab"])


class ResponseModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class PaymentLabLiveStepResponse(ResponseModel):
    key: str
    label: str
    status: str
    occurred_at: datetime | None
    detail: str


class PaymentLabPaymentEvidenceResponse(ResponseModel):
    payment_attempt_id: UUID
    provider_payment_id: str
    current_state: str
    failure_code: str | None
    failure_reason: str | None
    observed_at: datetime


class PaymentLabAgentEvidenceResponse(ResponseModel):
    recovery_case_id: UUID
    recovery_case_status: str
    agent_run_id: UUID | None
    agent_run_status: str | None
    planner_provider: str | None
    model_name: str | None
    fallback_used: bool | None
    fallback_reason: str | None
    reasoning_summary: str | None
    proposed_action_count: int = Field(ge=0)
    completed_at: datetime | None


class PaymentLabActionEvidenceResponse(ResponseModel):
    recovery_action_id: UUID
    sequence_number: int = Field(ge=1)
    action_type: str
    status: str
    policy_outcome: str
    policy_guardrails: list[str]
    policy_explanation: str
    provider_action_id: str | None
    provider_action_status: str | None
    provider_action_url: str | None
    provider_action_expires_at: datetime | None
    completed_at: datetime | None


class PaymentLabOutcomeEvidenceResponse(ResponseModel):
    recovery_outcome_id: UUID
    status: str
    attribution: str
    gross_recovered_minor: int = Field(ge=0)
    duplicate_collection_prevented_minor: int = Field(ge=0)
    evidence_event_count: int = Field(ge=0)
    occurred_at: datetime


class PaymentLabLiveRunResponse(ResponseModel):
    payment_lab_run_id: UUID
    client_request_id: UUID
    mode: str
    provenance: str
    persisted_status: str
    business_state: str
    state_label: str
    current_stage: str
    active_step_key: str | None
    waiting_reason: str | None
    automation_complete: bool
    financial_outcome_terminal: bool
    terminal: bool
    poll_after_milliseconds: int | None
    amount_minor: int = Field(gt=0)
    currency: str = Field(min_length=3, max_length=3)
    payment_method: str
    provider_order_id: str | None
    provider_order_status: str | None
    failure_code: str | None
    checkout_expires_at: datetime
    created_at: datetime
    updated_at: datetime
    steps: list[PaymentLabLiveStepResponse]
    payment: PaymentLabPaymentEvidenceResponse | None
    agent: PaymentLabAgentEvidenceResponse | None
    actions: list[PaymentLabActionEvidenceResponse]
    outcome: PaymentLabOutcomeEvidenceResponse | None


@router.get(
    "/runs/{payment_lab_run_id}",
    response_model=PaymentLabLiveRunResponse,
    summary="Read one provider-backed Payment Lab run",
)
async def get_payment_lab_live_run(
    payment_lab_run_id: UUID,
    session: DatabaseSessionDependency,
    settings: SettingsDependency,
    access_token: PaymentLabTokenHeader = None,
) -> PaymentLabLiveRunResponse:
    require_payment_lab_access(settings, access_token)
    try:
        live_run = await load_payment_lab_live_run(
            session,
            payment_lab_run_id=payment_lab_run_id,
        )
    except PaymentLabLiveRunNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Payment Lab run not found",
        ) from error
    return PaymentLabLiveRunResponse.model_validate(live_run)
