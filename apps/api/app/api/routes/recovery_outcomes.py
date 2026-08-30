from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.database import get_database_session
from app.services.recovery_outcome_feed_service import (
    MAX_OUTCOME_FEED_LIMIT,
    MAX_OUTCOME_FEED_OFFSET,
    RecoveryOutcomeFeedFilters,
    RecoveryOutcomeFeedItem,
    load_recovery_outcome_feed,
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
OutcomeStatusQuery = Annotated[
    list[str] | None,
    Query(alias="status"),
]
OutcomeLimitQuery = Annotated[
    int,
    Query(
        ge=1,
        le=MAX_OUTCOME_FEED_LIMIT,
    ),
]
OutcomeOffsetQuery = Annotated[
    int,
    Query(
        ge=0,
        le=MAX_OUTCOME_FEED_OFFSET,
    ),
]

router = APIRouter(
    prefix="/recovery/dashboard",
    tags=["recovery-dashboard"],
)


class RecoveryOutcomeFeedItemResponse(BaseModel):
    recovery_outcome_id: UUID
    recovery_case_id: UUID
    recovery_action_id: UUID | None
    status: str
    attribution: str
    original_amount_minor: int = Field(gt=0)
    gross_recovered_minor: int = Field(ge=0)
    reversed_minor: int = Field(ge=0)
    duplicate_collection_prevented_minor: int = Field(ge=0)
    currency: str = Field(min_length=3, max_length=3)
    payment_link_id: str | None
    evidence_event_count: int = Field(ge=0)
    occurred_at: datetime
    updated_at: datetime


class RecoveryOutcomeFeedResponse(BaseModel):
    items: list[RecoveryOutcomeFeedItemResponse]
    total_count: int = Field(ge=0)
    limit: int = Field(ge=1, le=MAX_OUTCOME_FEED_LIMIT)
    offset: int = Field(ge=0, le=MAX_OUTCOME_FEED_OFFSET)


def to_recovery_outcome_feed_item_response(
    item: RecoveryOutcomeFeedItem,
) -> RecoveryOutcomeFeedItemResponse:
    return RecoveryOutcomeFeedItemResponse(
        recovery_outcome_id=item.recovery_outcome_id,
        recovery_case_id=item.recovery_case_id,
        recovery_action_id=item.recovery_action_id,
        status=item.status,
        attribution=item.attribution,
        original_amount_minor=item.original_amount_minor,
        gross_recovered_minor=item.gross_recovered_minor,
        reversed_minor=item.reversed_minor,
        duplicate_collection_prevented_minor=(item.duplicate_collection_prevented_minor),
        currency=item.currency,
        payment_link_id=item.payment_link_id,
        evidence_event_count=item.evidence_event_count,
        occurred_at=item.occurred_at,
        updated_at=item.updated_at,
    )


@router.get(
    "/outcomes",
    response_model=RecoveryOutcomeFeedResponse,
    summary="List verified recovery outcomes and duplicate-prevention evidence",
)
async def list_recovery_outcomes(
    session: DatabaseSessionDependency,
    settings: SettingsDependency,
    currency: CurrencyQuery = None,
    status_filters: OutcomeStatusQuery = None,
    limit: OutcomeLimitQuery = 25,
    offset: OutcomeOffsetQuery = 0,
) -> RecoveryOutcomeFeedResponse:
    try:
        filters = RecoveryOutcomeFeedFilters(
            currency=currency or settings.incident_currency,
            statuses=(tuple(status_filters) if status_filters is not None else ()),
            limit=limit,
            offset=offset,
        )
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(error),
        ) from error

    page = await load_recovery_outcome_feed(
        session,
        filters=filters,
    )

    return RecoveryOutcomeFeedResponse(
        items=[to_recovery_outcome_feed_item_response(item) for item in page.items],
        total_count=page.total_count,
        limit=page.limit,
        offset=page.offset,
    )
