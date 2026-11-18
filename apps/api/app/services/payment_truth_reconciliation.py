import hashlib
import json
from collections.abc import Collection
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import and_, func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models.payment import PaymentAttempt
from app.db.models.payment_truth import (
    PaymentTruthReconciliationState,
    PaymentTruthSnapshotRecord,
)
from app.db.models.webhook import WebhookEvent, WebhookProcessingStatus
from app.domain.recovery.contracts import PaymentEvidenceSource, PaymentTruthState
from app.integrations.razorpay.orders import (
    RazorpayOrderPayment,
    RazorpayOrderProvider,
    RazorpayOrderProviderError,
)
from app.services.payment_truth_service import (
    PaymentEvidenceWrite,
    canonical_sha256,
    record_payment_evidence,
    resolve_and_persist_payment_truth,
)
from app.services.payment_webhook_processor import (
    PaymentWebhookDisposition,
    process_canonical_payment_webhook,
)

SessionFactory = async_sessionmaker[AsyncSession]
RECONCILE_AFTER = timedelta(minutes=2)
CIRCUIT_FAILURE_THRESHOLD = 3
DEFAULT_RETRY_BASE_DELAY = timedelta(seconds=15)
DEFAULT_RETRY_MAXIMUM_DELAY = timedelta(minutes=5)
DEFAULT_MAX_ATTEMPTS = 5
DEFAULT_CIRCUIT_OPEN_DURATION = timedelta(minutes=5)
CONTROLLED_SYNTHETIC_EVIDENCE_SOURCES = frozenset(
    {
        "controlled_synthetic",
        "synthetic_test_fixture",
    }
)


@dataclass(frozen=True, slots=True)
class PaymentTruthReconciliationResult:
    checked: int
    projected: int
    unchanged: int
    unavailable: int
    persistence_failures: int
    circuit_opened: bool
    deferred: int = 0
    exhausted: int = 0
    synthetic_blocked: int = 0
    provider_calls: int = 0
    cooling_down_controls: int = 0
    open_circuit_controls: int = 0
    exhausted_controls: int = 0
    synthetic_blocked_controls: int = 0


@dataclass(frozen=True, slots=True)
class PaymentTruthReconciliationControlCounts:
    cooling_down: int
    open_circuits: int
    exhausted: int
    synthetic_blocked: int


class ProviderEvidencePersistenceError(RuntimeError):
    """Provider responded, but the local evidence transaction did not commit."""


def _retry_delay(
    *,
    failure_count: int,
    base_delay: timedelta,
    maximum_delay: timedelta,
) -> timedelta:
    if failure_count < 1:
        raise ValueError("Failure count must be positive")
    if base_delay <= timedelta(0) or maximum_delay <= timedelta(0):
        raise ValueError("Reconciliation retry delays must be positive")
    if maximum_delay < base_delay:
        raise ValueError("Reconciliation retry maximum must not be lower than base")
    multiplier = 2 ** min(failure_count - 1, 30)
    candidate = base_delay * multiplier
    return maximum_delay if candidate > maximum_delay else candidate


def _failure_fingerprint(error: RazorpayOrderProviderError) -> str:
    return canonical_sha256(
        {
            "provider": "razorpay",
            "failure_kind": error.kind.value,
            "status_code": error.status_code,
            "retryable": error.retryable,
        },
    )


def _unavailable_source_reference(
    *,
    payment_attempt_id: UUID,
    payment_state_version: int,
    observation_sequence: int,
    failure_fingerprint: str,
) -> str:
    return (
        f"provider-unavailable:{payment_attempt_id}:state-v{payment_state_version}:"
        f"observation-{observation_sequence}:{failure_fingerprint[:16]}"
    )


def _reset_reconciliation_state(
    state: PaymentTruthReconciliationState,
    *,
    payment_state_version: int,
) -> None:
    state.payment_state_version = payment_state_version
    state.attempt_count = 0
    state.consecutive_failures = 0
    state.observation_sequence = 0
    state.next_retry_at = None
    state.circuit_open_until = None
    state.exhausted_at = None
    state.blocked_reason = None
    state.last_attempt_at = None
    state.last_failure_at = None
    state.last_success_at = None
    state.last_failure_fingerprint = None


async def _load_reconciliation_state(
    session: AsyncSession,
    *,
    attempt: PaymentAttempt,
) -> PaymentTruthReconciliationState:
    await session.execute(
        insert(PaymentTruthReconciliationState)
        .values(
            payment_attempt_id=attempt.id,
            payment_state_version=attempt.state_version,
        )
        .on_conflict_do_nothing(index_elements=["payment_attempt_id"]),
    )
    state = await session.scalar(
        select(PaymentTruthReconciliationState)
        .where(PaymentTruthReconciliationState.payment_attempt_id == attempt.id)
        .with_for_update(),
    )
    if state is None:
        raise RuntimeError("Payment truth reconciliation state was not persisted")
    if state.payment_state_version != attempt.state_version:
        _reset_reconciliation_state(
            state,
            payment_state_version=attempt.state_version,
        )
    return state


async def _is_controlled_synthetic(
    session: AsyncSession,
    *,
    attempt: PaymentAttempt,
) -> bool:
    event = await session.get(WebhookEvent, attempt.state_webhook_event_id)
    if event is None or not isinstance(event.payload, dict):
        return False
    raw_source = event.payload.get("reclaimrail_evidence_source")
    return (
        isinstance(raw_source, str)
        and raw_source.strip().casefold() in CONTROLLED_SYNTHETIC_EVIDENCE_SOURCES
    )


def _defer_reason(
    state: PaymentTruthReconciliationState,
    *,
    reference_time: datetime,
) -> str | None:
    if state.exhausted_at is not None:
        if state.blocked_reason == "controlled_synthetic":
            return "synthetic_blocked"
        return "exhausted"
    if state.circuit_open_until is not None and state.circuit_open_until > reference_time:
        return "deferred"
    if state.next_retry_at is not None and state.next_retry_at > reference_time:
        return "deferred"
    return None


def _record_provider_success(
    state: PaymentTruthReconciliationState,
    *,
    observed_at: datetime,
) -> None:
    state.attempt_count = 0
    state.consecutive_failures = 0
    state.next_retry_at = observed_at + RECONCILE_AFTER
    state.circuit_open_until = None
    state.exhausted_at = None
    state.blocked_reason = None
    state.last_attempt_at = observed_at
    state.last_success_at = observed_at
    state.last_failure_fingerprint = None


async def _candidate_ids(
    session: AsyncSession,
    *,
    reference_time: datetime,
    batch_size: int,
    payment_attempt_ids: Collection[UUID] | None = None,
) -> tuple[UUID, ...]:
    latest_versions = (
        select(
            PaymentTruthSnapshotRecord.payment_attempt_id.label("attempt_id"),
            func.max(PaymentTruthSnapshotRecord.version).label("version"),
        )
        .group_by(PaymentTruthSnapshotRecord.payment_attempt_id)
        .subquery()
    )
    latest = (
        select(PaymentTruthSnapshotRecord)
        .join(
            latest_versions,
            and_(
                PaymentTruthSnapshotRecord.payment_attempt_id == latest_versions.c.attempt_id,
                PaymentTruthSnapshotRecord.version == latest_versions.c.version,
            ),
        )
        .subquery()
    )
    control = PaymentTruthReconciliationState
    statement = (
        select(PaymentAttempt.id)
        .outerjoin(latest, latest.c.payment_attempt_id == PaymentAttempt.id)
        .outerjoin(control, control.payment_attempt_id == PaymentAttempt.id)
        .where(
            PaymentAttempt.provider == "razorpay",
            PaymentAttempt.provider_order_id.is_not(None),
            or_(
                latest.c.id.is_(None),
                latest.c.state.in_(
                    (
                        PaymentTruthState.OUTCOME_UNKNOWN.value,
                        PaymentTruthState.SOURCE_CONFLICT.value,
                        PaymentTruthState.MANUAL_INVESTIGATION_REQUIRED.value,
                        PaymentTruthState.PAYMENT_PENDING.value,
                    ),
                ),
                latest.c.resolved_at <= reference_time - RECONCILE_AFTER,
            ),
            or_(
                control.payment_attempt_id.is_(None),
                control.payment_state_version != PaymentAttempt.state_version,
                and_(
                    control.exhausted_at.is_(None),
                    or_(
                        control.next_retry_at.is_(None),
                        control.next_retry_at <= reference_time,
                    ),
                    or_(
                        control.circuit_open_until.is_(None),
                        control.circuit_open_until <= reference_time,
                    ),
                ),
            ),
        )
        .order_by(PaymentAttempt.updated_at)
        .limit(batch_size)
    )
    if payment_attempt_ids is not None:
        if not payment_attempt_ids:
            return ()
        statement = statement.where(PaymentAttempt.id.in_(payment_attempt_ids))
    result = await session.execute(statement)
    return tuple(result.scalars())


async def _control_counts(
    session: AsyncSession,
    *,
    reference_time: datetime,
) -> PaymentTruthReconciliationControlCounts:
    result = await session.execute(
        select(
            func.count().filter(
                PaymentTruthReconciliationState.exhausted_at.is_(None),
                PaymentTruthReconciliationState.next_retry_at > reference_time,
            ),
            func.count().filter(
                PaymentTruthReconciliationState.exhausted_at.is_(None),
                PaymentTruthReconciliationState.circuit_open_until > reference_time,
            ),
            func.count().filter(
                PaymentTruthReconciliationState.exhausted_at.is_not(None),
            ),
            func.count().filter(
                PaymentTruthReconciliationState.blocked_reason == "controlled_synthetic",
            ),
        ),
    )
    cooling_down, open_circuits, exhausted, synthetic_blocked = result.one()
    return PaymentTruthReconciliationControlCounts(
        cooling_down=int(cooling_down or 0),
        open_circuits=int(open_circuits or 0),
        exhausted=int(exhausted or 0),
        synthetic_blocked=int(synthetic_blocked or 0),
    )


async def _record_unavailable(
    session: AsyncSession,
    *,
    attempt: PaymentAttempt,
    state: PaymentTruthReconciliationState,
    error: RazorpayOrderProviderError,
    observed_at: datetime,
    retry_base_delay: timedelta,
    retry_maximum_delay: timedelta,
    max_attempts: int,
    circuit_failure_threshold: int,
    circuit_open_duration: timedelta,
) -> tuple[bool, bool]:
    retry_attempt = state.attempt_count + 1
    observation_sequence = state.observation_sequence + 1
    failure_fingerprint = _failure_fingerprint(error)
    retry_delay = _retry_delay(
        failure_count=retry_attempt,
        base_delay=retry_base_delay,
        maximum_delay=retry_maximum_delay,
    )
    exhausted = not error.retryable or retry_attempt >= max_attempts
    circuit_opened = state.consecutive_failures + 1 >= circuit_failure_threshold

    state.attempt_count = retry_attempt
    state.consecutive_failures += 1
    state.observation_sequence = observation_sequence
    state.last_attempt_at = observed_at
    state.last_failure_at = observed_at
    state.last_failure_fingerprint = failure_fingerprint
    state.exhausted_at = observed_at if exhausted else None
    state.blocked_reason = "retry_budget_exhausted" if exhausted else None
    state.next_retry_at = None if exhausted else observed_at + retry_delay
    state.circuit_open_until = (
        observed_at + circuit_open_duration if circuit_opened and not exhausted else None
    )

    freshness = max(
        RECONCILE_AFTER,
        retry_delay,
        circuit_open_duration if circuit_opened else timedelta(0),
    )
    payload: dict[str, object] = {
        "provider": "razorpay",
        "order_id": attempt.provider_order_id,
        "failure_kind": error.kind.value,
        "status_code": error.status_code,
        "retryable": error.retryable,
        "payment_state_version": attempt.state_version,
        "retry_attempt": retry_attempt,
        "observation_sequence": observation_sequence,
        "retry_budget": max_attempts,
        "circuit_opened": circuit_opened,
        "exhausted": exhausted,
    }
    await record_payment_evidence(
        session,
        PaymentEvidenceWrite(
            payment_attempt_id=attempt.id,
            source=PaymentEvidenceSource.RECONCILIATION,
            source_reference=_unavailable_source_reference(
                payment_attempt_id=attempt.id,
                payment_state_version=attempt.state_version,
                observation_sequence=observation_sequence,
                failure_fingerprint=failure_fingerprint,
            ),
            fact_name="provider.available",
            fact_value="false",
            content_sha256=canonical_sha256(payload),
            observed_at=observed_at,
            fresh_until=observed_at + freshness,
            normalized_fields=payload,
            verified=True,
            reliability="authoritative",
            unavailable_reason=error.kind.value,
        ),
    )
    await resolve_and_persist_payment_truth(
        session,
        payment_attempt=attempt,
        resolved_at=observed_at,
    )
    return circuit_opened, exhausted


def _provider_event(payment: RazorpayOrderPayment, observed_at: datetime) -> WebhookEvent:
    payment_entity = payment.model_dump(by_alias=True)
    payment_entity["entity"] = "payment"
    payload: dict[str, object] = {
        "entity": "event",
        "event": f"payment.{payment.status.value}",
        "contains": ["payment"],
        "payload": {"payment": {"entity": payment_entity}},
        "created_at": payment.provider_created_at,
        "reclaimrail_evidence_source": "razorpay_api_verification",
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return WebhookEvent(
        id=uuid4(),
        provider="razorpay",
        provider_event_id=f"provider-api:{payment.payment_id}:{payment.status.value}",
        event_type=f"payment.{payment.status.value}",
        provider_created_at=datetime.fromtimestamp(payment.provider_created_at, tz=UTC),
        payload=payload,
        payload_sha256=hashlib.sha256(raw).hexdigest(),
        processing_status=WebhookProcessingStatus.RECEIVED.value,
        delivery_count=1,
        first_received_at=observed_at,
        last_received_at=observed_at,
    )


async def _reconcile_one(
    session: AsyncSession,
    *,
    attempt_id: UUID,
    provider: RazorpayOrderProvider,
    reference_time: datetime,
    retry_base_delay: timedelta = DEFAULT_RETRY_BASE_DELAY,
    retry_maximum_delay: timedelta = DEFAULT_RETRY_MAXIMUM_DELAY,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    circuit_failure_threshold: int = CIRCUIT_FAILURE_THRESHOLD,
    circuit_open_duration: timedelta = DEFAULT_CIRCUIT_OPEN_DURATION,
) -> str:
    attempt = await session.scalar(
        select(PaymentAttempt).where(PaymentAttempt.id == attempt_id).with_for_update(),
    )
    if attempt is None or attempt.provider_order_id is None:
        return "unchanged"
    state = await _load_reconciliation_state(session, attempt=attempt)
    defer_reason = _defer_reason(state, reference_time=reference_time)
    if defer_reason is not None:
        return defer_reason
    if await _is_controlled_synthetic(session, attempt=attempt):
        state.exhausted_at = reference_time
        state.blocked_reason = "controlled_synthetic"
        state.last_attempt_at = None
        await session.commit()
        return "synthetic_blocked"
    try:
        payments = await provider.fetch_order_payments(attempt.provider_order_id)
    except RazorpayOrderProviderError as error:
        circuit_opened, exhausted = await _record_unavailable(
            session,
            attempt=attempt,
            state=state,
            error=error,
            observed_at=reference_time,
            retry_base_delay=retry_base_delay,
            retry_maximum_delay=retry_maximum_delay,
            max_attempts=max_attempts,
            circuit_failure_threshold=circuit_failure_threshold,
            circuit_open_duration=circuit_open_duration,
        )
        await session.commit()
        if exhausted:
            return "unavailable_exhausted"
        if circuit_opened:
            return "unavailable_circuit"
        return "unavailable"

    _record_provider_success(state, observed_at=reference_time)
    matching = tuple(
        item
        for item in payments
        if item.order_id == attempt.provider_order_id
        and item.amount_minor == attempt.amount_minor
        and item.currency == attempt.currency
        and item.payment_id == attempt.provider_payment_id
    )
    if not matching:
        payload = {
            "order_id": attempt.provider_order_id,
            "payment_id": attempt.provider_payment_id,
            "matching_payment_count": 0,
        }
        await record_payment_evidence(
            session,
            PaymentEvidenceWrite(
                payment_attempt_id=attempt.id,
                source=PaymentEvidenceSource.RECONCILIATION,
                source_reference=f"provider-scan:{attempt.provider_order_id}:{reference_time.isoformat()}",
                fact_name="provider.matching_payment_count",
                fact_value="0",
                content_sha256=canonical_sha256(payload),
                observed_at=reference_time,
                fresh_until=reference_time + RECONCILE_AFTER,
                normalized_fields=payload,
                verified=True,
                reliability="authoritative",
            ),
        )
        await resolve_and_persist_payment_truth(
            session, payment_attempt=attempt, resolved_at=reference_time
        )
        await session.commit()
        return "unchanged"

    payment = max(matching, key=lambda item: item.provider_created_at)
    event_id = f"provider-api:{payment.payment_id}:{payment.status.value}"
    existing = await session.scalar(
        select(WebhookEvent.id).where(
            WebhookEvent.provider == "razorpay",
            WebhookEvent.provider_event_id == event_id,
        ),
    )
    if existing is not None:
        await session.commit()
        return "unchanged"
    event = _provider_event(payment, reference_time)
    try:
        session.add(event)
        await session.flush()
        processing_result = await process_canonical_payment_webhook(
            session,
            event.id,
            processed_at=reference_time,
        )
        if processing_result.disposition is not PaymentWebhookDisposition.PROJECTED:
            raise ProviderEvidencePersistenceError(
                "Provider response could not be projected into canonical payment evidence"
            )
        await session.commit()
    except ProviderEvidencePersistenceError:
        await session.rollback()
        raise
    except Exception as error:
        await session.rollback()
        raise ProviderEvidencePersistenceError(
            "Provider response received but payment evidence persistence failed"
        ) from error
    return "projected"


async def reconcile_payment_truth_batch(
    session_factory: SessionFactory,
    *,
    provider: RazorpayOrderProvider,
    reference_time: datetime,
    batch_size: int,
    retry_base_delay: timedelta = DEFAULT_RETRY_BASE_DELAY,
    retry_maximum_delay: timedelta = DEFAULT_RETRY_MAXIMUM_DELAY,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    circuit_failure_threshold: int = CIRCUIT_FAILURE_THRESHOLD,
    circuit_open_duration: timedelta = DEFAULT_CIRCUIT_OPEN_DURATION,
    payment_attempt_ids: Collection[UUID] | None = None,
) -> PaymentTruthReconciliationResult:
    if reference_time.tzinfo is None or reference_time.utcoffset() is None:
        raise ValueError("Reconciliation time must be timezone-aware")
    if not 1 <= batch_size <= 100:
        raise ValueError("Reconciliation batch size must be between 1 and 100")
    if max_attempts < 1:
        raise ValueError("Reconciliation max attempts must be positive")
    if not 1 <= circuit_failure_threshold <= max_attempts:
        raise ValueError("Circuit failure threshold must fit the retry budget")
    if circuit_open_duration <= timedelta(0):
        raise ValueError("Circuit open duration must be positive")
    _retry_delay(
        failure_count=1,
        base_delay=retry_base_delay,
        maximum_delay=retry_maximum_delay,
    )
    async with session_factory() as session:
        candidate_ids = await _candidate_ids(
            session,
            reference_time=reference_time,
            batch_size=batch_size,
            payment_attempt_ids=payment_attempt_ids,
        )

    projected = unchanged = unavailable = persistence_failures = consecutive_failures = 0
    deferred = exhausted = synthetic_blocked = provider_calls = checked = 0
    circuit_opened = False
    for attempt_id in candidate_ids:
        if consecutive_failures >= circuit_failure_threshold:
            circuit_opened = True
            break
        checked += 1
        try:
            async with session_factory() as session:
                outcome = await _reconcile_one(
                    session,
                    attempt_id=attempt_id,
                    provider=provider,
                    reference_time=reference_time,
                    retry_base_delay=retry_base_delay,
                    retry_maximum_delay=retry_maximum_delay,
                    max_attempts=max_attempts,
                    circuit_failure_threshold=circuit_failure_threshold,
                    circuit_open_duration=circuit_open_duration,
                )
        except RazorpayOrderProviderError:
            provider_calls += 1
            unavailable += 1
            consecutive_failures += 1
            continue
        except ProviderEvidencePersistenceError:
            provider_calls += 1
            persistence_failures += 1
            continue
        if outcome == "deferred":
            deferred += 1
            continue
        if outcome == "exhausted":
            exhausted += 1
            continue
        if outcome == "synthetic_blocked":
            synthetic_blocked += 1
            continue
        if outcome.startswith("unavailable"):
            provider_calls += 1
            unavailable += 1
            consecutive_failures += 1
            if outcome == "unavailable_circuit":
                circuit_opened = True
            if outcome == "unavailable_exhausted":
                circuit_opened = True
                exhausted += 1
            continue
        provider_calls += 1
        consecutive_failures = 0
        if outcome == "projected":
            projected += 1
        else:
            unchanged += 1
    async with session_factory() as session:
        control_counts = await _control_counts(session, reference_time=reference_time)
    return PaymentTruthReconciliationResult(
        checked=checked,
        projected=projected,
        unchanged=unchanged,
        unavailable=unavailable,
        persistence_failures=persistence_failures,
        circuit_opened=circuit_opened,
        deferred=deferred,
        exhausted=exhausted,
        synthetic_blocked=synthetic_blocked,
        provider_calls=provider_calls,
        cooling_down_controls=control_counts.cooling_down,
        open_circuit_controls=control_counts.open_circuits,
        exhausted_controls=control_counts.exhausted,
        synthetic_blocked_controls=control_counts.synthetic_blocked,
    )
