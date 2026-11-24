"""Mistral evaluation candidate; generates local read-only calls without executing tools."""

from __future__ import annotations

import json

import httpx2

from app.integrations.groq.evidence_investigator import (
    GroqEvidenceInvestigator,
    _GroqToolCall,
)
from app.integrations.investigator import (
    EvidenceInvestigatorRateLimitCategory,
    EvidenceInvestigatorRateLimitMetadata,
)


class MistralEvidenceInvestigator(GroqEvidenceInvestigator):
    provider_name = "mistral"
    base_url = "https://api.mistral.ai/v1"
    model_allowlist = frozenset({"mistral-large-2512", "mistral-medium-latest"})

    @staticmethod
    def _quota_from_headers(headers: httpx2.Headers) -> EvidenceInvestigatorRateLimitMetadata:
        value = headers.get("x-ratelimit-remaining")
        remaining = int(value) if value is not None and value.isdigit() else None
        return EvidenceInvestigatorRateLimitMetadata(
            category=EvidenceInvestigatorRateLimitCategory.REQUEST,
            request_remaining=remaining if remaining is not None and remaining <= 10**12 else None,
        )

    @staticmethod
    def _tool_result_message(
        pending: _GroqToolCall, observation: dict[str, object]
    ) -> dict[str, object]:
        return {
            "role": "tool",
            "name": pending.tool_name,
            "tool_call_id": pending.call_id,
            "content": json.dumps(observation, sort_keys=True, separators=(",", ":"), default=str),
        }
