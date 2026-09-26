"""Allow-listed read-only evidence tools for recovery investigation."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final
from uuid import UUID

from pydantic import BaseModel, ConfigDict, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.incident import RevenueIncident
from app.db.models.payment_truth import PaymentEvidenceRecord, PaymentTruthSnapshotRecord
from app.db.models.recovery import RecoveryCase
from app.domain.investigation import InvestigationToolObservation, InvestigationToolOutcome

TOOL_REGISTRY_VERSION: Final = "recovery-read-tools-v1"
TOOL_TIMEOUT_SECONDS: Final = 5.0


class InvestigationToolRejectedError(ValueError):
    pass


class CaseToolArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")
    case_id: UUID


@dataclass(frozen=True, slots=True)
class InvestigationToolSpec:
    name: str
    description: str
    input_schema: dict[str, object]
    output_schema: dict[str, object]
    mutates_state: bool = False


TOOL_OUTPUT_SCHEMA: Final[dict[str, object]] = {
    "type": "object",
    "additionalProperties": True,
    "required": ["evidence_ids", "payload"],
    "properties": {
        "evidence_ids": {"type": "array", "items": {"type": "string"}},
        "payload": {"type": "object"},
    },
}


def _spec(name: str, description: str) -> InvestigationToolSpec:
    return InvestigationToolSpec(
        name=name,
        description=description,
        input_schema=CaseToolArguments.model_json_schema(),
        output_schema=TOOL_OUTPUT_SCHEMA,
    )


TOOL_SPECS: Final = (
    _spec("get_truth_snapshot", "Read current versioned payment truth"),
    _spec("get_provider_payment", "Read ledgered Razorpay payment observations"),
    _spec("get_provider_order", "Read ledgered Razorpay order observations"),
    _spec("get_verified_webhooks", "Read verified signed webhook evidence"),
    _spec("get_internal_payment", "Read merchant payment projection evidence"),
    _spec("get_recovery_history", "Read prior recovery evidence"),
    _spec("get_payment_link_status", "Read recovery-link evidence"),
    _spec("get_route_health", "Read case-linked rail incident evidence"),
    _spec("get_merchant_policy_summary", "Read non-sensitive recovery capability summary"),
    _spec("get_customer_contact_capabilities", "Read consent capability without contact values"),
    _spec("get_similar_outcomes", "Read merchant-scoped aggregate outcomes when scope exists"),
)

_TOOLS_BY_NAME: Final = {spec.name: spec for spec in TOOL_SPECS}
_SENSITIVE_KEYS: Final = frozenset(
    {"email", "phone", "mobile", "contact", "token", "secret", "authorization", "api_key"},
)


def public_tool_catalog() -> tuple[dict[str, object], ...]:
    return tuple(
        {
            "name": spec.name,
            "description": spec.description,
            "input_schema": spec.input_schema,
            "output_schema": spec.output_schema,
            "read_only": not spec.mutates_state,
            "timeout_seconds": TOOL_TIMEOUT_SECONDS,
        }
        for spec in TOOL_SPECS
    )


def _redact(value: object) -> object:
    if isinstance(value, Mapping):
        return {
            str(key): "[REDACTED]"
            if any(marker in str(key).casefold() for marker in _SENSITIVE_KEYS)
            else _redact(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_redact(item) for item in value]
    return value


def _evidence_payload(record: PaymentEvidenceRecord) -> dict[str, object]:
    return {
        "evidence_id": str(record.id),
        "source": record.source,
        "fact": record.fact_name,
        "value": record.fact_value,
        "event_at": record.event_at.isoformat() if record.event_at else None,
        "observed_at": record.observed_at.isoformat(),
        "fresh_until": record.fresh_until.isoformat() if record.fresh_until else None,
        "verified": record.verified,
        "signature_verified": record.signature_verified,
        "reliability": record.reliability,
        "unavailable_reason": record.unavailable_reason,
        "normalized_fields": _redact(record.normalized_fields),
    }


async def _load_case(session: AsyncSession, case_id: UUID) -> RecoveryCase:
    result = await session.execute(select(RecoveryCase).where(RecoveryCase.id == case_id))
    recovery_case = result.scalar_one_or_none()
    if recovery_case is None:
        raise InvestigationToolRejectedError("Recovery case does not exist")
    return recovery_case


async def _ledger_observation(
    session: AsyncSession,
    *,
    recovery_case: RecoveryCase,
    tool_name: str,
    cutoff_at: datetime,
    sources: tuple[str, ...],
    require_signature: bool = False,
) -> tuple[tuple[str, ...], dict[str, object]]:
    filters = [
        PaymentEvidenceRecord.payment_attempt_id == recovery_case.payment_attempt_id,
        PaymentEvidenceRecord.observed_at <= cutoff_at,
        PaymentEvidenceRecord.source.in_(sources),
    ]
    if require_signature:
        filters.extend(
            [
                PaymentEvidenceRecord.verified.is_(True),
                PaymentEvidenceRecord.signature_verified.is_(True),
            ],
        )
    result = await session.execute(
        select(PaymentEvidenceRecord)
        .where(*filters)
        .order_by(PaymentEvidenceRecord.observed_at.desc(), PaymentEvidenceRecord.id)
        .limit(25),
    )
    records = tuple(result.scalars().all())
    return (
        tuple(str(record.id) for record in records),
        {"tool": tool_name, "observations": [_evidence_payload(record) for record in records]},
    )


async def execute_investigation_tool(
    session: AsyncSession,
    *,
    recovery_case_id: UUID,
    evidence_cutoff_at: datetime,
    tool_name: str,
    arguments: Mapping[str, object],
    started_at: datetime | None = None,
) -> InvestigationToolObservation:
    if evidence_cutoff_at.tzinfo is None or evidence_cutoff_at.utcoffset() is None:
        raise ValueError("Evidence cutoff must be timezone-aware")
    spec = _TOOLS_BY_NAME.get(tool_name)
    if spec is None or spec.mutates_state:
        raise InvestigationToolRejectedError("Tool is not in the read-only allow-list")
    try:
        parsed = CaseToolArguments.model_validate(dict(arguments))
    except ValidationError as error:
        raise InvestigationToolRejectedError("Tool arguments failed strict validation") from error
    if parsed.case_id != recovery_case_id:
        raise InvestigationToolRejectedError("Tool arguments do not belong to this recovery case")

    began = started_at or datetime.now(UTC)
    recovery_case = await _load_case(session, recovery_case_id)
    source_map = {
        "get_provider_payment": ("provider_payment_api",),
        "get_provider_order": ("provider_order_api",),
        "get_verified_webhooks": ("verified_webhook",),
        "get_internal_payment": ("merchant_database", "payment_lab"),
        "get_recovery_history": ("recovery_state", "reconciliation", "recovery_link"),
        "get_payment_link_status": ("recovery_link",),
    }
    evidence_ids: tuple[str, ...]
    payload: dict[str, object]
    if tool_name in source_map:
        evidence_ids, payload = await _ledger_observation(
            session,
            recovery_case=recovery_case,
            tool_name=tool_name,
            cutoff_at=evidence_cutoff_at,
            sources=source_map[tool_name],
            require_signature=tool_name == "get_verified_webhooks",
        )
    elif tool_name == "get_truth_snapshot":
        result = await session.execute(
            select(PaymentTruthSnapshotRecord)
            .where(
                PaymentTruthSnapshotRecord.payment_attempt_id == recovery_case.payment_attempt_id,
                PaymentTruthSnapshotRecord.resolved_at <= evidence_cutoff_at,
            )
            .order_by(PaymentTruthSnapshotRecord.version.desc())
            .limit(1),
        )
        truth = result.scalar_one_or_none()
        if truth is None:
            evidence_ids, payload = (), {"available": False, "reason": "no_truth_before_cutoff"}
        else:
            evidence_ids = tuple(dict.fromkeys([f"truth:{truth.id}", *truth.evidence_refs]))
            payload = {
                "truth_snapshot_id": str(truth.id),
                "version": truth.version,
                "state": truth.state,
                "evidence_ids": list(truth.evidence_refs),
                "conflict_codes": list(truth.conflict_codes),
                "resolved_at": truth.resolved_at.isoformat(),
                "resolver_version": truth.resolver_version,
            }
    elif tool_name == "get_route_health":
        incident: RevenueIncident | None = None
        if recovery_case.source_incident_id is not None:
            incident_result = await session.execute(
                select(RevenueIncident).where(
                    RevenueIncident.id == recovery_case.source_incident_id,
                    RevenueIncident.last_detected_at <= evidence_cutoff_at,
                ),
            )
            incident = incident_result.scalar_one_or_none()
        if incident is None:
            evidence_ids, payload = (), {"available": False, "reason": "no_case_linked_incident"}
        else:
            evidence_ids = (f"incident:{incident.id}",)
            payload = {
                "incident_id": str(incident.id),
                "status": incident.status,
                "severity": incident.severity,
                "scope": incident.scope,
                "dimension": incident.dimension_value,
                "last_detected_at": incident.last_detected_at.isoformat(),
            }
    elif tool_name == "get_merchant_policy_summary":
        evidence_ids = (f"policy:{TOOL_REGISTRY_VERSION}",)
        payload = {
            "customer_contact_requires_consent": True,
            "payment_truth_required": True,
            "human_approval_may_be_required": True,
            "ai_can_authorize": False,
            "provider_mutation_allowed": False,
        }
    elif tool_name == "get_customer_contact_capabilities":
        evidence_ids = (f"case:{recovery_case.id}:v{recovery_case.version}",)
        payload = {
            "contact_permitted": recovery_case.customer_contact_allowed,
            "raw_contact_data_exposed": False,
        }
    else:
        evidence_ids, payload = (), {"available": False, "reason": "merchant_scope_unavailable"}

    completed = datetime.now(UTC)
    outcome = (
        InvestigationToolOutcome.SUCCEEDED if evidence_ids else InvestigationToolOutcome.UNAVAILABLE
    )
    return InvestigationToolObservation(
        tool_name=tool_name,
        outcome=outcome,
        evidence_ids=evidence_ids,
        payload=payload,
        started_at=began,
        completed_at=completed,
        error_code=None if evidence_ids else str(payload.get("reason", "unavailable")),
    )
