"""Contracts for bounded, reviewer-safe recovery investigation."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class InvestigationStatus(StrEnum):
    RUNNING = "running"
    COMPLETED = "completed"
    ABSTAINED = "abstained"
    FALLBACK = "fallback"
    FAILED_SAFE = "failed_safe"


class InvestigationTurnAction(StrEnum):
    CALL_TOOL = "call_tool"
    COMPLETE = "complete"
    ABSTAIN = "abstain"


class InvestigationToolOutcome(StrEnum):
    SUCCEEDED = "succeeded"
    UNAVAILABLE = "unavailable"
    REJECTED = "rejected"
    FAILED = "failed"


class HypothesisStatus(StrEnum):
    OPEN = "open"
    SUPPORTED = "supported"
    CONTRADICTED = "contradicted"
    UNRESOLVED = "unresolved"
    REJECTED = "rejected"


@dataclass(frozen=True, slots=True)
class InvestigationBudgets:
    max_tool_calls: int = 8
    max_model_retries: int = 2
    max_total_tokens: int = 12_000
    max_duration: timedelta = timedelta(seconds=30)

    def __post_init__(self) -> None:
        if not 1 <= self.max_tool_calls <= 20:
            raise ValueError("Tool-call budget must be between one and twenty")
        if not 0 <= self.max_model_retries <= 5:
            raise ValueError("Model retry budget must be between zero and five")
        if not 256 <= self.max_total_tokens <= 100_000:
            raise ValueError("Token budget must be between 256 and 100000")
        if not timedelta(seconds=1) <= self.max_duration <= timedelta(minutes=5):
            raise ValueError("Investigation duration must be between one second and five minutes")


class HypothesisUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str = Field(min_length=1, max_length=80, pattern=r"^[a-z0-9][a-z0-9_.-]*$")
    claim: str = Field(min_length=1, max_length=300)
    status: HypothesisStatus
    supporting_evidence_ids: tuple[str, ...] = Field(default=(), max_length=20)
    contradicting_evidence_ids: tuple[str, ...] = Field(default=(), max_length=20)
    missing_questions: tuple[str, ...] = Field(default=(), max_length=10)
    next_observation: str | None = Field(default=None, max_length=200)


class InvestigatorTurn(BaseModel):
    """One structured model turn; never stores private chain-of-thought."""

    model_config = ConfigDict(extra="forbid")
    action: InvestigationTurnAction
    tool_name: str | None = Field(default=None, max_length=80)
    tool_arguments: dict[str, object] | None = None
    hypotheses: tuple[HypothesisUpdate, ...] = Field(default=(), max_length=10)
    summary: str | None = Field(default=None, max_length=600)
    evidence_ids: tuple[str, ...] = Field(default=(), max_length=30)
    abstention_reason: str | None = Field(default=None, max_length=300)

    @model_validator(mode="after")
    def validate_shape(self) -> Self:
        if self.action is InvestigationTurnAction.CALL_TOOL:
            if not self.tool_name or self.tool_arguments is None:
                raise ValueError("Tool turn requires tool name and arguments")
            if self.summary is not None or self.abstention_reason is not None:
                raise ValueError("Tool turn cannot contain a terminal result")
        elif self.action is InvestigationTurnAction.COMPLETE:
            if not self.summary or not self.evidence_ids:
                raise ValueError("Completed investigation requires summary and evidence")
            if self.tool_name is not None or self.tool_arguments is not None:
                raise ValueError("Completed investigation cannot request a tool")
        else:
            if not self.abstention_reason:
                raise ValueError("Abstention requires a reason")
            if self.tool_name is not None or self.tool_arguments is not None:
                raise ValueError("Abstention cannot request a tool")
        return self


@dataclass(frozen=True, slots=True)
class InvestigationToolObservation:
    tool_name: str
    outcome: InvestigationToolOutcome
    evidence_ids: tuple[str, ...]
    payload: dict[str, object]
    started_at: datetime
    completed_at: datetime
    error_code: str | None = None

    def __post_init__(self) -> None:
        for value in (self.started_at, self.completed_at):
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError("Tool timestamps must be timezone-aware")
        if self.completed_at < self.started_at:
            raise ValueError("Tool completion cannot precede start")
        if self.outcome is InvestigationToolOutcome.SUCCEEDED and not self.evidence_ids:
            raise ValueError("Successful tool observation requires evidence references")


@dataclass(frozen=True, slots=True)
class InvestigatorProviderResponse:
    turn: object
    model_name: str
    model_version: str | None = None
    input_token_count: int | None = None
    output_token_count: int | None = None
