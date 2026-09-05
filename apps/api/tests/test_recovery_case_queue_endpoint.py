from collections.abc import AsyncIterator
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes import recovery_dashboard
from app.core.database import get_database_session
from app.main import app
from app.services.recovery_case_queue_service import (
    RecoveryCaseQueueItem,
    RecoveryCaseQueuePage,
)

CASE_ID = UUID("10000000-0000-0000-0000-000000000001")
INCIDENT_ID = UUID("20000000-0000-0000-0000-000000000001")
NOW = datetime(2026, 8, 26, 5, 0, tzinfo=UTC)


async def override_database_session() -> AsyncIterator[AsyncSession]:
    yield MagicMock(spec=AsyncSession)


@pytest.fixture(autouse=True)
def database_session_override() -> AsyncIterator[None]:
    app.dependency_overrides[get_database_session] = override_database_session

    yield

    app.dependency_overrides.clear()


def build_item() -> RecoveryCaseQueueItem:
    return RecoveryCaseQueueItem(
        recovery_case_id=CASE_ID,
        status="ready",
        amount_minor=349_900,
        currency="INR",
        payment_method="upi",
        source_incident_id=INCIDENT_ID,
        recovery_attempt_count=1,
        next_action_at=NOW,
        late_authorization_detected_at=None,
        opened_at=NOW,
        closed_at=None,
        updated_at=NOW,
        latest_action_type="create_payment_link",
        latest_action_status="succeeded",
        latest_action_policy_outcome="allow",
        latest_approval_status=None,
        latest_approval_reason=None,
        latest_approval_decision_reason=None,
        latest_approval_decided_at=None,
        latest_approval_decided_by=None,
        outcome_status="payment_link_pending",
    )


def build_page() -> RecoveryCaseQueuePage:
    return RecoveryCaseQueuePage(
        items=(build_item(),),
        total_count=1,
        limit=25,
        offset=0,
    )


def test_lists_pii_safe_recovery_cases_from_real_queue_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    load_queue = AsyncMock(return_value=build_page())
    monkeypatch.setattr(
        recovery_dashboard,
        "load_recovery_case_queue",
        load_queue,
    )

    with TestClient(app) as client:
        response = client.get("/recovery/dashboard/cases")

    assert response.status_code == 200

    body = response.json()

    assert body["total_count"] == 1
    assert body["limit"] == 25
    assert body["offset"] == 0
    assert body["items"] == [
        {
            "recovery_case_id": str(CASE_ID),
            "status": "ready",
            "amount_minor": 349_900,
            "currency": "INR",
            "payment_method": "upi",
            "source_incident_id": str(INCIDENT_ID),
            "recovery_attempt_count": 1,
            "next_action_at": "2026-08-26T05:00:00Z",
            "late_authorization_detected_at": None,
            "opened_at": "2026-08-26T05:00:00Z",
            "closed_at": None,
            "updated_at": "2026-08-26T05:00:00Z",
            "latest_action_type": "create_payment_link",
            "latest_action_status": "succeeded",
            "latest_action_policy_outcome": "allow",
            "latest_approval_status": None,
            "latest_approval_reason": None,
            "latest_approval_decision_reason": None,
            "latest_approval_decided_at": None,
            "latest_approval_decided_by": None,
            "outcome_status": "payment_link_pending",
        },
    ]
    assert "email" not in response.text
    assert "contact" not in response.text
    assert load_queue.await_args.kwargs["filters"].currency == "INR"


def test_lists_filtered_paginated_recovery_cases(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    load_queue = AsyncMock(return_value=build_page())
    monkeypatch.setattr(
        recovery_dashboard,
        "load_recovery_case_queue",
        load_queue,
    )

    with TestClient(app) as client:
        response = client.get(
            "/recovery/dashboard/cases",
            params=[
                ("currency", "usd"),
                ("status", "ready"),
                ("status", "waiting"),
                ("source_incident_id", str(INCIDENT_ID)),
                ("limit", "50"),
                ("offset", "25"),
            ],
        )

    assert response.status_code == 200

    filters = load_queue.await_args.kwargs["filters"]
    assert filters.currency == "USD"
    assert filters.statuses == ("ready", "waiting")
    assert filters.source_incident_id == INCIDENT_ID
    assert filters.limit == 50
    assert filters.offset == 25


def test_rejects_invalid_recovery_case_status_before_querying(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    load_queue = AsyncMock()
    monkeypatch.setattr(
        recovery_dashboard,
        "load_recovery_case_queue",
        load_queue,
    )

    with TestClient(app) as client:
        response = client.get(
            "/recovery/dashboard/cases",
            params={"status": "unknown"},
        )

    assert response.status_code == 422
    assert response.json()["detail"] == ("Recovery-case status filter is invalid")
    load_queue.assert_not_awaited()


def test_rejects_out_of_bounds_queue_limit_before_querying(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    load_queue = AsyncMock()
    monkeypatch.setattr(
        recovery_dashboard,
        "load_recovery_case_queue",
        load_queue,
    )

    with TestClient(app) as client:
        response = client.get(
            "/recovery/dashboard/cases",
            params={"limit": "101"},
        )

    assert response.status_code == 422
    load_queue.assert_not_awaited()
