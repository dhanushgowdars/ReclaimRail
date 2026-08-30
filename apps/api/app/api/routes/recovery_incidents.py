from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.database import get_database_session
from app.services.recovery_incident_feed_service import (
    MAX_ACTIVE_INCIDENTS,
    RecoveryIncidentFeedItem,
    load_active_recovery_incidents,
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
IncidentLimitQuery = Annotated[
    int,
    Query(
        ge=1,
        le=MAX_ACTIVE_INCIDENTS,
    ),
]

router = APIRouter(
    prefix="/recovery/dashboard",
    tags=["recovery-dashboard"],
)


class RecoveryIncidentFeedItemResponse(BaseModel):
    incident_id: UUID
    status: str
    severity: str
    scope: str
    dimension_value: str
    currency: str = Field(min_length=3, max_length=3)
    revenue_at_risk_minor: int = Field(ge=0)
    failure_rate: float = Field(ge=0, le=1)
    baseline_failure_rate: float = Field(ge=0, le=1)
    absolute_uplift: float = Field(ge=0)
    rate_multiplier: float | None = Field(default=None, ge=0)
    confidence: float = Field(ge=0, le=1)
    occurrence_count: int = Field(ge=1)
    reason_codes: list[str]
    first_detected_at: datetime
    last_detected_at: datetime


def to_recovery_incident_feed_item_response(
    item: RecoveryIncidentFeedItem,
) -> RecoveryIncidentFeedItemResponse:
    return RecoveryIncidentFeedItemResponse(
        incident_id=item.incident_id,
        status=item.status,
        severity=item.severity,
        scope=item.scope,
        dimension_value=item.dimension_value,
        currency=item.currency,
        revenue_at_risk_minor=item.revenue_at_risk_minor,
        failure_rate=item.failure_rate,
        baseline_failure_rate=item.baseline_failure_rate,
        absolute_uplift=item.absolute_uplift,
        rate_multiplier=item.rate_multiplier,
        confidence=item.confidence,
        occurrence_count=item.occurrence_count,
        reason_codes=list(item.reason_codes),
        first_detected_at=item.first_detected_at,
        last_detected_at=item.last_detected_at,
    )


@router.get(
    "/incidents",
    response_model=list[RecoveryIncidentFeedItemResponse],
    summary="List active payment-rail incidents affecting recovery decisions",
)
async def list_active_recovery_incidents(
    session: DatabaseSessionDependency,
    settings: SettingsDependency,
    currency: CurrencyQuery = None,
    limit: IncidentLimitQuery = 5,
) -> list[RecoveryIncidentFeedItemResponse]:
    try:
        incidents = await load_active_recovery_incidents(
            session,
            currency=currency or settings.incident_currency,
            limit=limit,
        )
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(error),
        ) from error

    return [to_recovery_incident_feed_item_response(item) for item in incidents]
