from collections.abc import AsyncIterator
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes import recovery_outcomes
from app.core.database import get_database_session
from app.main import app
from app.services.recovery_outcome_feed_service import (
    RecoveryOutcomeFeedItem,
    RecoveryOutcomeFeedPage,
)

OUTCOME_ID = UUID("10000000-0000-0000-0000-000000000001")
CASE_ID = UUID("20000000-0000-0000-0000-000000000001")
ACTION_ID = UUID("30000000-0000-0000-0000-000000000001")
NOW = datetime(2026, 8, 26, 8, 0, tzinfo=UTC)


async def override_database_session() -> AsyncIterator[AsyncSession]:
    yield MagicMock(spec=AsyncSession)


@pytest.fixture(autouse=True)
def database_session_override() -> AsyncIterator[None]:
    app.dependency_overrides[get_database_session] = override_database_session

    yield

    app.dependency_overrides.clear()


def build_page() -> RecoveryOutcomeFeedPage:
    return RecoveryOutcomeFeedPage(
        items=(
            RecoveryOutcomeFeedItem(
                recovery_outcome_id=OUTCOME_ID,
                recovery_case_id=CASE_ID,
                recovery_action_id=ACTION_ID,
                status="recovered",
                attribution="direct_payment_link",
                original_amount_minor=349_900,
                gross_recovered_minor=349_900,
                reversed_minor=0,
                duplicate_collection_prevented_minor=0,
                currency="INR",
                payment_link_id="plink_demo",
                evidence_event_count=2,
                occurred_at=NOW,
                updated_at=NOW,
            ),
        ),
        total_count=1,
        limit=25,
        offset=0,
    )


def test_lists_verified_pii_safe_recovery_outcomes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    load_outcomes = AsyncMock(return_value=build_page())
    monkeypatch.setattr(
        recovery_outcomes,
        "load_recovery_outcome_feed",
        load_outcomes,
    )

    with TestClient(app) as client:
        response = client.get("/recovery/dashboard/outcomes")

    assert response.status_code == 200
    assert response.json() == {
        "items": [
            {
                "recovery_outcome_id": str(OUTCOME_ID),
                "recovery_case_id": str(CASE_ID),
                "recovery_action_id": str(ACTION_ID),
                "status": "recovered",
                "attribution": "direct_payment_link",
                "original_amount_minor": 349_900,
                "gross_recovered_minor": 349_900,
                "reversed_minor": 0,
                "duplicate_collection_prevented_minor": 0,
                "currency": "INR",
                "payment_link_id": "plink_demo",
                "evidence_event_count": 2,
                "occurred_at": "2026-08-26T08:00:00Z",
                "updated_at": "2026-08-26T08:00:00Z",
            },
        ],
        "total_count": 1,
        "limit": 25,
        "offset": 0,
    }
    assert "email" not in response.text
    assert "contact" not in response.text
    assert load_outcomes.await_args.kwargs["filters"].currency == "INR"


def test_accepts_status_currency_and_pagination_filters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    load_outcomes = AsyncMock(
        return_value=RecoveryOutcomeFeedPage(
            items=(),
            total_count=0,
            limit=10,
            offset=25,
        ),
    )
    monkeypatch.setattr(
        recovery_outcomes,
        "load_recovery_outcome_feed",
        load_outcomes,
    )

    with TestClient(app) as client:
        response = client.get(
            "/recovery/dashboard/outcomes",
            params=[
                ("currency", "usd"),
                ("status", "recovered"),
                ("status", "reversed"),
                ("limit", "10"),
                ("offset", "25"),
            ],
        )

    assert response.status_code == 200
    assert response.json()["items"] == []

    filters = load_outcomes.await_args.kwargs["filters"]
    assert filters.currency == "USD"
    assert filters.statuses == ("recovered", "reversed")
    assert filters.limit == 10
    assert filters.offset == 25


def test_rejects_invalid_outcome_status_before_querying(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    load_outcomes = AsyncMock()
    monkeypatch.setattr(
        recovery_outcomes,
        "load_recovery_outcome_feed",
        load_outcomes,
    )

    with TestClient(app) as client:
        response = client.get(
            "/recovery/dashboard/outcomes",
            params={"status": "unknown"},
        )

    assert response.status_code == 422
    assert response.json()["detail"] == "Recovery-outcome status filter is invalid"
    load_outcomes.assert_not_awaited()
