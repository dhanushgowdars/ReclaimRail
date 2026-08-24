import argparse
import asyncio
import logging

from app.core.cache import close_redis, get_redis_client
from app.core.config import get_settings
from app.core.database import (
    close_database,
    get_session_factory,
)
from app.services.outbox_dispatcher import (
    create_dispatcher_config,
    dispatch_outbox_batch,
)

LOGGER = logging.getLogger("reclaimrail.outbox-worker")


async def run_outbox_worker(
    *,
    run_once: bool = False,
) -> None:
    settings = get_settings()
    dispatcher_config = create_dispatcher_config(settings)
    session_factory = get_session_factory()
    redis_client = get_redis_client()

    LOGGER.info(
        "Outbox worker started: stream=%s batch_size=%d mode=%s",
        dispatcher_config.stream_name,
        dispatcher_config.batch_size,
        "once" if run_once else "continuous",
    )

    try:
        while True:
            try:
                result = await dispatch_outbox_batch(
                    session_factory,
                    redis_client,
                    dispatcher_config,
                )
            except asyncio.CancelledError:
                raise
            except Exception:
                LOGGER.exception("Outbox dispatch batch failed")

                if run_once:
                    raise

                await asyncio.sleep(
                    settings.outbox_poll_interval_seconds,
                )
                continue

            if result.claimed > 0:
                LOGGER.info(
                    ("Outbox batch completed: claimed=%d published=%d retried=%d failed=%d"),
                    result.claimed,
                    result.published,
                    result.retried,
                    result.failed,
                )

            if run_once:
                return

            if result.claimed == 0:
                await asyncio.sleep(
                    settings.outbox_poll_interval_seconds,
                )
    finally:
        await asyncio.gather(
            close_redis(),
            close_database(),
        )

        LOGGER.info("Outbox worker stopped")


def parse_run_once() -> bool:
    parser = argparse.ArgumentParser(
        description="Dispatch ReclaimRail transactional outbox messages.",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Process at most one batch and exit.",
    )

    arguments = parser.parse_args()
    return bool(arguments.once)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format=("%(asctime)s %(levelname)s %(name)s %(message)s"),
    )

    try:
        asyncio.run(
            run_outbox_worker(
                run_once=parse_run_once(),
            ),
        )
    except KeyboardInterrupt:
        LOGGER.info("Outbox worker interrupted")


if __name__ == "__main__":
    main()
