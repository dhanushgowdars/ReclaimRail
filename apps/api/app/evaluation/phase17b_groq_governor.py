"""Evaluation-only proactive governor for the frozen Groq corpus."""

from __future__ import annotations

import json
import math
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Final, Protocol

from app.integrations.groq.evidence_investigator import GROQ_EVALUATION_INSTRUCTION, _tools
from app.integrations.investigator import (
    EvidenceInvestigatorFailureKind,
    EvidenceInvestigatorProviderError,
)

GROQ_RPM: Final = 30
GROQ_RPD: Final = 1_000
GROQ_TPM: Final = 8_000
GROQ_TPD: Final = 200_000
EVALUATION_TPM_CEILING: Final = 6_000
EVALUATION_TPD_CEILING: Final = 180_000
SAFETY_MARGIN: Final = 1.25
MAX_OUTPUT_TOKENS: Final = 512

Clock = Callable[[], float]
Sleeper = Callable[[float], Awaitable[None]]


class TurnProvider(Protocol):
    async def next_turn(self, request: dict[str, object]) -> object: ...


class GovernorStoppedError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class GovernorReservation:
    estimated_tokens: int
    wait_seconds: float
    at_seconds: float


@dataclass(slots=True)
class GroqEvaluationGovernor:
    clock: Clock
    sleeper: Sleeper
    minute_events: deque[tuple[float, int]] = field(default_factory=deque)
    day_events: deque[tuple[float, int]] = field(default_factory=deque)
    stopped: bool = False
    consecutive_transient_failures: int = 0

    def _prune(self, now: float) -> None:
        while self.minute_events and self.minute_events[0][0] <= now - 60:
            self.minute_events.popleft()
        while self.day_events and self.day_events[0][0] <= now - 86_400:
            self.day_events.popleft()

    async def reserve(self, estimated_tokens: int) -> GovernorReservation:
        if self.stopped:
            raise GovernorStoppedError("evaluation governor stopped")
        if not 1 <= estimated_tokens <= EVALUATION_TPM_CEILING:
            raise GovernorStoppedError("single request exceeds evaluation token ceiling")
        now = self.clock()
        self._prune(now)
        if (
            len(self.day_events) >= GROQ_RPD
            or sum(tokens for _, tokens in self.day_events) + estimated_tokens
            > EVALUATION_TPD_CEILING
        ):
            raise GovernorStoppedError("evaluation day ceiling exhausted")
        if len(self.minute_events) >= GROQ_RPM or (
            sum(tokens for _, tokens in self.minute_events) + estimated_tokens
            > EVALUATION_TPM_CEILING
        ):
            wait = max(0.0, self.minute_events[0][0] + 60 - now)
        else:
            wait = 0.0
        if wait:
            await self.sleeper(wait)
            now = self.clock()
            self._prune(now)
        self.minute_events.append((now, estimated_tokens))
        self.day_events.append((now, estimated_tokens))
        return GovernorReservation(estimated_tokens, wait, now)

    def stop_on_error(self, error: object) -> None:
        if not isinstance(error, EvidenceInvestigatorProviderError):
            self.stopped = True
            return
        if error.kind is EvidenceInvestigatorFailureKind.UNKNOWN_PROVIDER:
            self.stopped = True
            return
        if error.kind in {
            EvidenceInvestigatorFailureKind.TIMEOUT,
            EvidenceInvestigatorFailureKind.TRANSIENT_PROVIDER,
        }:
            self.consecutive_transient_failures += 1
            self.stopped = self.consecutive_transient_failures >= 2
        else:
            self.consecutive_transient_failures = 0


@dataclass(slots=True)
class GovernedEvaluationProvider:
    """Evaluation wrapper only; production workers never construct this type."""

    provider: TurnProvider
    governor: GroqEvaluationGovernor
    max_attempts: int = 2

    async def next_turn(self, request: dict[str, object]) -> object:
        payload = serialized_payload(
            request,
            [
                {"role": "system", "content": GROQ_EVALUATION_INSTRUCTION},
                {"role": "user", "content": json.dumps(request, sort_keys=True, default=str)},
            ],
        )
        for attempt in range(1, self.max_attempts + 1):
            await self.governor.reserve(estimate_tokens(payload))
            if hasattr(self.provider, "attempt_number"):
                setattr(self.provider, "attempt_number", attempt)  # noqa: B010 - optional metered seam
            try:
                result = await self.provider.next_turn(request)
                self.governor.consecutive_transient_failures = 0
                return result
            except Exception as error:  # noqa: BLE001 - provider boundary is intentionally fail-closed
                diagnostic = getattr(
                    getattr(self.provider, "provider", None), "last_diagnostic_details", None
                )
                tool_failure = (
                    isinstance(diagnostic, dict)
                    and diagnostic.get("provider_error_code_raw") == "tool_use_failed"
                )
                transient = isinstance(error, EvidenceInvestigatorProviderError) and error.kind in {
                    EvidenceInvestigatorFailureKind.TIMEOUT,
                    EvidenceInvestigatorFailureKind.TRANSIENT_PROVIDER,
                }
                if attempt < self.max_attempts and (tool_failure or transient):
                    await self.governor.sleeper(2.5)
                    continue
                self.governor.stop_on_error(error)
                raise
        raise AssertionError("bounded evaluation attempt loop exhausted")


def estimate_tokens(payload: dict[str, object]) -> int:
    """Conservative offline estimate: serialized payload, 25% margin, maximum output."""
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    return math.ceil((math.ceil(len(encoded) / 4) + MAX_OUTPUT_TOKENS) * SAFETY_MARGIN)


def dry_run_schedule(
    request_payloads: tuple[dict[str, object], ...],
) -> tuple[GovernorReservation, ...]:
    now = 0.0

    def clock() -> float:
        return now

    async def sleeper(seconds: float) -> None:
        nonlocal now
        now += seconds

    async def build() -> tuple[GovernorReservation, ...]:
        governor = GroqEvaluationGovernor(clock, sleeper)
        reservations: list[GovernorReservation] = []
        for payload in request_payloads:
            reservations.append(await governor.reserve(estimate_tokens(payload)))
        return tuple(reservations)

    import asyncio

    return asyncio.run(build())


def serialized_payload(
    request: dict[str, object], messages: list[dict[str, object]]
) -> dict[str, object]:
    """Shared offline payload shape; no provider transport is created."""
    return {
        "model": "openai/gpt-oss-120b",
        "messages": messages,
        "tools": _tools(request),
        "tool_choice": "required",
        "parallel_tool_calls": False,
        "max_completion_tokens": MAX_OUTPUT_TOKENS,
        "temperature": 0,
    }
