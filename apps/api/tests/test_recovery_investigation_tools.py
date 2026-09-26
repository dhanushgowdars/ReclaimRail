from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.investigation import InvestigationToolOutcome
from app.services.recovery_investigation_tools import (
    TOOL_SPECS,
    InvestigationToolRejectedError,
    _redact,
    execute_investigation_tool,
    public_tool_catalog,
)

CASE_ID = UUID("91000000-0000-0000-0000-000000000001")
NOW = datetime(2026, 9, 25, 12, tzinfo=UTC)


def test_registry_is_versioned_read_only_and_has_strict_input_schemas() -> None:
    assert len(TOOL_SPECS) == 11
    catalog = public_tool_catalog()
    assert all(item["read_only"] is True for item in catalog)
    assert all(item["input_schema"]["additionalProperties"] is False for item in catalog)


def test_recursive_redaction_removes_sensitive_values() -> None:
    redacted = _redact(
        {
            "email": "person@example.test",
            "nested": {"phone_number": "+910000000000", "state": "failed"},
        },
    )
    assert redacted == {
        "email": "[REDACTED]",
        "nested": {"phone_number": "[REDACTED]", "state": "failed"},
    }


@pytest.mark.asyncio
async def test_tool_rejects_unknown_tool_cross_case_and_extra_arguments() -> None:
    session = AsyncMock(spec=AsyncSession)
    with pytest.raises(InvestigationToolRejectedError, match="allow-list"):
        await execute_investigation_tool(
            session,
            recovery_case_id=CASE_ID,
            evidence_cutoff_at=NOW,
            tool_name="create_payment_link",
            arguments={"case_id": str(CASE_ID)},
        )

    with pytest.raises(InvestigationToolRejectedError, match="do not belong"):
        await execute_investigation_tool(
            session,
            recovery_case_id=CASE_ID,
            evidence_cutoff_at=NOW,
            tool_name="get_truth_snapshot",
            arguments={"case_id": "92000000-0000-0000-0000-000000000001"},
        )

    with pytest.raises(InvestigationToolRejectedError, match="arguments"):
        await execute_investigation_tool(
            session,
            recovery_case_id=CASE_ID,
            evidence_cutoff_at=NOW,
            tool_name="get_truth_snapshot",
            arguments={"case_id": str(CASE_ID), "write": True},
        )


@pytest.mark.asyncio
async def test_policy_tool_exposes_capabilities_not_a_decision() -> None:
    recovery_case = MagicMock()
    recovery_case.id = CASE_ID
    recovery_case.version = 4
    recovery_case.customer_contact_allowed = False
    result = MagicMock()
    result.scalar_one_or_none.return_value = recovery_case
    session = AsyncMock(spec=AsyncSession)
    session.execute.return_value = result

    observation = await execute_investigation_tool(
        session,
        recovery_case_id=CASE_ID,
        evidence_cutoff_at=NOW,
        tool_name="get_merchant_policy_summary",
        arguments={"case_id": str(CASE_ID)},
    )

    assert observation.outcome is InvestigationToolOutcome.SUCCEEDED
    assert observation.payload["ai_can_authorize"] is False
    assert observation.payload["provider_mutation_allowed"] is False
    assert "decision" not in observation.payload
