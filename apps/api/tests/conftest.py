import pytest

from app.core.config import get_settings


@pytest.fixture(autouse=True)
def configured_reviewer_access(monkeypatch: pytest.MonkeyPatch):
    """Give endpoint tests an explicit non-production reviewer credential."""

    monkeypatch.setenv("RECLAIMRAIL_REVIEWER_ACCESS_TOKEN", "reviewer-secret")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
