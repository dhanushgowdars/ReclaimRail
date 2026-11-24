import pytest

from app.evaluation.phase17b_groq_governor import (
    EVALUATION_TPD_CEILING,
    EVALUATION_TPM_CEILING,
    GovernedEvaluationProvider,
    GovernorStoppedError,
    GroqEvaluationGovernor,
    dry_run_schedule,
    estimate_tokens,
)
from app.integrations.investigator import (
    EvidenceInvestigatorFailureKind,
    EvidenceInvestigatorProviderError,
)
from app.services.recovery_investigation_tools import public_tool_catalog


class FakeTime:
    def __init__(self) -> None:
        self.now = 0.0
        self.waits: list[float] = []

    def clock(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.waits.append(seconds)
        self.now += seconds


@pytest.mark.asyncio
async def test_rolling_window_paces_before_transmission_and_advances_fake_clock() -> None:
    fake = FakeTime()
    governor = GroqEvaluationGovernor(fake.clock, fake.sleep)
    await governor.reserve(4_000)
    reservation = await governor.reserve(4_000)
    assert reservation.wait_seconds == 60
    assert fake.waits == [60]
    assert sum(tokens for _, tokens in governor.minute_events) == 4_000


def test_estimate_includes_serialization_margin_and_maximum_output() -> None:
    estimate = estimate_tokens({"messages": [{"role": "user", "content": "x" * 4000}]})
    assert estimate > (4000 // 4) + 512


@pytest.mark.asyncio
async def test_day_limit_and_oversized_request_fail_before_waiting() -> None:
    fake = FakeTime()
    governor = GroqEvaluationGovernor(fake.clock, fake.sleep)
    governor.day_events.append((0.0, EVALUATION_TPD_CEILING))
    with pytest.raises(GovernorStoppedError, match="day ceiling"):
        await governor.reserve(1)
    with pytest.raises(GovernorStoppedError, match="single request"):
        await GroqEvaluationGovernor(fake.clock, fake.sleep).reserve(EVALUATION_TPM_CEILING + 1)
    assert fake.waits == []


@pytest.mark.asyncio
async def test_request_count_ceiling_paces_without_retry() -> None:
    fake = FakeTime()
    governor = GroqEvaluationGovernor(fake.clock, fake.sleep)
    for _ in range(30):
        await governor.reserve(1)
    reservation = await governor.reserve(1)
    assert reservation.wait_seconds == 60
    assert fake.waits == [60]


@pytest.mark.asyncio
async def test_definitive_provider_error_does_not_stop_next_scenario() -> None:
    fake = FakeTime()

    class FailingProvider:
        calls = 0

        async def next_turn(self, request: dict[str, object]) -> object:
            self.calls += 1
            raise EvidenceInvestigatorProviderError(
                "sanitized",
                kind=EvidenceInvestigatorFailureKind.QUOTA_EXHAUSTED,
                retryable=False,
                status_code=429,
            )

    provider = FailingProvider()
    wrapped = GovernedEvaluationProvider(provider, GroqEvaluationGovernor(fake.clock, fake.sleep))
    with pytest.raises(EvidenceInvestigatorProviderError):
        await wrapped.next_turn({"tools": public_tool_catalog(), "observations": []})
    assert provider.calls == 1
    with pytest.raises(EvidenceInvestigatorProviderError):
        await wrapped.next_turn({"tools": public_tool_catalog(), "observations": []})
    assert provider.calls == 2


@pytest.mark.asyncio
async def test_indeterminate_timeout_stops_wrapper() -> None:
    fake = FakeTime()

    class FailingProvider:
        async def next_turn(self, request: dict[str, object]) -> object:
            raise EvidenceInvestigatorProviderError(
                "sanitized",
                kind=EvidenceInvestigatorFailureKind.TIMEOUT,
                retryable=True,
            )

    wrapped = GovernedEvaluationProvider(
        FailingProvider(), GroqEvaluationGovernor(fake.clock, fake.sleep)
    )
    with pytest.raises(EvidenceInvestigatorProviderError):
        await wrapped.next_turn({"tools": public_tool_catalog(), "observations": []})
    with pytest.raises(EvidenceInvestigatorProviderError):
        await wrapped.next_turn({"tools": public_tool_catalog(), "observations": []})
    with pytest.raises(GovernorStoppedError):
        await wrapped.next_turn({"tools": public_tool_catalog(), "observations": []})


def test_dry_run_schedule_is_local_and_respects_windows() -> None:
    schedule = dry_run_schedule(({"messages": [{"content": "x" * 1000}]},) * 3)
    assert len(schedule) == 3
    assert all(item.estimated_tokens <= EVALUATION_TPM_CEILING for item in schedule)
    assert all(item.wait_seconds >= 0 for item in schedule)


@pytest.mark.asyncio
async def test_tool_use_failed_retries_once_with_backoff_and_attempt_number() -> None:
    fake = FakeTime()

    class Adapter:
        last_diagnostic_details = {"provider_error_code_raw": "tool_use_failed"}

    class Meter:
        provider = Adapter()
        attempt_number = 0
        attempts: list[int] = []

        async def next_turn(self, request: dict[str, object]) -> object:
            self.attempts.append(self.attempt_number)
            if self.attempt_number == 1:
                raise EvidenceInvestigatorProviderError(
                    "safe",
                    kind=EvidenceInvestigatorFailureKind.PROVIDER_REJECTED,
                    retryable=False,
                    status_code=400,
                )
            return "accepted"

    meter = Meter()
    wrapped = GovernedEvaluationProvider(meter, GroqEvaluationGovernor(fake.clock, fake.sleep))
    assert (
        await wrapped.next_turn({"tools": public_tool_catalog(), "observations": []}) == "accepted"
    )
    assert meter.attempts == [1, 2]
    assert any(wait >= 2.5 for wait in fake.waits)
