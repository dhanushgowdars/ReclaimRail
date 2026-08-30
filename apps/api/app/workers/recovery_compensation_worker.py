import argparse
import asyncio
import logging
from datetime import UTC, datetime

from app.core.cache import close_redis
from app.core.config import get_settings
from app.core.database import close_database, get_session_factory
from app.integrations.razorpay.payment_links import (
    create_razorpay_payment_link_provider,
)
from app.services.recovery_compensation_batch import (
    RecoveryCompensationBatchResult,
    run_recovery_compensation_batch,
)
from app.services.worker_supervision_service import (
    WorkerName,
    create_worker_heartbeat_reporter,
)

LOGGER = logging.getLogger("reclaimrail.recovery-compensation-worker")


def utc_now() -> datetime:
    return datetime.now(UTC)


def log_batch_result(result: RecoveryCompensationBatchResult) -> None:
    LOGGER.info(
        (
            "Recovery compensation batch completed: discovered=%d cancelled=%d "
            "already_cancelled=%d escalated=%d retryable_failures=%d "
            "permanent_failures=%d skipped=%d"
        ),
        result.discovered,
        result.cancelled,
        result.already_cancelled,
        result.escalated,
        result.retryable_failures,
        result.permanent_failures,
        result.skipped,
    )

    for failure in result.failures:
        LOGGER.warning(
            "Recovery compensation failed: case_id=%s error_type=%s retryable=%s",
            failure.recovery_case_id,
            failure.error_type,
            failure.retryable,
        )


async def run_recovery_compensation_worker(
    *,
    run_once: bool = False,
) -> None:
    settings = get_settings()
    provider = create_razorpay_payment_link_provider(settings)

    if provider is None:
        raise RuntimeError(
            "Razorpay Key ID and Key Secret are required for the recovery compensation worker",
        )

    session_factory = get_session_factory()
    heartbeat = create_worker_heartbeat_reporter(
        settings,
        worker_name=WorkerName.RECOVERY_COMPENSATION,
    )

    LOGGER.info(
        "Recovery compensation worker started: batch_size=%d mode=%s",
        settings.recovery_action_batch_size,
        "once" if run_once else "continuous",
    )

    await heartbeat.start()
    try:
        while True:
            try:
                result = await run_recovery_compensation_batch(
                    session_factory,
                    provider=provider,
                    reference_time=utc_now(),
                    batch_size=settings.recovery_action_batch_size,
                )
            except asyncio.CancelledError:
                raise
            except Exception as error:
                await heartbeat.record_failure(error)
                LOGGER.exception("Recovery compensation batch failed")

                if run_once:
                    raise

                await asyncio.sleep(
                    settings.recovery_action_poll_interval_seconds,
                )
                continue

            await heartbeat.record_success(
                {
                    "discovered": result.discovered,
                    "cancelled": result.cancelled,
                    "escalated": result.escalated,
                },
            )

            if result.discovered > 0:
                log_batch_result(result)

            if run_once:
                return

            if result.discovered == 0:
                await asyncio.sleep(
                    settings.recovery_action_poll_interval_seconds,
                )
    finally:
        await heartbeat.stop()
        await asyncio.gather(close_redis(), close_database())
        LOGGER.info("Recovery compensation worker stopped")


def parse_run_once() -> bool:
    parser = argparse.ArgumentParser(
        description="Cancel unsafe ReclaimRail recovery links.",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Process at most one recovery-compensation batch and exit.",
    )

    arguments = parser.parse_args()
    return bool(arguments.once)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    try:
        asyncio.run(
            run_recovery_compensation_worker(
                run_once=parse_run_once(),
            ),
        )
    except KeyboardInterrupt:
        LOGGER.info("Recovery compensation worker interrupted")


if __name__ == "__main__":
    main()
