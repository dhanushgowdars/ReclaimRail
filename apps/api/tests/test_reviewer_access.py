from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.main import app

REVIEWER_HEADERS = {"X-ReclaimRail-Reviewer-Token": "reviewer-secret"}


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/health/workers"),
        ("GET", "/health/queues"),
        ("GET", "/recovery/dashboard/summary"),
        ("GET", "/recovery/dashboard/cases"),
        ("GET", "/recovery/dashboard/cases/not-a-uuid"),
        ("GET", "/recovery/dashboard/incidents"),
        ("GET", "/recovery/dashboard/outcomes"),
        ("POST", "/recovery/evaluations/controlled-batch"),
        ("GET", "/recovery/evaluations/not-a-uuid"),
        ("GET", "/recovery/evaluations/not-a-uuid/scenarios"),
    ],
)
@pytest.mark.parametrize("headers", [{}, {"X-ReclaimRail-Reviewer-Token": "wrong"}])
def test_operational_routes_reject_missing_or_wrong_reviewer_token(
    client: TestClient,
    method: str,
    path: str,
    headers: dict[str, str],
) -> None:
    response = client.request(method, path, headers=headers)

    assert response.status_code == 401
    assert response.json() == {"detail": "Reviewer access denied"}


def test_operational_routes_fail_closed_when_reviewer_access_is_unconfigured(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("RECLAIMRAIL_REVIEWER_ACCESS_TOKEN")
    get_settings.cache_clear()

    response = client.get("/health/workers")

    assert response.status_code == 503
    assert response.json() == {"detail": "Reviewer access is not configured"}


def test_correct_reviewer_token_reaches_route_validation(client: TestClient) -> None:
    response = client.get("/health/workers", headers=REVIEWER_HEADERS)

    assert response.status_code in {200, 503}
    assert response.json().get("detail") not in {
        "Reviewer access denied",
        "Reviewer access is not configured",
    }


def test_liveness_and_readiness_do_not_require_reviewer_token(
    client: TestClient,
) -> None:
    live = client.get("/health/live")
    ready = client.get("/health/ready")

    assert live.status_code == 200
    assert ready.status_code in {200, 503}
    assert live.json()["status"] == "ok"
    assert ready.json()["status"] in {"ready", "not_ready"}
