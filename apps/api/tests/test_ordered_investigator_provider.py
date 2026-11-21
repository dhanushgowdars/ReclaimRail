import pytest

from app.domain.investigation import (
    InvestigationTurnAction,
    InvestigatorProviderResponse,
    InvestigatorTurn,
)
from app.integrations.investigator import (
    EvidenceInvestigatorFailureKind,
    EvidenceInvestigatorProviderError,
    OrderedEvidenceInvestigator,
)


class Provider:
    def __init__(self, name: str, result: object) -> None:
        self.provider_name = name
        self.result = result
        self.calls = 0

    async def next_turn(self, request: dict[str, object]) -> InvestigatorProviderResponse:
        self.calls += 1
        if isinstance(self.result, Exception):
            raise self.result
        return self.result  # type: ignore[return-value]


def response(name: str) -> InvestigatorProviderResponse:
    return InvestigatorProviderResponse(
        turn=InvestigatorTurn(
            action=InvestigationTurnAction.ABSTAIN, abstention_reason="insufficient"
        ),
        model_name=f"{name}-model",
        input_token_count=1,
        output_token_count=1,
        provider=name,
    )


@pytest.mark.asyncio
async def test_chain_uses_one_eligible_failover_once_each() -> None:
    first = Provider(
        "primary",
        EvidenceInvestigatorProviderError(
            "safe",
            kind=EvidenceInvestigatorFailureKind.TRANSIENT_PROVIDER,
            retryable=False,
            status_code=503,
        ),
    )
    second = Provider("secondary", response("secondary"))
    result = await OrderedEvidenceInvestigator((first, second)).next_turn({})
    assert result.provider == "secondary"
    assert first.calls == second.calls == 1


@pytest.mark.asyncio
async def test_chain_closes_on_ineligible_error() -> None:
    first = Provider(
        "primary",
        EvidenceInvestigatorProviderError(
            "safe",
            kind=EvidenceInvestigatorFailureKind.ACCESS_DENIED,
            retryable=False,
            status_code=401,
        ),
    )
    second = Provider("secondary", response("secondary"))
    with pytest.raises(EvidenceInvestigatorProviderError):
        await OrderedEvidenceInvestigator((first, second)).next_turn({})
    assert first.calls == 1
    assert second.calls == 0


def test_chain_rejects_more_than_two_providers() -> None:
    with pytest.raises(ValueError, match="one or two"):
        OrderedEvidenceInvestigator(
            (
                Provider("a", response("a")),
                Provider("b", response("b")),
                Provider("c", response("c")),
            )
        )
