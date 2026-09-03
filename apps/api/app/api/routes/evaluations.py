from dataclasses import asdict
from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_database_session
from app.db.models.evaluation import EvaluationRun, EvaluationScenario
from app.services.evaluation_service import (
    SYNTHETIC_PROVENANCE,
    create_or_load_controlled_evaluation,
    load_evaluation_metrics,
)

DatabaseSessionDependency = Annotated[AsyncSession, Depends(get_database_session)]
router = APIRouter(prefix="/recovery/evaluations", tags=["recovery-evaluations"])


class EvaluationMetricsResponse(BaseModel):
    payments_evaluated: int = Field(ge=0)
    failed_or_at_risk: int = Field(ge=0)
    recovery_eligible: int = Field(ge=0)
    recovery_attempted: int = Field(ge=0)
    successfully_recovered: int = Field(ge=0)
    recovered_minor: int = Field(ge=0)
    baseline_recovered_minor: int = Field(ge=0)
    incremental_recovered_minor: int = Field(ge=0)
    pending_minor: int = Field(ge=0)
    unsafe_actions_blocked: int = Field(ge=0)
    duplicate_recovery_blocked: int = Field(ge=0)
    late_authorization_stops: int = Field(ge=0)
    recovery_rate_percent: float = Field(ge=0, le=100)


class EvaluationRunResponse(BaseModel):
    evaluation_run_id: UUID
    label: str
    provenance: str
    financial_scope: str
    currency: str
    scenario_count: int
    audit_root_hash: str
    metrics: EvaluationMetricsResponse


class EvaluationScenarioResponse(BaseModel):
    scenario_number: int
    scenario_key: str
    payment_method: str
    original_amount_minor: int
    at_risk: bool
    eligible: bool
    attempted: bool
    outcome: str
    observed_condition: str | None
    agent_recommendation: str | None
    proposed_action: str | None
    expected_policy_outcome: str | None
    policy_outcome: str
    policy_explanation: str | None
    execution_status: str | None
    guardrails: list[str]
    recovered_minor: int
    control_recovered_minor: int
    pending_minor: int
    protected_minor: int
    decision_latency_ms: int
    audit_event_hash: str
    evaluated_at: datetime


def response(run: EvaluationRun, metrics: object) -> EvaluationRunResponse:
    return EvaluationRunResponse(
        evaluation_run_id=run.id,
        label=run.label,
        provenance=SYNTHETIC_PROVENANCE,
        financial_scope="not_production_merchant_revenue",
        currency=run.currency,
        scenario_count=run.scenario_count,
        audit_root_hash=run.audit_root_hash,
        metrics=EvaluationMetricsResponse(**asdict(metrics)),
    )


@router.post(
    "/controlled-batch", response_model=EvaluationRunResponse, status_code=status.HTTP_201_CREATED
)
async def create_controlled_batch(session: DatabaseSessionDependency) -> EvaluationRunResponse:
    run = await create_or_load_controlled_evaluation(session)
    await session.commit()
    return response(run, await load_evaluation_metrics(session, run=run))


@router.get("/{evaluation_run_id}", response_model=EvaluationRunResponse)
async def get_evaluation_run(
    evaluation_run_id: UUID, session: DatabaseSessionDependency
) -> EvaluationRunResponse:
    run = (
        await session.execute(select(EvaluationRun).where(EvaluationRun.id == evaluation_run_id))
    ).scalar_one_or_none()
    if run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Evaluation run not found"
        )
    return response(run, await load_evaluation_metrics(session, run=run))


@router.get("/{evaluation_run_id}/scenarios", response_model=list[EvaluationScenarioResponse])
async def list_evaluation_scenarios(
    evaluation_run_id: UUID,
    session: DatabaseSessionDependency,
) -> list[EvaluationScenarioResponse]:
    rows = (
        (
            await session.execute(
                select(EvaluationScenario)
                .where(EvaluationScenario.evaluation_run_id == evaluation_run_id)
                .order_by(EvaluationScenario.scenario_number),
            )
        )
        .scalars()
        .all()
    )
    return [
        EvaluationScenarioResponse(
            scenario_number=row.scenario_number,
            scenario_key=row.scenario_key,
            payment_method=row.payment_method,
            original_amount_minor=row.original_amount_minor,
            at_risk=row.at_risk,
            eligible=row.eligible,
            attempted=row.attempted,
            outcome=row.outcome,
            observed_condition=row.observed_condition,
            agent_recommendation=row.agent_recommendation,
            proposed_action=row.proposed_action,
            expected_policy_outcome=row.expected_policy_outcome,
            policy_outcome=row.policy_outcome,
            policy_explanation=row.policy_explanation,
            execution_status=row.execution_status,
            guardrails=list(row.guardrails),
            recovered_minor=row.recovered_minor,
            control_recovered_minor=row.control_recovered_minor,
            pending_minor=row.pending_minor,
            protected_minor=row.protected_minor,
            decision_latency_ms=row.decision_latency_ms,
            audit_event_hash=row.audit_event_hash,
            evaluated_at=row.evaluated_at,
        )
        for row in rows
    ]
