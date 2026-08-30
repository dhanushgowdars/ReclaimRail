from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_database_session
from app.services.recovery_case_detail_service import (
    RecoveryCaseDetailNotFoundError,
    load_recovery_case_detail,
)

DatabaseSessionDependency = Annotated[
    AsyncSession,
    Depends(get_database_session),
]

router = APIRouter(
    prefix="/recovery/dashboard",
    tags=["recovery-dashboard"],
)


class ResponseModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class RecoveryCaseSnapshotResponse(ResponseModel):
    recovery_case_id: UUID
    status: str
    amount_minor: int = Field(gt=0)
    currency: str = Field(min_length=3, max_length=3)
    payment_method: str | None
    source_incident_id: UUID | None
    recovery_attempt_count: int = Field(ge=0)
    active_payment_link_id: str | None
    next_action_at: datetime | None
    late_authorization_detected_at: datetime | None
    opened_at: datetime
    recovered_at: datetime | None
    closed_at: datetime | None
    close_reason: str | None


class PaymentLifecycleSnapshotResponse(ResponseModel):
    payment_attempt_id: UUID
    current_state: str
    state_version: int = Field(ge=0)
    amount_minor: int = Field(ge=0)
    currency: str = Field(min_length=3, max_length=3)
    payment_method: str | None
    error_code: str | None
    error_source: str | None
    error_step: str | None
    error_reason: str | None
    recovery_eligible: bool
    recovery_stopped_at: datetime | None
    recovery_stop_reason: str | None
    late_authorization_detected_at: datetime | None


class RecoveryAiTraceResponse(ResponseModel):
    root_cause_category: str | None
    recoverability_assessment: str | None
    confidence: float | None = Field(default=None, ge=0, le=1)
    recommended_action: str | None
    evidence_references: list[str]
    evidence_codes: list[str]
    evidence_tool_names: list[str]
    input_token_count: int | None = Field(default=None, ge=0)
    output_token_count: int | None = Field(default=None, ge=0)
    fallback_used: bool | None
    fallback_reason: str | None


class RecoveryAgentRunSummaryResponse(ResponseModel):
    agent_run_id: UUID
    run_number: int = Field(ge=1)
    status: str
    planner_provider: str
    model_name: str | None
    prompt_version: str
    reasoning_summary: str | None
    proposed_action_count: int = Field(ge=0)
    failure_code: str | None
    started_at: datetime
    completed_at: datetime | None
    ai_trace: RecoveryAiTraceResponse


class RecoveryActionSummaryResponse(ResponseModel):
    recovery_action_id: UUID
    agent_run_id: UUID
    sequence_number: int = Field(ge=1)
    action_type: str
    status: str
    proposal_reason: str
    amount_minor: int | None
    currency: str | None
    channel: str | None
    target_payment_method: str | None
    execute_after: datetime | None
    policy_outcome: str
    policy_guardrails: list[str]
    policy_explanation: str
    policy_version: str
    policy_evaluated_at: datetime
    execution_attempt_count: int = Field(ge=0)
    provider_action_id: str | None
    provider_action_status: str | None
    provider_action_url: str | None
    provider_action_expires_at: datetime | None
    started_at: datetime | None
    completed_at: datetime | None


class RecoveryApprovalSummaryResponse(ResponseModel):
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


class RecoveryOutcomeSummaryResponse(ResponseModel):
    recovery_outcome_id: UUID
    status: str
    attribution: str
    recovery_action_id: UUID | None
    payment_link_id: str | None
    gross_recovered_minor: int = Field(ge=0)
    reversed_minor: int = Field(ge=0)
    duplicate_collection_prevented_minor: int = Field(ge=0)
    evidence_event_count: int = Field(ge=0)
    occurred_at: datetime
    updated_at: datetime


class PaymentTransitionSummaryResponse(ResponseModel):
    event_type: str
    previous_state: str
    incoming_state: str
    resulting_state: str
    resulting_version: int = Field(ge=0)
    outcome: str
    reason: str
    late_authorization: bool
    stop_recovery: bool
    event_created_at: datetime
    processed_at: datetime


class RecoveryAuditEventSummaryResponse(ResponseModel):
    sequence_number: int = Field(ge=1)
    event_type: str
    actor_type: str
    recovery_action_id: UUID | None
    previous_event_hash: str | None
    event_hash: str = Field(min_length=64, max_length=64)
    hash_algorithm: str
    occurred_at: datetime


class RecoveryAuditChainSummaryResponse(ResponseModel):
    valid: bool
    reason: str
    checked_event_count: int = Field(ge=0)
    broken_sequence_number: int | None
    total_event_count: int = Field(ge=0)
    timeline_truncated: bool
    events: list[RecoveryAuditEventSummaryResponse]


class RecoveryCaseDetailResponse(ResponseModel):
    recovery_case: RecoveryCaseSnapshotResponse
    payment_lifecycle: PaymentLifecycleSnapshotResponse
    agent_runs: list[RecoveryAgentRunSummaryResponse]
    actions: list[RecoveryActionSummaryResponse]
    approvals: list[RecoveryApprovalSummaryResponse]
    outcome: RecoveryOutcomeSummaryResponse | None
    payment_transitions: list[PaymentTransitionSummaryResponse]
    audit_chain: RecoveryAuditChainSummaryResponse


@router.get(
    "/cases/{recovery_case_id}",
    response_model=RecoveryCaseDetailResponse,
    summary="Read one PII-safe recovery case decision and audit timeline",
)
async def get_recovery_case_detail(
    recovery_case_id: UUID,
    session: DatabaseSessionDependency,
) -> RecoveryCaseDetailResponse:
    try:
        detail = await load_recovery_case_detail(
            session,
            recovery_case_id=recovery_case_id,
        )
    except RecoveryCaseDetailNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Recovery case not found",
        ) from error

    return RecoveryCaseDetailResponse.model_validate(detail)
