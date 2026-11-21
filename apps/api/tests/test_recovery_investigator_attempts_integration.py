"""Real PostgreSQL coverage for durable investigator-provider receipts.

These tests intentionally exercise the short persistence transactions directly.
Provider doubles never contact an external service.
"""

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.db.models.investigation import (
    RecoveryInvestigationProviderAttempt,
    RecoveryInvestigationSession,
)
from app.db.models.payment import PaymentAttempt
from app.db.models.payment_truth import PaymentTruthSnapshotRecord
from app.db.models.recovery import RecoveryCase
from app.db.models.webhook import WebhookEvent, WebhookProcessingStatus
from app.domain.investigation import InvestigatorProviderResponse, InvestigatorTurn
from app.domain.recovery import RecoveryCaseStatus
from app.integrations.investigator import (
    EvidenceInvestigatorFailureKind,
    EvidenceInvestigatorProviderError,
)
from app.services.recovery_case_detail_service import load_recovery_case_detail
from app.services.recovery_investigator_service import (
    _finalize_provider_attempt,
    _start_provider_attempt,
)

STARTED_AT = datetime(2026, 11, 20, 9, 0, tzinfo=UTC)


@dataclass(frozen=True, slots=True)
class StubProvider:
    provider_name: str
    model_name: str

    async def next_turn(self, request: dict[str, object]) -> InvestigatorProviderResponse:
        raise AssertionError("Provider doubles in persistence tests must not be invoked")


def _success(provider: str = "groq") -> InvestigatorProviderResponse:
    return InvestigatorProviderResponse(
        provider=provider,
        model_name="openai/gpt-oss-120b",
        model_version="test-version",
        input_token_count=17,
        output_token_count=11,
        turn=InvestigatorTurn.model_validate(
            {
                "action": "abstain",
                "abstention_reason": "insufficient evidence",
                "evidence_ids": [],
            }
        ),
    )


async def _make_graph(
    session_factory: async_sessionmaker[AsyncSession],
) -> tuple[UUID, UUID, UUID, UUID, UUID]:
    """Build only the valid graph required by an investigation session."""
    suffix = uuid4().hex
    webhook_id, payment_id, case_id, truth_id, session_id = (uuid4() for _ in range(5))
    webhook = WebhookEvent(
        id=webhook_id,
        provider="razorpay",
        provider_event_id=f"evt_phase17b_attempt_{suffix}",
        event_type="payment.failed",
        account_id="acc_phase17b_attempt_test",
        provider_created_at=STARTED_AT - timedelta(minutes=2),
        payload={"event": "payment.failed"},
        payload_sha256="a" * 64,
        processing_status=WebhookProcessingStatus.PROCESSED.value,
        delivery_count=1,
        first_received_at=STARTED_AT - timedelta(minutes=2),
        last_received_at=STARTED_AT - timedelta(minutes=2),
        processed_at=STARTED_AT - timedelta(minutes=2),
    )
    payment = PaymentAttempt(
        id=payment_id,
        provider="razorpay",
        provider_payment_id=f"pay_phase17b_attempt_{suffix}",
        account_id="acc_phase17b_attempt_test",
        provider_order_id=f"order_phase17b_attempt_{suffix}",
        amount_minor=149_900,
        currency="INR",
        method="upi",
        payment_created_at=STARTED_AT - timedelta(minutes=3),
        current_state="failed",
        state_version=1,
        state_provider_event_id=f"evt_phase17b_attempt_{suffix}",
        state_webhook_event_id=webhook_id,
        state_event_created_at=STARTED_AT - timedelta(minutes=2),
        error_code="BAD_REQUEST_ERROR",
        error_description="Payment failed",
        error_source="customer",
        error_step="payment_authentication",
        error_reason="payment_failed",
        recovery_eligible=True,
    )
    recovery_case = RecoveryCase(
        id=case_id,
        payment_attempt_id=payment_id,
        status=RecoveryCaseStatus.OPEN.value,
        amount_minor=149_900,
        currency="INR",
        payment_method="upi",
        recovery_attempt_count=0,
        version=0,
        customer_contact_allowed=True,
        opened_at=STARTED_AT - timedelta(minutes=1),
    )
    truth = PaymentTruthSnapshotRecord(
        id=truth_id,
        payment_attempt_id=payment_id,
        recovery_case_id=case_id,
        version=1,
        state="payment_failed",
        evidence_refs=["webhook:payment.failed"],
        conflict_codes=[],
        evidence_digest=uuid4().hex + uuid4().hex,
        resolver_version="phase17b-integration",
        resolved_at=STARTED_AT - timedelta(seconds=1),
    )
    investigation = RecoveryInvestigationSession(
        id=session_id,
        recovery_case_id=case_id,
        payment_attempt_id=payment_id,
        truth_snapshot_id=truth_id,
        case_version=0,
        truth_version=1,
        evidence_cutoff_at=STARTED_AT,
        status="running",
        provider="groq",
        model_name=None,
        model_version=None,
        prompt_version="phase17b-integration",
        tool_registry_version="phase17b-integration",
        shadow_mode=True,
        max_tool_calls=2,
        max_model_retries=0,
        max_total_tokens=512,
        max_duration_ms=60_000,
        started_at=STARTED_AT,
    )
    async with session_factory.begin() as session:
        session.add(webhook)
        await session.flush()
        session.add(payment)
        await session.flush()
        session.add(recovery_case)
        await session.flush()
        session.add(truth)
        await session.flush()
        session.add(investigation)
    return webhook_id, payment_id, case_id, truth_id, session_id


async def _cleanup(
    session_factory: async_sessionmaker[AsyncSession],
    webhook_id: UUID,
    payment_id: UUID,
    case_id: UUID,
    truth_id: UUID,
    session_id: UUID,
) -> None:
    async with session_factory.begin() as session:
        await session.execute(
            delete(RecoveryInvestigationProviderAttempt).where(
                RecoveryInvestigationProviderAttempt.session_id == session_id
            )
        )
        await session.execute(
            delete(RecoveryInvestigationSession).where(
                RecoveryInvestigationSession.id == session_id
            )
        )
        await session.execute(
            delete(PaymentTruthSnapshotRecord).where(PaymentTruthSnapshotRecord.id == truth_id)
        )
        await session.execute(delete(RecoveryCase).where(RecoveryCase.id == case_id))
        await session.execute(delete(PaymentAttempt).where(PaymentAttempt.id == payment_id))
        await session.execute(delete(WebhookEvent).where(WebhookEvent.id == webhook_id))


@pytest_asyncio.fixture
async def provider_attempt_graph() -> tuple[
    async_sessionmaker[AsyncSession], tuple[UUID, UUID, UUID, UUID, UUID]
]:
    settings = get_settings()
    if settings.database_url is None or not settings.database_url.get_secret_value():
        pytest.skip("Database URL is not configured")
    engine = create_async_engine(settings.database_url.get_secret_value(), pool_pre_ping=True)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    graph = await _make_graph(factory)
    try:
        yield factory, graph
    finally:
        await _cleanup(factory, *graph)
        await engine.dispose()


@pytest.mark.asyncio
async def test_started_attempt_is_committed_before_blocked_provider_and_remains_visible(
    provider_attempt_graph: tuple[
        async_sessionmaker[AsyncSession], tuple[UUID, UUID, UUID, UUID, UUID]
    ],
) -> None:
    factory, (_, _, _, _, investigation_id) = provider_attempt_graph
    provider = StubProvider("groq", "openai/gpt-oss-120b")
    entered = asyncio.Event()
    release = asyncio.Event()

    async def invoke_after_receipt() -> UUID:
        attempt_id = await _start_provider_attempt(
            factory, session_id=investigation_id, provider=provider
        )
        entered.set()
        await release.wait()
        return attempt_id

    task = asyncio.create_task(invoke_after_receipt())
    await asyncio.wait_for(entered.wait(), timeout=2)
    async with factory() as observer:
        attempts = list(
            (
                await observer.scalars(
                    select(RecoveryInvestigationProviderAttempt).where(
                        RecoveryInvestigationProviderAttempt.session_id == investigation_id
                    )
                )
            ).all()
        )
    assert len(attempts) == 1
    assert attempts[0].status == "started"
    assert attempts[0].completed_at is None
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    async with factory() as observer:
        retained = await observer.scalar(
            select(RecoveryInvestigationProviderAttempt).where(
                RecoveryInvestigationProviderAttempt.session_id == investigation_id
            )
        )
    assert retained is not None
    assert retained.status == "started"
    assert retained.completed_at is None


@pytest.mark.asyncio
async def test_finalization_is_sanitized_idempotent_and_updates_selected_session(
    provider_attempt_graph: tuple[
        async_sessionmaker[AsyncSession], tuple[UUID, UUID, UUID, UUID, UUID]
    ],
) -> None:
    factory, (_, _, _, _, investigation_id) = provider_attempt_graph
    primary = StubProvider("groq", "openai/gpt-oss-120b")
    attempt_id = await _start_provider_attempt(
        factory, session_id=investigation_id, provider=primary
    )
    await _finalize_provider_attempt(factory, attempt_id=attempt_id, response=_success())
    await _finalize_provider_attempt(factory, attempt_id=attempt_id, response=_success("gemini"))
    async with factory() as session:
        attempt = await session.get(RecoveryInvestigationProviderAttempt, attempt_id)
        investigation = await session.get(RecoveryInvestigationSession, investigation_id)
    assert attempt is not None and investigation is not None
    assert attempt.status == "succeeded"
    assert attempt.selected_result is True
    assert attempt.input_token_count == 17
    assert attempt.output_token_count == 11
    assert attempt.returned_model == "openai/gpt-oss-120b"
    assert investigation.provider == "groq"
    assert investigation.model_name == "openai/gpt-oss-120b"

    failed_id = await _start_provider_attempt(
        factory, session_id=investigation_id, provider=primary
    )
    await _finalize_provider_attempt(
        factory,
        attempt_id=failed_id,
        error=EvidenceInvestigatorProviderError(
            "sanitized server failure",
            kind=EvidenceInvestigatorFailureKind.TRANSIENT_PROVIDER,
            retryable=True,
            status_code=503,
        ),
    )
    async with factory() as session:
        failed = await session.get(RecoveryInvestigationProviderAttempt, failed_id)
    assert failed is not None
    assert failed.status == "failed_safe"
    assert failed.failure_kind == "transient_provider"
    assert failed.http_status_code == 503
    assert failed.selected_result is False


@pytest.mark.asyncio
async def test_sequence_allocation_and_failover_receipts_are_ordered_and_preserved(
    provider_attempt_graph: tuple[
        async_sessionmaker[AsyncSession], tuple[UUID, UUID, UUID, UUID, UUID]
    ],
) -> None:
    factory, (_, _, _, _, investigation_id) = provider_attempt_graph
    groq = StubProvider("groq", "openai/gpt-oss-120b")
    gemini = StubProvider("gemini", "gemini-3.6-flash")
    primary_id, secondary_id = await asyncio.gather(
        _start_provider_attempt(factory, session_id=investigation_id, provider=groq),
        _start_provider_attempt(factory, session_id=investigation_id, provider=gemini),
    )
    await _finalize_provider_attempt(
        factory,
        attempt_id=primary_id,
        error=EvidenceInvestigatorProviderError(
            "sanitized timeout",
            kind=EvidenceInvestigatorFailureKind.TIMEOUT,
            retryable=True,
        ),
    )
    await _finalize_provider_attempt(factory, attempt_id=secondary_id, response=_success("gemini"))
    async with factory() as session:
        attempts = list(
            (
                await session.scalars(
                    select(RecoveryInvestigationProviderAttempt)
                    .where(RecoveryInvestigationProviderAttempt.session_id == investigation_id)
                    .order_by(RecoveryInvestigationProviderAttempt.sequence_number)
                )
            ).all()
        )
    assert [item.sequence_number for item in attempts] == [1, 2]
    assert attempts[0].status == "failed_safe"
    assert attempts[0].failure_kind == "timeout"
    assert attempts[1].status == "succeeded"
    assert attempts[1].selected_result is True
    assert sum(item.selected_result for item in attempts) == 1


@pytest.mark.asyncio
async def test_case_detail_serializes_ordered_attempts_and_historical_sessions_are_empty(
    provider_attempt_graph: tuple[
        async_sessionmaker[AsyncSession], tuple[UUID, UUID, UUID, UUID, UUID]
    ],
) -> None:
    factory, (_, _, case_id, _, investigation_id) = provider_attempt_graph
    async with factory() as session:
        detail = await load_recovery_case_detail(session, recovery_case_id=case_id)
    assert detail.investigations[0].provider_attempts == ()
    provider = StubProvider("groq", "openai/gpt-oss-120b")
    attempt_id = await _start_provider_attempt(
        factory, session_id=investigation_id, provider=provider
    )
    await _finalize_provider_attempt(factory, attempt_id=attempt_id, response=_success())
    async with factory() as session:
        detail = await load_recovery_case_detail(session, recovery_case_id=case_id)
    timeline = detail.investigations[0].provider_attempts
    assert [item.sequence_number for item in timeline] == [1]
    assert timeline[0].provider == "groq"
    assert timeline[0].selected_result is True
