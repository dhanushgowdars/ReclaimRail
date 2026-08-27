import argparse
import asyncio
import logging
from datetime import UTC, datetime

from app.core.config import get_settings
from app.core.database import (
    close_database,
    get_session_factory,
)
from app.integrations.razorpay.payment_links import (
    create_razorpay_payment_link_provider,
)
from app.services.recovery_outcome_batch import (
    RecoveryOutcomeBatchResult,
    run_recovery_outcome_batch,
)

LOGGER = logging.getLogger(
    "reclaimrail.recovery-outcome-worker",
)


def utc_now() -> datetime:
    return datetime.now(UTC)


def log_batch_result(
    result: RecoveryOutcomeBatchResult,
) -> None:
    LOGGER.info(
        (
            "Recovery outcome batch completed: "
            "discovered=%d reconciled=%d "
            "already_current=%d recovered=%d "
            "duplicate_collection_prevented=%d "
            "retryable_failures=%d permanent_failures=%d "
            "skipped=%d"
        ),
        result.discovered,
        result.reconciled,
        result.already_current,
        result.recovered,
        result.duplicate_collection_prevented,
        result.retryable_failures,
        result.permanent_failures,
        result.skipped,
    )

    for failure in result.failures:
        LOGGER.warning(
            ("Recovery outcome reconciliation failed: action_id=%s error_type=%s retryable=%s"),
            failure.recovery_action_id,
            failure.error_type,
            failure.retryable,
        )


async def run_recovery_outcome_worker(
    *,
    run_once: bool = False,
) -> None:
    settings = get_settings()

    provider = create_razorpay_payment_link_provider(
        settings,
    )

    if provider is None:
        raise RuntimeError(
            ("Razorpay Key ID and Key Secret are required for the recovery outcome worker"),
        )

    session_factory = get_session_factory()

    LOGGER.info(
        ("Recovery outcome worker started: batch_size=%d poll_interval_seconds=%s mode=%s"),
        settings.recovery_outcome_batch_size,
        settings.recovery_outcome_poll_interval_seconds,
        "once" if run_once else "continuous",
    )

    try:
        while True:
            try:
                result = await run_recovery_outcome_batch(
                    session_factory,
                    provider=provider,
                    reference_time=utc_now(),
                    batch_size=settings.recovery_outcome_batch_size,
                )
            except asyncio.CancelledError:
                raise
            except Exception:
                LOGGER.exception(
                    "Recovery outcome batch failed",
                )

                if run_once:
                    raise

                await asyncio.sleep(
                    settings.recovery_outcome_poll_interval_seconds,
                )
                continue

            if result.discovered > 0:
                log_batch_result(result)

            if run_once:
                return

            await asyncio.sleep(
                settings.recovery_outcome_poll_interval_seconds,
            )
    finally:
        await close_database()

        LOGGER.info(
            "Recovery outcome worker stopped",
        )


def parse_run_once() -> bool:
    parser = argparse.ArgumentParser(
        description=("Reconcile ReclaimRail Payment Link outcomes."),
    )

    parser.add_argument(
        "--once",
        action="store_true",
        help=("Process at most one recovery-outcome batch and exit."),
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
            run_recovery_outcome_worker(
                run_once=parse_run_once(),
            ),
        )
    except KeyboardInterrupt:
        LOGGER.info(
            "Recovery outcome worker interrupted",
        )


if __name__ == "__main__":
    main()
