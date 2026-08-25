import argparse
import asyncio
import logging
from datetime import UTC, datetime, timedelta

from app.core.config import get_settings
from app.core.database import (
    close_database,
    get_session_factory,
)
from app.integrations.razorpay.payment_links import (
    create_razorpay_payment_link_provider,
)
from app.services.recovery_action_batch import (
    RecoveryActionBatchResult,
    run_recovery_action_batch,
)

LOGGER = logging.getLogger(
    "reclaimrail.recovery-action-worker",
)


def utc_now() -> datetime:
    return datetime.now(UTC)


def log_batch_result(
    result: RecoveryActionBatchResult,
) -> None:
    LOGGER.info(
        (
            "Recovery action batch completed: "
            "discovered=%d succeeded=%d "
            "already_succeeded=%d policy_denied=%d "
            "retryable_failures=%d "
            "permanent_failures=%d skipped=%d"
        ),
        result.discovered,
        result.succeeded,
        result.already_succeeded,
        result.policy_denied,
        result.retryable_failures,
        result.permanent_failures,
        result.skipped,
    )

    for failure in result.failures:
        LOGGER.warning(
            ("Recovery action failed: action_id=%s error_type=%s retryable=%s"),
            failure.action_id,
            failure.error_type,
            failure.retryable,
        )


async def run_recovery_action_worker(
    *,
    run_once: bool = False,
) -> None:
    settings = get_settings()

    provider = create_razorpay_payment_link_provider(
        settings,
    )

    if provider is None:
        raise RuntimeError(
            "Razorpay Key ID and Key Secret are required for the recovery action worker",
        )

    session_factory = get_session_factory()

    claim_timeout = timedelta(
        seconds=(settings.recovery_action_claim_timeout_seconds),
    )

    LOGGER.info(
        (
            "Recovery action worker started: "
            "batch_size=%d "
            "claim_timeout_seconds=%d "
            "maximum_attempts=%d mode=%s"
        ),
        settings.recovery_action_batch_size,
        (settings.recovery_action_claim_timeout_seconds),
        settings.recovery_action_max_attempts,
        "once" if run_once else "continuous",
    )

    try:
        while True:
            try:
                result = await run_recovery_action_batch(
                    session_factory,
                    provider=provider,
                    reference_time=utc_now(),
                    batch_size=(settings.recovery_action_batch_size),
                    claim_timeout=claim_timeout,
                    maximum_attempts=(settings.recovery_action_max_attempts),
                )
            except asyncio.CancelledError:
                raise
            except Exception:
                LOGGER.exception(
                    "Recovery action batch failed",
                )

                if run_once:
                    raise

                await asyncio.sleep(
                    settings.recovery_action_poll_interval_seconds,
                )
                continue

            if result.discovered > 0:
                log_batch_result(
                    result,
                )

            if run_once:
                return

            if result.discovered == 0:
                await asyncio.sleep(
                    settings.recovery_action_poll_interval_seconds,
                )
    finally:
        await close_database()

        LOGGER.info(
            "Recovery action worker stopped",
        )


def parse_run_once() -> bool:
    parser = argparse.ArgumentParser(
        description=("Execute ReclaimRail bounded recovery actions."),
    )

    parser.add_argument(
        "--once",
        action="store_true",
        help=("Process at most one recovery-action batch and exit."),
    )

    arguments = parser.parse_args()

    return bool(
        arguments.once,
    )


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format=("%(asctime)s %(levelname)s %(name)s %(message)s"),
    )

    try:
        asyncio.run(
            run_recovery_action_worker(
                run_once=parse_run_once(),
            ),
        )
    except KeyboardInterrupt:
        LOGGER.info(
            "Recovery action worker interrupted",
        )


if __name__ == "__main__":
    main()
