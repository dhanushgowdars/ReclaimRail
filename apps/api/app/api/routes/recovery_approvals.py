import secrets
from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.database import get_database_session
from app.db.models.recovery import RecoveryApproval, RecoveryApprovalStatus
from app.services.recovery_approval_service import (
    RecoveryApprovalConflictError,
    RecoveryApprovalDecision,
    RecoveryApprovalDecisionDisposition,
    RecoveryApprovalNotFoundError,
    RecoveryApprovalStateError,
    decide_recovery_approval,
    list_recovery_approvals,
)

DatabaseSessionDependency = Annotated[AsyncSession, Depends(get_database_session)]
SettingsDependency = Annotated[Settings, Depends(get_settings)]
OperatorTokenHeader = Annotated[
    str | None,
    Header(alias="X-ReclaimRail-Operator-Token"),
]

router = APIRouter(
    prefix="/recovery/approvals",
    tags=["recovery-approvals"],
)


class RecoveryApprovalResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    approval_id: UUID = Field(validation_alias="id")
    recovery_case_id: UUID
    recovery_action_id: UUID
    status: RecoveryApprovalStatus
    request_reason: str
    amount_minor: int = Field(gt=0)
    currency: str = Field(min_length=3, max_length=3)
    threshold_minor: int = Field(gt=0)
    requested_at: datetime
    expires_at: datetime
    decided_at: datetime | None
    decided_by: str | None
    decision_reason: str | None
    version: int = Field(ge=0)


class RecoveryApprovalListResponse(BaseModel):
    approvals: list[RecoveryApprovalResponse]


class RecoveryApprovalDecisionRequest(BaseModel):
    decision: RecoveryApprovalDecision
    reviewer_id: str = Field(min_length=1, max_length=128)
    reason: str = Field(min_length=3, max_length=1000)
    expected_version: int = Field(ge=0)


class RecoveryApprovalDecisionResponse(BaseModel):
    disposition: RecoveryApprovalDecisionDisposition
    approval: RecoveryApprovalResponse


def require_operator_access(settings: Settings, provided_token: str | None) -> None:
    configured_token = settings.recovery_operator_access_token
    if configured_token is None or not configured_token.get_secret_value().strip():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Recovery operator access is not configured",
        )
    if provided_token is None or not secrets.compare_digest(
        provided_token,
        configured_token.get_secret_value(),
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Recovery operator access denied",
        )


def build_approval_response(approval: RecoveryApproval) -> RecoveryApprovalResponse:
    return RecoveryApprovalResponse.model_validate(approval)


@router.get(
    "",
    response_model=RecoveryApprovalListResponse,
    summary="List PII-safe recovery approvals for the operator queue",
)
async def list_recovery_approvals_endpoint(
    session: DatabaseSessionDependency,
    settings: SettingsDependency,
    approval_status: Annotated[
        RecoveryApprovalStatus | None,
        Query(alias="status"),
    ] = RecoveryApprovalStatus.PENDING,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    access_token: OperatorTokenHeader = None,
) -> RecoveryApprovalListResponse:
    require_operator_access(settings, access_token)
    approvals = await list_recovery_approvals(
        session,
        status=approval_status,
        limit=limit,
    )
    return RecoveryApprovalListResponse(
        approvals=[build_approval_response(approval) for approval in approvals],
    )


@router.post(
    "/{approval_id}/decision",
    response_model=RecoveryApprovalDecisionResponse,
    summary="Approve or reject one policy-gated recovery action",
)
async def decide_recovery_approval_endpoint(
    approval_id: UUID,
    request: RecoveryApprovalDecisionRequest,
    response: Response,
    session: DatabaseSessionDependency,
    settings: SettingsDependency,
    access_token: OperatorTokenHeader = None,
) -> RecoveryApprovalDecisionResponse:
    require_operator_access(settings, access_token)
    try:
        async with session.begin():
            result = await decide_recovery_approval(
                session,
                approval_id=approval_id,
                decision=request.decision,
                reviewer_id=request.reviewer_id,
                reason=request.reason,
                expected_version=request.expected_version,
                decided_at=datetime.now(UTC),
            )
    except RecoveryApprovalNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Recovery approval not found",
        ) from error
    except RecoveryApprovalConflictError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(error),
        ) from error
    except RecoveryApprovalStateError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(error),
        ) from error

    if result.disposition is RecoveryApprovalDecisionDisposition.EXPIRED:
        response.status_code = status.HTTP_409_CONFLICT
    return RecoveryApprovalDecisionResponse(
        disposition=result.disposition,
        approval=build_approval_response(result.approval),
    )
