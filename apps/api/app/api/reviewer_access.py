import secrets
from typing import Annotated

from fastapi import Depends, Header, HTTPException, status

from app.core.config import Settings, get_settings

SettingsDependency = Annotated[Settings, Depends(get_settings)]
ReviewerTokenHeader = Annotated[
    str | None,
    Header(alias="X-ReclaimRail-Reviewer-Token"),
]


def require_reviewer_access(
    settings: SettingsDependency,
    provided_token: ReviewerTokenHeader = None,
) -> None:
    """Fail closed unless the server-held reviewer token is configured and supplied."""

    configured_token = settings.reviewer_access_token
    if configured_token is None or not configured_token.get_secret_value().strip():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Reviewer access is not configured",
        )

    expected = configured_token.get_secret_value()
    if provided_token is None or not secrets.compare_digest(provided_token, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Reviewer access denied",
        )
