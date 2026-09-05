from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.payment_lab import PaymentLabTokenHeader, require_payment_lab_access
from app.core.cache import get_redis_client
from app.core.config import Settings, get_settings
from app.core.database import get_database_session
from app.services.payment_lab_live_run_service import (
    PaymentLabLiveRunNotFoundError,
    PaymentLabVerifiedReplayNotFoundError,
    load_latest_verified_payment_lab_replay,
    load_payment_lab_live_run,
)
from app.services.worker_supervision_service import (
    WorkerHealthStatus,
    load_worker_fleet_health,
    responsible_worker_for_live_state,
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
    duration_milliseconds: int | None = Field(default=None, ge=0)
    detail: str


class PaymentLabPaymentEvidenceResponse(ResponseModel):
    payment_attempt_id: UUID
    provider_payment_id: str
    current_state: str
    failure_code: str | None
    failure_reason: str | None
    observed_at: datetime
    source: str | None = None


class RecoveryAiTraceResponse(ResponseModel):
    root_cause_category: str | None
    recoverability_assessment: str | None
    recommended_action: str | None
    operator_explanation: str | None
    evidence_references: list[str]
    evidence_citations: list[RecoveryAiEvidenceCitationResponse]
    evidence_codes: list[str]
    evidence_tool_names: list[str]
    input_token_count: int | None = Field(default=None, ge=0)
    output_token_count: int | None = Field(default=None, ge=0)
    fallback_used: bool | None
    fallback_reason: str | None
    reasoning_items: list[RecoveryAiReasoningItemResponse]
    alternatives_considered: list[RecoveryAiAlternativeResponse]
    known_uncertainties: list[str]


class RecoveryAiEvidenceCitationResponse(ResponseModel):
    reference: str
    label: str
    observations: list[str]


class RecoveryAiReasoningItemResponse(ResponseModel):
    evidence_references: list[str]
    interpretation: str
    action_impact: str


class RecoveryAiAlternativeResponse(ResponseModel):
    action_type: str
    disposition: str
    reason: str
    evidence_references: list[str]


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
    started_at: datetime | None
    completed_at: datetime | None
    ai_trace: RecoveryAiTraceResponse | None


class PaymentLabActionEvidenceResponse(ResponseModel):
    recovery_action_id: UUID
    sequence_number: int = Field(ge=1)
    action_type: str
    proposal_reason: str
    channel: str | None
    status: str
    policy_outcome: str
    policy_guardrails: list[str]
    policy_check_results: list[dict[str, str]]
    policy_explanation: str
    provider_action_id: str | None
    provider_action_status: str | None
    provider_action_url: str | None
    provider_action_expires_at: datetime | None
    completed_at: datetime | None


class PaymentLabApprovalEvidenceResponse(ResponseModel):
    approval_id: UUID
    recovery_action_id: UUID
    status: str
    request_reason: str
    amount_minor: int = Field(gt=0)
    currency: str = Field(min_length=3, max_length=3)
    threshold_minor: int | None = Field(default=None, gt=0)
    request_context: dict[str, object]
    requested_at: datetime
    expires_at: datetime
    decided_at: datetime | None
    decided_by: str | None
    decision_reason: str | None
    version: int = Field(ge=0)


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
    responsible_worker: str | None = None
    responsible_worker_status: str | None = None
    stalled_reason: str | None = None
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
    approval: PaymentLabApprovalEvidenceResponse | None
    outcome: PaymentLabOutcomeEvidenceResponse | None


@router.get(
    "/replays/latest",
    response_model=PaymentLabLiveRunResponse,
    summary="Read the latest completed Razorpay Test Mode replay",
)
async def get_latest_verified_payment_lab_replay(
    session: DatabaseSessionDependency,
    settings: SettingsDependency,
    access_token: PaymentLabTokenHeader = None,
) -> PaymentLabLiveRunResponse:
    require_payment_lab_access(settings, access_token)
    try:
        live_run = await load_latest_verified_payment_lab_replay(session)
    except PaymentLabVerifiedReplayNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No completed Razorpay Test Mode replay is available yet",
        ) from error
    return PaymentLabLiveRunResponse.model_validate(live_run)


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
    response_model = PaymentLabLiveRunResponse.model_validate(live_run)
    responsible_worker = responsible_worker_for_live_state(live_run.business_state)
    if responsible_worker is None:
        return response_model

    try:
        fleet = await load_worker_fleet_health(
            get_redis_client(),
            reference_time=datetime.now(UTC),
            delayed_after_seconds=settings.worker_delayed_after_seconds,
        )
    except Exception:
        return response_model.model_copy(
            update={
                "responsible_worker": responsible_worker.value,
                "responsible_worker_status": "unavailable",
                "stalled_reason": "Worker diagnostics are temporarily unavailable",
            },
        )

    worker_health = next(
        (worker for worker in fleet.workers if worker.name is responsible_worker),
        None,
    )
    if worker_health is None:
        return response_model.model_copy(
            update={
                "responsible_worker": responsible_worker.value,
                "responsible_worker_status": "unavailable",
                "stalled_reason": "Responsible worker heartbeat is unavailable",
            },
        )
    stalled_reason = None
    if worker_health.status not in {
        WorkerHealthStatus.HEALTHY,
        WorkerHealthStatus.STARTING,
    }:
        stalled_reason = (
            f"{responsible_worker.value} worker is {worker_health.status.value}; "
            "inspect /health/workers and local runtime logs"
        )
    return response_model.model_copy(
        update={
            "responsible_worker": responsible_worker.value,
            "responsible_worker_status": worker_health.status.value,
            "stalled_reason": stalled_reason,
        },
    )
