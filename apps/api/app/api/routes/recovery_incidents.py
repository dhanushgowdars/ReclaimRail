import secrets
from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.database import get_database_session
from app.domain.incidents import IncidentSeverity
from app.services.incident_test_drill_service import create_test_mode_incident_drill
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
TestDrillTokenHeader = Annotated[str | None, Header(alias="X-ReclaimRail-Lab-Token")]

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


class TestModeIncidentDrillRequest(BaseModel):
    payment_method: str = Field(pattern="^(upi|card|netbanking|wallet)$")
    severity: IncidentSeverity = IncidentSeverity.HIGH
    duration_minutes: int = Field(default=10, ge=1, le=60)


class TestModeIncidentDrillResponse(BaseModel):
    incident_id: UUID
    label: str
    severity: IncidentSeverity
    payment_method: str
    expires_at: datetime


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


@router.post(
    "/incidents/test-drill",
    response_model=TestModeIncidentDrillResponse,
    status_code=status.HTTP_201_CREATED,
)
async def start_test_mode_incident_drill(
    request: TestModeIncidentDrillRequest,
    session: DatabaseSessionDependency,
    settings: SettingsDependency,
    access_token: TestDrillTokenHeader = None,
) -> TestModeIncidentDrillResponse:
    if settings.app_env == "production" or not settings.incident_test_drill_enabled:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Test Mode incident drills are disabled"
        )
    configured_token = settings.payment_lab_access_token
    expected = configured_token.get_secret_value() if configured_token is not None else None
    if not expected or not access_token or not secrets.compare_digest(expected, access_token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid Test Mode access token"
        )
    incident = await create_test_mode_incident_drill(
        session,
        payment_method=request.payment_method,
        currency=settings.incident_currency,
        severity=request.severity,
        duration_minutes=request.duration_minutes,
    )
    await session.commit()
    expires_at = incident.current_window_end
    return TestModeIncidentDrillResponse(
        incident_id=incident.id,
        label="TEST MODE INCIDENT DRILL — not provider evidence",
        severity=request.severity,
        payment_method=request.payment_method,
        expires_at=expires_at,
    )
