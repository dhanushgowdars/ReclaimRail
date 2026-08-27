from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.payment import PaymentAttempt
from app.db.models.recovery import (
    RecoveryAction,
    RecoveryActionStatus,
    RecoveryCase,
)
from app.domain.payments import PaymentState
from app.domain.recovery import (
    RecoveryActionType,
    RecoveryCaseStatus,
)
from app.integrations.razorpay.payment_links import (
    RazorpayPaymentLink,
    RazorpayPaymentLinkProvider,
    RazorpayPaymentLinkProviderError,
    RazorpayPaymentLinkRequest,
    RazorpayPaymentLinkStatus,
)
from app.services import recovery_action_executor
from app.services.recovery_action_executor import (
    PreparedPaymentLinkAction,
    RecoveryActionExecutionDisposition,
    RecoveryActionExecutionResult,
    RecoveryActionInProgressError,
    RecoveryActionNotDueError,
    RecoveryActionPreparation,
    RecoveryActionProviderFailure,
    build_payment_link_reference_id,
    complete_recovery_payment_link_action,
    execute_recovery_payment_link_action,
    fail_recovery_payment_link_action,
    prepare_recovery_payment_link_action,
)

NOW = datetime(2026, 8, 25, 16, 0, tzinfo=UTC)
ACTION_ID = UUID(
    "91000000-0000-0000-0000-000000000001",
)
CASE_ID = UUID(
    "91000000-0000-0000-0000-000000000002",
)
PAYMENT_ID = UUID(
    "91000000-0000-0000-0000-000000000003",
)
AGENT_RUN_ID = UUID(
    "91000000-0000-0000-0000-000000000004",
)


def query_result(
    value: object | None,
) -> MagicMock:
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    return result


def create_action(
    *,
    status: RecoveryActionStatus = (RecoveryActionStatus.ALLOWED),
    execute_after: datetime | None = None,
    started_at: datetime | None = None,
    attempt_count: int = 0,
) -> RecoveryAction:
    return RecoveryAction(
        id=ACTION_ID,
        recovery_case_id=CASE_ID,
        agent_run_id=AGENT_RUN_ID,
        sequence_number=1,
        idempotency_key="a" * 64,
        action_type=(RecoveryActionType.CREATE_PAYMENT_LINK.value),
        status=status.value,
        proposal_reason="Recover failed payment",
        amount_minor=125_000,
        currency="INR",
        execute_after=execute_after,
        policy_outcome="allow",
        policy_guardrails=[],
        policy_explanation="Allowed",
        policy_version="deterministic-v1",
        policy_evaluated_at=(NOW - timedelta(minutes=1)),
        execution_attempt_count=attempt_count,
        started_at=started_at,
    )


def create_case(
    *,
    status: RecoveryCaseStatus = (RecoveryCaseStatus.READY),
) -> RecoveryCase:
    return RecoveryCase(
        id=CASE_ID,
        payment_attempt_id=PAYMENT_ID,
        status=status.value,
        amount_minor=125_000,
        currency="INR",
        payment_method="upi",
        recovery_attempt_count=0,
        version=1,
        customer_contact_allowed=True,
        opened_at=NOW - timedelta(minutes=10),
    )


def create_payment(
    *,
    state: PaymentState = PaymentState.FAILED,
) -> PaymentAttempt:
    return PaymentAttempt(
        id=PAYMENT_ID,
        provider="razorpay",
        provider_payment_id=("pay_action_executor_test"),
        amount_minor=125_000,
        currency="INR",
        method="upi",
        payment_created_at=(NOW - timedelta(minutes=11)),
        current_state=state.value,
        state_version=1,
        state_provider_event_id=("evt_action_executor_test"),
        state_webhook_event_id=UUID(
            "91000000-0000-0000-0000-000000000005",
        ),
        state_event_created_at=(NOW - timedelta(minutes=10)),
        recovery_eligible=(state is PaymentState.FAILED),
        late_authorization_detected_at=(
            NOW - timedelta(seconds=1) if state is PaymentState.AUTHORIZED else None
        ),
    )


def create_payment_link() -> RazorpayPaymentLink:
    return RazorpayPaymentLink.model_validate(
        {
            "id": "plink_action_executor_test",
            "short_url": ("https://rzp.io/i/action-test"),
            "status": "created",
            "amount": 125_000,
            "currency": "INR",
            "reference_id": (
                build_payment_link_reference_id(
                    ACTION_ID,
                )
            ),
            "expire_by": int((NOW + timedelta(hours=24)).timestamp()),
        },
    )


def create_prepared() -> PreparedPaymentLinkAction:
    reference_id = build_payment_link_reference_id(
        ACTION_ID,
    )

    return PreparedPaymentLinkAction(
        action_id=ACTION_ID,
        recovery_case_id=CASE_ID,
        provider_payment_id=("pay_action_executor_test"),
        customer_contact_allowed=False,
        attempt_number=1,
        reference_id=reference_id,
        request=RazorpayPaymentLinkRequest(
            amount_minor=125_000,
            currency="INR",
            reference_id=reference_id,
            description="Recover failed payment",
        ),
    )


def patch_audit(
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncMock:
    append_audit = AsyncMock()

    monkeypatch.setattr(
        recovery_action_executor,
        "append_recovery_audit_event",
        append_audit,
    )

    return append_audit


def test_builds_stable_provider_reference_within_limit() -> None:
    reference_id = build_payment_link_reference_id(
        ACTION_ID,
    )

    assert reference_id == ("rr_91000000000000000000000000000001")
    assert len(reference_id) == 35


@pytest.mark.asyncio
async def test_prepares_allowed_payment_link_action(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    action = create_action()
    recovery_case = create_case()

    session = AsyncMock(spec=AsyncSession)
    session.execute.side_effect = [
        query_result(action),
        query_result(recovery_case),
        query_result(create_payment()),
    ]

    append_audit = patch_audit(monkeypatch)

    result = await prepare_recovery_payment_link_action(
        session,
        action_id=ACTION_ID,
        executed_at=NOW,
    )

    assert result.prepared is not None
    assert result.terminal_result is None
    assert result.prepared.reference_id == (
        build_payment_link_reference_id(
            ACTION_ID,
        )
    )
    assert result.prepared.request.amount_minor == 125_000
    assert result.prepared.request.expire_by == NOW + timedelta(hours=24)
    assert action.status == RecoveryActionStatus.EXECUTING.value
    assert action.execution_attempt_count == 1
    assert action.started_at == NOW
    assert recovery_case.status == (RecoveryCaseStatus.EXECUTING.value)
    assert recovery_case.version == 2

    append_audit.assert_awaited_once()

    request = append_audit.await_args.kwargs["request"]
    assert request.event_type == ("action.payment_link.started")


@pytest.mark.asyncio
async def test_scheduled_action_cannot_execute_early() -> None:
    action = create_action(
        status=RecoveryActionStatus.SCHEDULED,
        execute_after=NOW + timedelta(minutes=5),
    )

    session = AsyncMock(spec=AsyncSession)
    session.execute.return_value = query_result(
        action,
    )

    with pytest.raises(
        RecoveryActionNotDueError,
        match="not due",
    ):
        await prepare_recovery_payment_link_action(
            session,
            action_id=ACTION_ID,
            executed_at=NOW,
        )

    assert session.execute.await_count == 1


@pytest.mark.asyncio
async def test_recent_execution_claim_cannot_be_stolen() -> None:
    action = create_action(
        status=RecoveryActionStatus.EXECUTING,
        started_at=NOW - timedelta(seconds=30),
        attempt_count=1,
    )

    session = AsyncMock(spec=AsyncSession)
    session.execute.return_value = query_result(
        action,
    )

    with pytest.raises(
        RecoveryActionInProgressError,
        match="active execution claim",
    ):
        await prepare_recovery_payment_link_action(
            session,
            action_id=ACTION_ID,
            executed_at=NOW,
        )


@pytest.mark.asyncio
async def test_succeeded_action_returns_idempotent_result() -> None:
    action = create_action(
        status=RecoveryActionStatus.SUCCEEDED,
    )

    session = AsyncMock(spec=AsyncSession)
    session.execute.return_value = query_result(
        action,
    )

    result = await prepare_recovery_payment_link_action(
        session,
        action_id=ACTION_ID,
        executed_at=NOW,
    )

    assert result.prepared is None
    assert result.terminal_result is not None
    assert (
        result.terminal_result.disposition is RecoveryActionExecutionDisposition.ALREADY_SUCCEEDED
    )


@pytest.mark.asyncio
async def test_late_authorization_stops_action_before_provider_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    action = create_action()
    recovery_case = create_case()

    session = AsyncMock(spec=AsyncSession)
    session.execute.side_effect = [
        query_result(action),
        query_result(recovery_case),
        query_result(
            create_payment(
                state=PaymentState.AUTHORIZED,
            ),
        ),
    ]

    append_audit = patch_audit(monkeypatch)

    result = await prepare_recovery_payment_link_action(
        session,
        action_id=ACTION_ID,
        executed_at=NOW,
    )

    assert result.terminal_result is not None
    assert result.terminal_result.disposition is RecoveryActionExecutionDisposition.POLICY_STOPPED
    assert action.status == RecoveryActionStatus.STOPPED.value
    assert "payment_already_completed" in action.policy_guardrails
    assert "late_authorization_detected" in action.policy_guardrails
    assert recovery_case.status == (RecoveryCaseStatus.CANCELLED.value)
    assert recovery_case.closed_at == NOW
    append_audit.assert_awaited_once()


@pytest.mark.asyncio
async def test_completion_persists_provider_result_and_case_projection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    action = create_action(
        status=RecoveryActionStatus.EXECUTING,
        started_at=NOW,
        attempt_count=1,
    )

    recovery_case = create_case(
        status=RecoveryCaseStatus.EXECUTING,
    )

    session = AsyncMock(spec=AsyncSession)
    session.execute.side_effect = [
        query_result(action),
        query_result(recovery_case),
    ]

    append_audit = patch_audit(monkeypatch)
    payment_link = create_payment_link()

    result = await complete_recovery_payment_link_action(
        session,
        prepared=create_prepared(),
        payment_link=payment_link,
        recovered_existing_link=True,
        completed_at=NOW,
    )

    assert result.disposition is RecoveryActionExecutionDisposition.SUCCEEDED
    assert result.recovered_existing_link is True
    assert action.status == RecoveryActionStatus.SUCCEEDED.value
    assert action.provider_action_id == (payment_link.payment_link_id)
    assert action.provider_action_status == (RazorpayPaymentLinkStatus.CREATED.value)
    assert action.provider_action_url == payment_link.short_url
    assert action.provider_action_expires_at == payment_link.provider_expires_at
    assert action.completed_at == NOW
    assert recovery_case.active_payment_link_id == payment_link.payment_link_id
    assert recovery_case.recovery_attempt_count == 1
    assert recovery_case.status == (RecoveryCaseStatus.READY.value)
    assert recovery_case.version == 2
    append_audit.assert_awaited_once()


@pytest.mark.asyncio
async def test_retryable_provider_failure_returns_case_to_ready(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    action = create_action(
        status=RecoveryActionStatus.EXECUTING,
        started_at=NOW,
        attempt_count=1,
    )

    recovery_case = create_case(
        status=RecoveryCaseStatus.EXECUTING,
    )

    session = AsyncMock(spec=AsyncSession)
    session.execute.side_effect = [
        query_result(action),
        query_result(recovery_case),
    ]

    append_audit = patch_audit(monkeypatch)

    await fail_recovery_payment_link_action(
        session,
        prepared=create_prepared(),
        error=RazorpayPaymentLinkProviderError(
            "temporary provider failure",
            retryable=True,
            status_code=503,
        ),
        failed_at=NOW,
    )

    assert action.status == RecoveryActionStatus.FAILED.value
    assert "temporary provider failure" not in (action.last_error or "")
    assert "status_code=503" in (action.last_error or "")
    assert recovery_case.status == (RecoveryCaseStatus.READY.value)
    assert recovery_case.next_action_at == NOW
    append_audit.assert_awaited_once()


class SessionContext:
    def __init__(
        self,
        session: object,
    ) -> None:
        self._session = session

    async def __aenter__(self) -> object:
        return self._session

    async def __aexit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: object | None,
    ) -> None:
        return None


class StubSessionFactory:
    def __init__(self) -> None:
        self.sessions: list[MagicMock] = []

    def begin(self) -> SessionContext:
        session = MagicMock()
        self.sessions.append(session)
        return SessionContext(session)


@pytest.mark.asyncio
async def test_orchestrator_recovers_existing_provider_link(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepared = create_prepared()
    payment_link = create_payment_link()

    preparation = RecoveryActionPreparation(
        prepared=prepared,
    )

    prepare = AsyncMock(
        return_value=preparation,
    )

    complete = AsyncMock(
        return_value=RecoveryActionExecutionResult(
            action_id=ACTION_ID,
            recovery_case_id=CASE_ID,
            disposition=(RecoveryActionExecutionDisposition.SUCCEEDED),
            payment_link=payment_link,
            recovered_existing_link=True,
        ),
    )

    monkeypatch.setattr(
        recovery_action_executor,
        "prepare_recovery_payment_link_action",
        prepare,
    )
    monkeypatch.setattr(
        recovery_action_executor,
        "complete_recovery_payment_link_action",
        complete,
    )

    provider = MagicMock(
        spec=RazorpayPaymentLinkProvider,
    )
    provider.find_payment_link_by_reference = AsyncMock(
        return_value=payment_link,
    )
    provider.create_payment_link = AsyncMock()

    session_factory = StubSessionFactory()

    result = await execute_recovery_payment_link_action(
        session_factory,  # type: ignore[arg-type]
        action_id=ACTION_ID,
        provider=provider,
        executed_at=NOW,
    )

    assert result.recovered_existing_link is True
    provider.find_payment_link_by_reference.assert_awaited_once_with(
        prepared.reference_id,
    )
    provider.create_payment_link.assert_not_awaited()
    complete.assert_awaited_once()
    assert len(session_factory.sessions) == 2


@pytest.mark.asyncio
async def test_orchestrator_creates_link_when_reference_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepared = create_prepared()
    payment_link = create_payment_link()

    monkeypatch.setattr(
        recovery_action_executor,
        "prepare_recovery_payment_link_action",
        AsyncMock(
            return_value=RecoveryActionPreparation(
                prepared=prepared,
            ),
        ),
    )

    complete = AsyncMock(
        return_value=RecoveryActionExecutionResult(
            action_id=ACTION_ID,
            recovery_case_id=CASE_ID,
            disposition=(RecoveryActionExecutionDisposition.SUCCEEDED),
            payment_link=payment_link,
        ),
    )

    monkeypatch.setattr(
        recovery_action_executor,
        "complete_recovery_payment_link_action",
        complete,
    )

    provider = MagicMock(
        spec=RazorpayPaymentLinkProvider,
    )
    provider.find_payment_link_by_reference = AsyncMock(return_value=None)
    provider.create_payment_link = AsyncMock(
        return_value=payment_link,
    )

    await execute_recovery_payment_link_action(
        StubSessionFactory(),  # type: ignore[arg-type]
        action_id=ACTION_ID,
        provider=provider,
        executed_at=NOW,
    )

    provider.create_payment_link.assert_awaited_once_with(
        prepared.request,
    )
    complete.assert_awaited_once()
    assert complete.await_args.kwargs["recovered_existing_link"] is False


@pytest.mark.asyncio
async def test_orchestrator_records_provider_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepared = create_prepared()

    monkeypatch.setattr(
        recovery_action_executor,
        "prepare_recovery_payment_link_action",
        AsyncMock(
            return_value=RecoveryActionPreparation(
                prepared=prepared,
            ),
        ),
    )

    fail = AsyncMock(return_value=True)

    monkeypatch.setattr(
        recovery_action_executor,
        "fail_recovery_payment_link_action",
        fail,
    )

    provider = MagicMock(
        spec=RazorpayPaymentLinkProvider,
    )
    provider.find_payment_link_by_reference = AsyncMock(
        side_effect=(
            RazorpayPaymentLinkProviderError(
                "temporary failure",
                retryable=True,
                status_code=503,
            )
        ),
    )

    with pytest.raises(
        RecoveryActionProviderFailure,
    ) as caught:
        await execute_recovery_payment_link_action(
            StubSessionFactory(),  # type: ignore[arg-type]
            action_id=ACTION_ID,
            provider=provider,
            executed_at=NOW,
        )

    assert caught.value.retryable is True
    assert caught.value.status_code == 503
    fail.assert_awaited_once()
