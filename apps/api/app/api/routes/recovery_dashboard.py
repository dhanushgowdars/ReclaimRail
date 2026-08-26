from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.database import get_database_session
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
