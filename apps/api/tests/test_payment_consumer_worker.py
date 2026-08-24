from unittest.mock import AsyncMock

import pytest

from app.core.config import Settings
from app.services.payment_stream_consumer import (
    PaymentStreamBatchResult,
)
from app.workers import payment_consumer_worker


def create_empty_batch_result() -> PaymentStreamBatchResult:
    return PaymentStreamBatchResult(
        received=0,
        projected=0,
        duplicates=0,
        skipped=0,
        failed=0,
        dead_lettered=0,
        retried=0,
    )


def test_parse_run_once_defaults_to_continuous() -> None:
    assert payment_consumer_worker.parse_run_once([]) is False


def test_parse_run_once_accepts_once_flag() -> None:
    assert (
        payment_consumer_worker.parse_run_once(
            ["--once"],
        )
        is True
    )


@pytest.mark.asyncio
async def test_run_once_processes_one_batch_and_closes_resources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(
        payment_consumer_block_milliseconds=5000,
    )
    session_factory = object()
    redis_client = object()

    ensure_group = AsyncMock()
    consume_batch = AsyncMock(
        return_value=create_empty_batch_result(),
    )
    close_redis = AsyncMock()
    close_database = AsyncMock()

    monkeypatch.setattr(
        payment_consumer_worker,
        "get_settings",
        lambda: settings,
    )
    monkeypatch.setattr(
        payment_consumer_worker,
        "get_session_factory",
        lambda: session_factory,
    )
    monkeypatch.setattr(
        payment_consumer_worker,
        "get_redis_client",
        lambda: redis_client,
    )
    monkeypatch.setattr(
        payment_consumer_worker,
        "ensure_payment_consumer_group",
        ensure_group,
    )
    monkeypatch.setattr(
        payment_consumer_worker,
        "consume_payment_stream_batch",
        consume_batch,
    )
    monkeypatch.setattr(
        payment_consumer_worker,
        "close_redis",
        close_redis,
    )
    monkeypatch.setattr(
        payment_consumer_worker,
        "close_database",
        close_database,
    )

    await payment_consumer_worker.run_payment_consumer_worker(
        run_once=True,
        consumer_name="test-consumer",
    )

    ensure_group.assert_awaited_once()
    consumer_config = ensure_group.await_args.args[1]

    assert consumer_config.consumer_name == "test-consumer"
    assert consumer_config.block_milliseconds == 1

    consume_batch.assert_awaited_once_with(
        session_factory,
        redis_client,
        consumer_config,
    )
    close_redis.assert_awaited_once()
    close_database.assert_awaited_once()


@pytest.mark.asyncio
async def test_run_once_closes_resources_after_batch_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings()
    session_factory = object()
    redis_client = object()

    ensure_group = AsyncMock()
    consume_batch = AsyncMock(
        side_effect=RuntimeError("Redis unavailable"),
    )
    close_redis = AsyncMock()
    close_database = AsyncMock()

    monkeypatch.setattr(
        payment_consumer_worker,
        "get_settings",
        lambda: settings,
    )
    monkeypatch.setattr(
        payment_consumer_worker,
        "get_session_factory",
        lambda: session_factory,
    )
    monkeypatch.setattr(
        payment_consumer_worker,
        "get_redis_client",
        lambda: redis_client,
    )
    monkeypatch.setattr(
        payment_consumer_worker,
        "ensure_payment_consumer_group",
        ensure_group,
    )
    monkeypatch.setattr(
        payment_consumer_worker,
        "consume_payment_stream_batch",
        consume_batch,
    )
    monkeypatch.setattr(
        payment_consumer_worker,
        "close_redis",
        close_redis,
    )
    monkeypatch.setattr(
        payment_consumer_worker,
        "close_database",
        close_database,
    )

    with pytest.raises(
        RuntimeError,
        match="Redis unavailable",
    ):
        await payment_consumer_worker.run_payment_consumer_worker(
            run_once=True,
            consumer_name="test-consumer",
        )

    close_redis.assert_awaited_once()
    close_database.assert_awaited_once()
