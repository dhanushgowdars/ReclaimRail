from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.database import get_database_session
from app.services.recovery_case_queue_service import (
    DEFAULT_QUEUE_STATUSES,
    MAX_QUEUE_LIMIT,
    MAX_QUEUE_OFFSET,
    RecoveryCaseQueueFilters,
    RecoveryCaseQueueItem,
    load_recovery_case_queue,
)
from app.services.recovery_dashboard_service import (
    load_recovery_dashboard_summary,
)

SettingsDependency = Annotated[Settings, Depends(get_settings)]
DatabaseSessionDependency = Annotated[
    AsyncSession,
    Depends(get_database_session),
]
CurrencyQuery = Annotated[
    str | None,
    Query(
        min_length=3,
        max_length=3,
        pattern=r"^[A-Za-z]{3}$",
    ),
]
QueueLimitQuery = Annotated[
    int,
    Query(
        ge=1,
        le=MAX_QUEUE_LIMIT,
    ),
]
QueueOffsetQuery = Annotated[
    int,
    Query(
        ge=0,
        le=MAX_QUEUE_OFFSET,
    ),
]
RecoveryCaseStatusQuery = Annotated[
    list[str] | None,
    Query(alias="status"),
]

router = APIRouter(
    prefix="/recovery/dashboard",
    tags=["recovery-dashboard"],
)


class RecoveryDashboardSummaryResponse(BaseModel):
    currency: str = Field(min_length=3, max_length=3)
    revenue_at_risk_minor: int = Field(ge=0)
    verified_recovered_minor: int = Field(ge=0)
    duplicate_collection_prevented_minor: int = Field(ge=0)
    active_incident_revenue_at_risk_minor: int = Field(ge=0)
    active_case_count: int = Field(ge=0)
    recovered_case_count: int = Field(ge=0)
    pending_outcome_count: int = Field(ge=0)
    open_incident_count: int = Field(ge=0)
    generated_at: datetime


class RecoveryCaseQueueItemResponse(BaseModel):
    recovery_case_id: UUID
    status: str
    amount_minor: int = Field(gt=0)
    currency: str = Field(min_length=3, max_length=3)
    payment_method: str | None
    source_incident_id: UUID | None
    recovery_attempt_count: int = Field(ge=0)
    next_action_at: datetime | None
    late_authorization_detected_at: datetime | None
    opened_at: datetime
    updated_at: datetime
    latest_action_type: str | None
    latest_action_status: str | None
    latest_action_policy_outcome: str | None
    outcome_status: str | None


class RecoveryCaseQueueResponse(BaseModel):
    items: list[RecoveryCaseQueueItemResponse]
    total_count: int = Field(ge=0)
    limit: int = Field(ge=1, le=MAX_QUEUE_LIMIT)
    offset: int = Field(ge=0, le=MAX_QUEUE_OFFSET)


@router.get(
    "/summary",
    response_model=RecoveryDashboardSummaryResponse,
    summary="Read verified merchant recovery metrics",
)
async def get_recovery_dashboard_summary(
    session: DatabaseSessionDependency,
    settings: SettingsDependency,
    currency: CurrencyQuery = None,
) -> RecoveryDashboardSummaryResponse:
    summary = await load_recovery_dashboard_summary(
        session,
        currency=currency or settings.incident_currency,
    )

    return RecoveryDashboardSummaryResponse(
        currency=summary.currency,
        revenue_at_risk_minor=summary.revenue_at_risk_minor,
        verified_recovered_minor=summary.verified_recovered_minor,
        duplicate_collection_prevented_minor=(summary.duplicate_collection_prevented_minor),
        active_incident_revenue_at_risk_minor=(summary.active_incident_revenue_at_risk_minor),
        active_case_count=summary.active_case_count,
        recovered_case_count=summary.recovered_case_count,
        pending_outcome_count=summary.pending_outcome_count,
        open_incident_count=summary.open_incident_count,
        generated_at=datetime.now(UTC),
    )


def to_recovery_case_queue_item_response(
    item: RecoveryCaseQueueItem,
) -> RecoveryCaseQueueItemResponse:
    return RecoveryCaseQueueItemResponse(
        recovery_case_id=item.recovery_case_id,
        status=item.status,
        amount_minor=item.amount_minor,
        currency=item.currency,
        payment_method=item.payment_method,
        source_incident_id=item.source_incident_id,
        recovery_attempt_count=item.recovery_attempt_count,
        next_action_at=item.next_action_at,
        late_authorization_detected_at=item.late_authorization_detected_at,
        opened_at=item.opened_at,
        updated_at=item.updated_at,
        latest_action_type=item.latest_action_type,
        latest_action_status=item.latest_action_status,
        latest_action_policy_outcome=item.latest_action_policy_outcome,
        outcome_status=item.outcome_status,
    )


@router.get(
    "/cases",
    response_model=RecoveryCaseQueueResponse,
    summary="List bounded recovery cases for merchant operations",
)
async def list_recovery_cases(
    session: DatabaseSessionDependency,
    settings: SettingsDependency,
    currency: CurrencyQuery = None,
    status_filters: RecoveryCaseStatusQuery = None,
    source_incident_id: UUID | None = None,
    limit: QueueLimitQuery = 25,
    offset: QueueOffsetQuery = 0,
) -> RecoveryCaseQueueResponse:
    try:
        filters = RecoveryCaseQueueFilters(
            currency=currency or settings.incident_currency,
            statuses=(
                tuple(status_filters) if status_filters is not None else DEFAULT_QUEUE_STATUSES
            ),
            source_incident_id=source_incident_id,
            limit=limit,
            offset=offset,
        )
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(error),
        ) from error

    page = await load_recovery_case_queue(
        session,
        filters=filters,
    )

    return RecoveryCaseQueueResponse(
        items=[to_recovery_case_queue_item_response(item) for item in page.items],
        total_count=page.total_count,
        limit=page.limit,
        offset=page.offset,
    )
