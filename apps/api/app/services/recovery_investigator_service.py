"""Bounded, durable, read-only recovery evidence investigation."""

import asyncio
import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models.investigation import (
    RecoveryInvestigationHypothesis,
    RecoveryInvestigationSession,
    RecoveryInvestigationStep,
)
from app.db.models.payment_truth import PaymentTruthSnapshotRecord
from app.db.models.recovery import RecoveryCase
from app.domain.investigation import (
    InvestigationBudgets,
    InvestigationStatus,
    InvestigationTurnAction,
    InvestigatorProviderResponse,
    InvestigatorTurn,
)
from app.integrations.gemini.evidence_investigator import (
    INVESTIGATOR_PROMPT_VERSION,
    EvidenceInvestigatorProvider,
)
from app.services.recovery_investigation_tools import (
    TOOL_REGISTRY_VERSION,
    TOOL_TIMEOUT_SECONDS,
    InvestigationToolRejectedError,
    execute_investigation_tool,
    public_tool_catalog,
)

SessionFactory = async_sessionmaker[AsyncSession]


@dataclass(frozen=True, slots=True)
class RecoveryInvestigationResult:
    session_id: UUID
    status: InvestigationStatus
    terminal_reason: str
    result_summary: str | None
    evidence_ids: tuple[str, ...]


def _digest(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(encoded).hexdigest()


def _parse_turn(response: InvestigatorProviderResponse) -> InvestigatorTurn:
    if isinstance(response.turn, InvestigatorTurn):
        return response.turn
    if isinstance(response.turn, str):
        return InvestigatorTurn.model_validate_json(response.turn)
    return InvestigatorTurn.model_validate(response.turn)


def _as_result(record: RecoveryInvestigationSession) -> RecoveryInvestigationResult:
    return RecoveryInvestigationResult(
        session_id=record.id,
        status=InvestigationStatus(record.status),
        terminal_reason=record.terminal_reason or "running",
        result_summary=record.result_summary,
        evidence_ids=tuple(record.result_evidence_ids),
    )


async def _load_existing(
    session: AsyncSession,
    recovery_case_id: UUID,
    case_version: int,
) -> RecoveryInvestigationSession | None:
    result = await session.execute(
        select(RecoveryInvestigationSession).where(
            RecoveryInvestigationSession.recovery_case_id == recovery_case_id,
            RecoveryInvestigationSession.case_version == case_version,
        ),
    )
    return result.scalar_one_or_none()


async def _create_or_load_session(
    session_factory: SessionFactory,
    *,
    recovery_case_id: UUID,
    provider: EvidenceInvestigatorProvider | None,
    started_at: datetime,
    budgets: InvestigationBudgets,
) -> tuple[RecoveryInvestigationSession, bool]:
    try:
        async with session_factory.begin() as session:
            case_result = await session.execute(
                select(RecoveryCase).where(RecoveryCase.id == recovery_case_id).with_for_update(),
            )
            recovery_case = case_result.scalar_one()
            existing = await _load_existing(session, recovery_case_id, recovery_case.version)
            if existing is not None:
                return existing, False
            truth_result = await session.execute(
                select(PaymentTruthSnapshotRecord)
                .where(
                    PaymentTruthSnapshotRecord.payment_attempt_id
                    == recovery_case.payment_attempt_id,
                    PaymentTruthSnapshotRecord.resolved_at <= started_at,
                )
                .order_by(PaymentTruthSnapshotRecord.version.desc())
                .limit(1),
            )
            truth = truth_result.scalar_one()
            record = RecoveryInvestigationSession(
                recovery_case_id=recovery_case.id,
                payment_attempt_id=recovery_case.payment_attempt_id,
                truth_snapshot_id=truth.id,
                case_version=recovery_case.version,
                truth_version=truth.version,
                evidence_cutoff_at=started_at,
                status=InvestigationStatus.RUNNING.value,
                provider="gemini" if provider else "deterministic_fallback",
                model_name=None,
                model_version=None,
                prompt_version=INVESTIGATOR_PROMPT_VERSION,
                tool_registry_version=TOOL_REGISTRY_VERSION,
                shadow_mode=True,
                max_tool_calls=budgets.max_tool_calls,
                max_model_retries=budgets.max_model_retries,
                max_total_tokens=budgets.max_total_tokens,
                max_duration_ms=int(budgets.max_duration.total_seconds() * 1000),
                started_at=started_at,
            )
            session.add(record)
            await session.flush()
            return record, True
    except IntegrityError:
        async with session_factory() as session:
            case_version = await session.scalar(
                select(RecoveryCase.version).where(RecoveryCase.id == recovery_case_id),
            )
            if case_version is None:
                raise RuntimeError(
                    "Recovery case disappeared during investigation claim",
                ) from None
            existing = await _load_existing(session, recovery_case_id, case_version)
            if existing is None:
                raise
            return existing, False


async def _finish(
    session_factory: SessionFactory,
    *,
    session_id: UUID,
    status: InvestigationStatus,
    reason: str,
    completed_at: datetime,
    summary: str | None = None,
    evidence_ids: tuple[str, ...] = (),
) -> RecoveryInvestigationResult:
    async with session_factory.begin() as session:
        record = await session.get(RecoveryInvestigationSession, session_id, with_for_update=True)
        if record is None:
            raise RuntimeError("Investigation session disappeared")
        if record.status != InvestigationStatus.RUNNING.value:
            return _as_result(record)
        record.status = status.value
        record.terminal_reason = reason
        record.result_summary = summary
        record.result_evidence_ids = list(evidence_ids)
        record.result_digest = _digest(
            {
                "status": status.value,
                "reason": reason,
                "summary": summary,
                "evidence": evidence_ids,
            },
        )
        record.completed_at = completed_at
        await session.flush()
        return _as_result(record)


def _validate_citations(turn: InvestigatorTurn, known_evidence: set[str]) -> None:
    cited = set(turn.evidence_ids)
    for hypothesis in turn.hypotheses:
        cited.update(hypothesis.supporting_evidence_ids)
        cited.update(hypothesis.contradicting_evidence_ids)
    if cited.difference(known_evidence):
        raise ValueError("Model cited evidence that was not returned by a tool")


async def _persist_hypotheses(
    session: AsyncSession,
    session_id: UUID,
    sequence_number: int,
    turn: InvestigatorTurn,
) -> None:
    for update in turn.hypotheses:
        result = await session.execute(
            select(RecoveryInvestigationHypothesis).where(
                RecoveryInvestigationHypothesis.session_id == session_id,
                RecoveryInvestigationHypothesis.hypothesis_key == update.key,
            ),
        )
        record = result.scalar_one_or_none()
        if record is None:
            record = RecoveryInvestigationHypothesis(
                session_id=session_id,
                hypothesis_key=update.key,
                claim=update.claim,
                status=update.status.value,
                first_step=sequence_number,
                last_step=sequence_number,
                version=1,
            )
            session.add(record)
        else:
            record.version += 1
        record.claim = update.claim
        record.status = update.status.value
        record.supporting_evidence_ids = list(update.supporting_evidence_ids)
        record.contradicting_evidence_ids = list(update.contradicting_evidence_ids)
        record.missing_questions = list(update.missing_questions)
        record.next_observation = update.next_observation
        record.last_step = sequence_number


async def run_shadow_investigation(
    session_factory: SessionFactory,
    *,
    recovery_case_id: UUID,
    provider: EvidenceInvestigatorProvider | None,
    started_at: datetime | None = None,
    budgets: InvestigationBudgets | None = None,
) -> RecoveryInvestigationResult:
    """Run one idempotent investigation without creating any recovery side effect."""
    began = started_at or datetime.now(UTC)
    budgets = budgets or InvestigationBudgets()
    if began.tzinfo is None or began.utcoffset() is None:
        raise ValueError("Investigation start time must be timezone-aware")
    record, claimed = await _create_or_load_session(
        session_factory,
        recovery_case_id=recovery_case_id,
        provider=provider,
        started_at=began,
        budgets=budgets,
    )
    if not claimed or record.status != InvestigationStatus.RUNNING.value:
        return _as_result(record)
    if provider is None:
        return await _finish(
            session_factory,
            session_id=record.id,
            status=InvestigationStatus.FALLBACK,
            reason="provider_unavailable",
            completed_at=datetime.now(UTC),
            summary="No model investigation ran; deterministic policy remains authoritative.",
        )

    observations: list[dict[str, object]] = []
    known_evidence: set[str] = set()
    tool_calls = retries = total_tokens = sequence = 0
    while True:
        now = datetime.now(UTC)
        if now - began >= budgets.max_duration:
            return await _finish(
                session_factory,
                session_id=record.id,
                status=InvestigationStatus.FALLBACK,
                reason="duration_budget_exhausted",
                completed_at=now,
                summary="Investigation stopped safely at its wall-clock budget.",
                evidence_ids=tuple(sorted(known_evidence)),
            )
        request: dict[str, object] = {
            "objective": (
                "Determine what payment evidence supports, contradicts, or leaves unresolved."
            ),
            "case": {
                "id": str(recovery_case_id),
                "version": record.case_version,
                "truth_snapshot_id": str(record.truth_snapshot_id),
                "truth_version": record.truth_version,
                "evidence_cutoff_at": record.evidence_cutoff_at.isoformat(),
            },
            "tools": public_tool_catalog(),
            "observations": observations,
            "budgets_remaining": {
                "tool_calls": budgets.max_tool_calls - tool_calls,
                "model_retries": budgets.max_model_retries - retries,
                "tokens": budgets.max_total_tokens - total_tokens,
            },
            "response_contract": "call one tool, complete with citations, or abstain",
        }
        try:
            remaining = max(
                0.001,
                (budgets.max_duration - (datetime.now(UTC) - began)).total_seconds(),
            )
            async with asyncio.timeout(remaining):
                response = await provider.next_turn(request)
            turn = _parse_turn(response)
            total_tokens += (response.input_token_count or 0) + (response.output_token_count or 0)
            if total_tokens > budgets.max_total_tokens:
                return await _finish(
                    session_factory,
                    session_id=record.id,
                    status=InvestigationStatus.FALLBACK,
                    reason="token_budget_exhausted",
                    completed_at=datetime.now(UTC),
                    summary="Investigation stopped safely at its token budget.",
                    evidence_ids=tuple(sorted(known_evidence)),
                )
            _validate_citations(turn, known_evidence)
        except TimeoutError:
            return await _finish(
                session_factory,
                session_id=record.id,
                status=InvestigationStatus.FALLBACK,
                reason="duration_budget_exhausted",
                completed_at=datetime.now(UTC),
                summary="Investigation stopped safely at its wall-clock budget.",
                evidence_ids=tuple(sorted(known_evidence)),
            )
        except Exception as error:  # noqa: BLE001 - explicit bounded provider boundary
            retries += 1
            if retries <= budgets.max_model_retries:
                continue
            return await _finish(
                session_factory,
                session_id=record.id,
                status=InvestigationStatus.FALLBACK,
                reason=f"model_retry_budget_exhausted:{type(error).__name__}",
                completed_at=datetime.now(UTC),
                summary="Model output was invalid; deterministic policy remains authoritative.",
                evidence_ids=tuple(sorted(known_evidence)),
            )

        async with session_factory.begin() as session:
            current = await session.get(
                RecoveryInvestigationSession, record.id, with_for_update=True
            )
            if current is None:
                raise RuntimeError("Investigation session disappeared")
            current_case_version = await session.scalar(
                select(RecoveryCase.version).where(RecoveryCase.id == recovery_case_id),
            )
            if current_case_version != record.case_version:
                current.status = InvestigationStatus.FAILED_SAFE.value
                current.terminal_reason = "superseded_by_new_evidence"
                current.completed_at = datetime.now(UTC)
                await session.flush()
                return _as_result(current)
            current.model_name = response.model_name
            current.model_version = response.model_version or response.model_name
            current.input_token_count += response.input_token_count or 0
            current.output_token_count += response.output_token_count or 0

            if turn.action is not InvestigationTurnAction.CALL_TOOL:
                await _persist_hypotheses(session, current.id, sequence, turn)
                status = (
                    InvestigationStatus.COMPLETED
                    if turn.action is InvestigationTurnAction.COMPLETE
                    else InvestigationStatus.ABSTAINED
                )
                current.status = status.value
                current.terminal_reason = (
                    "evidence_conclusion"
                    if status is InvestigationStatus.COMPLETED
                    else "model_abstained"
                )
                current.result_summary = turn.summary or turn.abstention_reason
                current.result_evidence_ids = list(turn.evidence_ids)
                current.result_digest = _digest(turn.model_dump(mode="json"))
                current.completed_at = datetime.now(UTC)
                await session.flush()
                return _as_result(current)

            if tool_calls >= budgets.max_tool_calls:
                current.status = InvestigationStatus.FALLBACK.value
                current.terminal_reason = "tool_budget_exhausted"
                current.result_summary = "Investigation stopped safely at its tool-call budget."
                current.result_evidence_ids = sorted(known_evidence)
                current.result_digest = _digest(current.result_evidence_ids)
                current.completed_at = datetime.now(UTC)
                await session.flush()
                return _as_result(current)

            sequence += 1
            tool_calls += 1
            tool_started = datetime.now(UTC)
            try:
                remaining = max(
                    0.001,
                    (budgets.max_duration - (datetime.now(UTC) - began)).total_seconds(),
                )
                async with asyncio.timeout(min(TOOL_TIMEOUT_SECONDS, remaining)):
                    observation = await execute_investigation_tool(
                        session,
                        recovery_case_id=recovery_case_id,
                        evidence_cutoff_at=record.evidence_cutoff_at,
                        tool_name=turn.tool_name or "",
                        arguments=turn.tool_arguments or {},
                        started_at=tool_started,
                    )
            except InvestigationToolRejectedError as error:
                current.status = InvestigationStatus.FAILED_SAFE.value
                current.terminal_reason = "tool_request_rejected"
                current.result_summary = str(error)
                current.completed_at = datetime.now(UTC)
                await session.flush()
                return _as_result(current)
            except TimeoutError:
                current.status = InvestigationStatus.FAILED_SAFE.value
                current.terminal_reason = "tool_timeout"
                current.result_summary = "Read-only evidence tool timed out."
                current.completed_at = datetime.now(UTC)
                await session.flush()
                return _as_result(current)
            except Exception as error:  # noqa: BLE001 - fail closed at the tool boundary
                current.status = InvestigationStatus.FAILED_SAFE.value
                current.terminal_reason = f"tool_failed:{type(error).__name__}"
                current.result_summary = "Read-only evidence retrieval failed safely."
                current.completed_at = datetime.now(UTC)
                await session.flush()
                return _as_result(current)

            current.tool_call_count = tool_calls
            await _persist_hypotheses(session, current.id, sequence, turn)
            session.add(
                RecoveryInvestigationStep(
                    session_id=current.id,
                    sequence_number=sequence,
                    tool_name=observation.tool_name,
                    arguments=turn.tool_arguments or {},
                    outcome=observation.outcome.value,
                    evidence_ids=list(observation.evidence_ids),
                    output_payload=observation.payload,
                    error_code=observation.error_code,
                    model_response_digest=_digest(turn.model_dump(mode="json")),
                    input_token_count=response.input_token_count,
                    output_token_count=response.output_token_count,
                    cumulative_tool_calls=tool_calls,
                    cumulative_total_tokens=total_tokens,
                    elapsed_ms=int((observation.completed_at - began).total_seconds() * 1000),
                    started_at=observation.started_at,
                    completed_at=observation.completed_at,
                ),
            )
            known_evidence.update(observation.evidence_ids)
            observations.append(
                {
                    "sequence": sequence,
                    "tool": observation.tool_name,
                    "outcome": observation.outcome.value,
                    "evidence_ids": observation.evidence_ids,
                    "payload": observation.payload,
                },
            )
