import argparse
import asyncio
import logging
import os
import socket
from dataclasses import replace

from app.core.cache import close_redis, get_redis_client
from app.core.config import get_settings
from app.core.database import (
    close_database,
    get_session_factory,
)
from app.services.payment_stream_consumer import (
    consume_payment_stream_batch,
    create_payment_consumer_config,
    ensure_payment_consumer_group,
)
from app.services.worker_supervision_service import (
    WorkerName,
    create_worker_heartbeat_reporter,
)

LOGGER = logging.getLogger("reclaimrail.payment-consumer-worker")


def build_consumer_name() -> str:
    hostname = socket.gethostname().strip() or "unknown-host"
    return f"{hostname}-{os.getpid()}"


async def run_payment_consumer_worker(
    *,
    run_once: bool = False,
    consumer_name: str | None = None,
) -> None:
    settings = get_settings()
    session_factory = get_session_factory()
    redis_client = get_redis_client()
    heartbeat = create_worker_heartbeat_reporter(
        settings,
        worker_name=WorkerName.PAYMENT_CONSUMER,
        redis_client=redis_client,
    )

    consumer_config = create_payment_consumer_config(
        settings,
        consumer_name=consumer_name or build_consumer_name(),
    )

    if run_once:
        consumer_config = replace(
            consumer_config,
            block_milliseconds=1,
        )

    await ensure_payment_consumer_group(
        redis_client,
        consumer_config,
    )

    LOGGER.info(
        ("Payment consumer started: stream=%s group=%s consumer=%s batch_size=%d mode=%s"),
        consumer_config.stream_name,
        consumer_config.group_name,
        consumer_config.consumer_name,
        consumer_config.batch_size,
        "once" if run_once else "continuous",
    )

    await heartbeat.start()
    try:
        while True:
            try:
                result = await consume_payment_stream_batch(
                    session_factory,
                    redis_client,
                    consumer_config,
                )
            except asyncio.CancelledError:
                raise
            except Exception as error:
                await heartbeat.record_failure(error)
                LOGGER.exception(
                    "Payment stream consumer batch failed",
                )

                if run_once:
                    raise

                await asyncio.sleep(
                    settings.payment_consumer_error_retry_seconds,
                )
                continue

            await heartbeat.record_success(
                {
                    "received": result.received,
                    "projected": result.projected,
                    "failed": result.failed,
                    "dead_lettered": result.dead_lettered,
                },
            )

            if result.received > 0:
                LOGGER.info(
                    (
                        "Payment stream batch completed: "
                        "received=%d projected=%d duplicates=%d "
                        "skipped=%d failed=%d dead_lettered=%d "
                        "retried=%d"
                    ),
                    result.received,
                    result.projected,
                    result.duplicates,
                    result.skipped,
                    result.failed,
                    result.dead_lettered,
                    result.retried,
                )

            if run_once:
                return
    finally:
        await heartbeat.stop()
        await asyncio.gather(
            close_redis(),
            close_database(),
        )

        LOGGER.info("Payment consumer stopped")


def parse_run_once(
    arguments: list[str] | None = None,
) -> bool:
    parser = argparse.ArgumentParser(
        description=("Consume ReclaimRail webhook events and project payment lifecycle state."),
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Process at most one stream batch and exit.",
    )

    parsed_arguments = parser.parse_args(arguments)
    return bool(parsed_arguments.once)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format=("%(asctime)s %(levelname)s %(name)s %(message)s"),
    )

    try:
        asyncio.run(
            run_payment_consumer_worker(
                run_once=parse_run_once(),
            ),
        )
    except KeyboardInterrupt:
        LOGGER.info("Payment consumer interrupted")


if __name__ == "__main__":
    main()
