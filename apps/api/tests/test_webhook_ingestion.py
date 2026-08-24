from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.outbox import (
    OutboxMessage,
    OutboxMessageStatus,
)
from app.db.models.webhook import (
    WebhookDelivery,
    WebhookDeliveryStatus,
)
from app.integrations.razorpay.webhooks import RazorpayWebhookEnvelope
from app.services.webhook_ingestion import (
    OUTBOX_SCHEMA_VERSION,
    WEBHOOK_RECEIVED_TOPIC,
    ingest_verified_webhook,
)

EVENT_ID = UUID("12345678-1234-5678-1234-567812345678")
PROVIDER_EVENT_ID = "evt_test_outbox_001"
CREATED_AT = 1_787_550_000
RAW_BODY = b'{"entity":"event","event":"payment.failed"}'
SIGNATURE = "a" * 64


def make_envelope() -> RazorpayWebhookEnvelope:
    return RazorpayWebhookEnvelope(
        entity="event",
        account_id="acc_reclaimrail_test",
        event="payment.failed",
        contains=["payment"],
        payload={
            "payment": {
                "entity": {
                    "id": "pay_reclaimrail_test_001",
                    "status": "failed",
                },
            },
        },
        created_at=CREATED_AT,
    )


@pytest.mark.asyncio
async def test_new_webhook_creates_one_pending_outbox_message() -> None:
    insert_result = MagicMock()
    insert_result.scalar_one_or_none.return_value = EVENT_ID

    session = AsyncMock(spec=AsyncSession)
    session.execute.return_value = insert_result

    result = await ingest_verified_webhook(
        session,
        provider_event_id=PROVIDER_EVENT_ID,
        signature=SIGNATURE,
        raw_body=RAW_BODY,
        envelope=make_envelope(),
    )

    added_objects = [call.args[0] for call in session.add.call_args_list]

    outbox_messages = [item for item in added_objects if isinstance(item, OutboxMessage)]
    deliveries = [item for item in added_objects if isinstance(item, WebhookDelivery)]

    assert result.canonical_event_id == EVENT_ID
    assert result.duplicate is False

    assert len(outbox_messages) == 1
    assert outbox_messages[0].webhook_event_id == EVENT_ID
    assert outbox_messages[0].topic == WEBHOOK_RECEIVED_TOPIC
    assert outbox_messages[0].status == OutboxMessageStatus.PENDING.value
    assert outbox_messages[0].attempt_count == 0
    assert outbox_messages[0].payload["schema_version"] == OUTBOX_SCHEMA_VERSION
    assert outbox_messages[0].payload["provider_event_id"] == PROVIDER_EVENT_ID
    assert outbox_messages[0].payload["event_type"] == "payment.failed"

    assert len(deliveries) == 1
    assert deliveries[0].delivery_status == WebhookDeliveryStatus.ACCEPTED.value
    assert deliveries[0].is_duplicate is False

    session.execute.assert_awaited_once()
    session.commit.assert_awaited_once()
    session.rollback.assert_not_awaited()


@pytest.mark.asyncio
async def test_duplicate_webhook_does_not_create_another_outbox_message() -> None:
    insert_result = MagicMock()
    insert_result.scalar_one_or_none.return_value = None

    update_result = MagicMock()
    update_result.scalar_one.return_value = EVENT_ID

    session = AsyncMock(spec=AsyncSession)
    session.execute.side_effect = [
        insert_result,
        update_result,
    ]

    result = await ingest_verified_webhook(
        session,
        provider_event_id=PROVIDER_EVENT_ID,
        signature=SIGNATURE,
        raw_body=RAW_BODY,
        envelope=make_envelope(),
    )

    added_objects = [call.args[0] for call in session.add.call_args_list]

    assert result.canonical_event_id == EVENT_ID
    assert result.duplicate is True
    assert not any(isinstance(item, OutboxMessage) for item in added_objects)

    deliveries = [item for item in added_objects if isinstance(item, WebhookDelivery)]

    assert len(deliveries) == 1
    assert deliveries[0].delivery_status == WebhookDeliveryStatus.DUPLICATE.value
    assert deliveries[0].is_duplicate is True

    assert session.execute.await_count == 2
    session.commit.assert_awaited_once()
    session.rollback.assert_not_awaited()
