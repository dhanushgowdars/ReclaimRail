from unittest.mock import AsyncMock, MagicMock

import pytest

from app.db.models.event_replay import PaymentEventReplayAudit
from app.services.payment_event_replay import (
    PaymentEventReplayError,
    replay_dead_letter_event,
)


@pytest.mark.asyncio
async def test_controlled_replay_requires_reason_and_writes_audit() -> None:
    session = AsyncMock()
    session.add = MagicMock()
    session.scalar.return_value = None
    redis = AsyncMock()
    redis.xrange.return_value = [
        (
            "100-0",
            {
                "fields": (
                    '{"outbox_message_id":"00000000-0000-0000-0000-000000000001",'
                    '"payload":"{}","topic":"webhook.received"}'
                ),
            },
        ),
    ]
    redis.xadd.return_value = "200-0"

    result = await replay_dead_letter_event(
        session,
        redis,
        dead_letter_stream="dead-letter",
        source_message_id="100-0",
        target_stream="payments",
        requested_by="operator@example.test",
        reason="Payload parser was fixed and reviewed",
    )

    audit = session.add.call_args.args[0]
    assert isinstance(audit, PaymentEventReplayAudit)
    assert audit.status == "published"
    assert audit.target_message_id == "200-0"
    assert result.audit_id == str(audit.id)
    redis.xadd.assert_awaited_once_with(
        "payments",
        {
            "outbox_message_id": "00000000-0000-0000-0000-000000000001",
            "payload": "{}",
            "topic": "webhook.received",
        },
    )


@pytest.mark.asyncio
async def test_replay_rejects_duplicate_authorization() -> None:
    session = AsyncMock()
    session.scalar.return_value = PaymentEventReplayAudit()

    with pytest.raises(PaymentEventReplayError, match="already been replayed"):
        await replay_dead_letter_event(
            session,
            AsyncMock(),
            dead_letter_stream="dead-letter",
            source_message_id="100-0",
            target_stream="payments",
            requested_by="operator@example.test",
            reason="Reviewed",
        )
