"""Provider-neutral contracts for the bounded read-only investigator."""

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from app.domain.investigation import InvestigatorProviderResponse


class EvidenceInvestigatorFailureKind(StrEnum):
    CONFIGURATION = "configuration"
    ACCESS_DENIED = "access_denied"
    QUOTA_EXHAUSTED = "quota_exhausted"
    TIMEOUT = "timeout"
    TRANSIENT_PROVIDER = "transient_provider"
    MALFORMED_RESPONSE = "malformed_response"
    PROVIDER_REJECTED = "provider_rejected"
    UNKNOWN_PROVIDER = "unknown_provider"


class EvidenceInvestigatorProviderReason(StrEnum):
    KEY_MISSING = "key_missing"
    MODEL_MISSING = "model_missing"
    CREDENTIAL_REJECTED = "credential_rejected"
    MODEL_NOT_SUPPORTED = "model_not_supported"
    THINKING_LEVEL_REJECTED = "thinking_level_rejected"
    RESPONSE_SCHEMA_REJECTED = "response_schema_rejected"
    STRUCTURED_OUTPUT_REJECTED = "structured_output_rejected"
    GENERATION_PARAMETER_REJECTED = "generation_parameter_rejected"
    INVALID_ARGUMENT = "invalid_argument"
    UNKNOWN_REJECTION = "unknown_rejection"


class EvidenceInvestigatorRateLimitCategory(StrEnum):
    REQUEST = "request"
    TOKEN = "token"
    REQUEST_AND_TOKEN = "request_and_token"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class EvidenceInvestigatorRateLimitMetadata:
    """Strictly allowlisted quota data; never stores arbitrary provider headers."""

    category: EvidenceInvestigatorRateLimitCategory
    request_limit: int | None = None
    request_remaining: int | None = None
    token_limit: int | None = None
    token_remaining: int | None = None
    request_reset_seconds: float | None = None
    token_reset_seconds: float | None = None
    retry_after_seconds: float | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "category": self.category.value,
            "request_limit": self.request_limit,
            "request_remaining": self.request_remaining,
            "token_limit": self.token_limit,
            "token_remaining": self.token_remaining,
            "request_reset_seconds": self.request_reset_seconds,
            "token_reset_seconds": self.token_reset_seconds,
            "retry_after_seconds": self.retry_after_seconds,
        }


class EvidenceInvestigatorProviderError(RuntimeError):
    """Sanitized failure.  The message is safe but is never persisted verbatim."""

    def __init__(
        self,
        message: str,
        *,
        kind: EvidenceInvestigatorFailureKind,
        retryable: bool,
        status_code: int | None = None,
        provider_status: str | None = None,
        reason_code: EvidenceInvestigatorProviderReason | None = None,
        rate_limit_metadata: EvidenceInvestigatorRateLimitMetadata | None = None,
    ) -> None:
        super().__init__(message)
        self.kind = kind
        self.retryable = retryable
        self.status_code = status_code
        self.provider_status = provider_status
        self.reason_code = reason_code
        self.rate_limit_metadata = rate_limit_metadata


class EvidenceInvestigatorProvider(Protocol):
    provider_name: str

    async def next_turn(self, request: dict[str, object]) -> InvestigatorProviderResponse: ...


@dataclass(frozen=True, slots=True)
class InvestigatorProviderAttempt:
    provider: str
    requested_model: str
    returned_model: str | None
    model_version: str | None
    started_at_ms: int
    completed_at_ms: int
    latency_ms: int
    status: str
    failure_kind: EvidenceInvestigatorFailureKind | None = None
    status_code: int | None = None
    input_token_count: int | None = None
    output_token_count: int | None = None
    selected: bool = False


class OrderedEvidenceInvestigator:
    """Future-ready bounded chain; the Phase 17B configuration supplies Groq only."""

    def __init__(self, providers: tuple[EvidenceInvestigatorProvider, ...]) -> None:
        if not 1 <= len(providers) <= 2:
            raise ValueError("Investigator provider chain must contain one or two providers")
        self._providers = providers
        self.provider_name = providers[0].provider_name

    async def next_turn(self, request: dict[str, object]) -> InvestigatorProviderResponse:
        last_error: EvidenceInvestigatorProviderError | None = None
        for index, provider in enumerate(self._providers):
            try:
                return await provider.next_turn(request)
            except EvidenceInvestigatorProviderError as error:
                last_error = error
                if index + 1 == len(self._providers) or not allows_failover(error):
                    raise
        assert last_error is not None
        raise last_error


def allows_failover(error: EvidenceInvestigatorProviderError) -> bool:
    return error.kind in {
        EvidenceInvestigatorFailureKind.TIMEOUT,
        EvidenceInvestigatorFailureKind.QUOTA_EXHAUSTED,
        EvidenceInvestigatorFailureKind.TRANSIENT_PROVIDER,
        EvidenceInvestigatorFailureKind.MALFORMED_RESPONSE,
    }
