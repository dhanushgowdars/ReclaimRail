import argparse
import asyncio
import logging
from datetime import UTC, datetime, timedelta

from app.core.cache import close_redis
from app.core.config import get_settings
from app.core.database import (
    close_database,
    get_session_factory,
)
from app.integrations.razorpay.payment_customers import (
    create_razorpay_payment_customer_provider,
)
from app.integrations.razorpay.payment_link_notifications import (
    create_razorpay_payment_link_notification_provider,
)
from app.integrations.resend.recovery_email import (
    create_resend_recovery_email_provider,
)
from app.services.recovery_message_batch import (
    RecoveryMessageBatchResult,
    run_recovery_message_batch,
)
from app.services.worker_supervision_service import (
    WorkerName,
    create_worker_heartbeat_reporter,
)

LOGGER = logging.getLogger(
    "reclaimrail.recovery-message-worker",
)


def utc_now() -> datetime:
    return datetime.now(UTC)


def log_batch_result(
    result: RecoveryMessageBatchResult,
) -> None:
    LOGGER.info(
        (
            "Recovery message batch completed: "
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
            ("Recovery message failed: action_id=%s error_type=%s retryable=%s"),
            failure.action_id,
            failure.error_type,
            failure.retryable,
        )


async def run_recovery_message_worker(
    *,
    run_once: bool = False,
) -> None:
    settings = get_settings()

    customer_provider = create_razorpay_payment_customer_provider(
        settings,
    )
    notification_provider = create_razorpay_payment_link_notification_provider(
        settings,
    )
    direct_email_provider = create_resend_recovery_email_provider(settings)
    demo_recipient = getattr(settings, "payment_lab_demo_email_recipient", None)
    direct_email_recipient = (
        demo_recipient.get_secret_value().strip()
        if demo_recipient is not None
        else None
    )

    if customer_provider is None or notification_provider is None:
        raise RuntimeError(
            ("Razorpay Key ID and Key Secret are required for the recovery message worker"),
        )

    session_factory = get_session_factory()
    heartbeat = create_worker_heartbeat_reporter(
        settings,
        worker_name=WorkerName.RECOVERY_MESSAGE,
    )

    claim_timeout = timedelta(
        seconds=settings.recovery_action_claim_timeout_seconds,
    )

    LOGGER.info(
        (
            "Recovery message worker started: "
            "batch_size=%d "
            "claim_timeout_seconds=%d "
            "maximum_attempts=%d mode=%s"
        ),
        settings.recovery_action_batch_size,
        settings.recovery_action_claim_timeout_seconds,
        settings.recovery_action_max_attempts,
        "once" if run_once else "continuous",
    )

    await heartbeat.start()
    try:
        while True:
            try:
                result = await run_recovery_message_batch(
                    session_factory,
                    customer_provider=customer_provider,
                    notification_provider=notification_provider,
                    direct_email_provider=direct_email_provider,
                    direct_email_recipient=direct_email_recipient,
                    reference_time=utc_now(),
                    batch_size=settings.recovery_action_batch_size,
                    claim_timeout=claim_timeout,
                    maximum_attempts=settings.recovery_action_max_attempts,
                )
            except asyncio.CancelledError:
                raise
            except Exception as error:
                await heartbeat.record_failure(error)
                LOGGER.exception(
                    "Recovery message batch failed",
                )

                if run_once:
                    raise

                await asyncio.sleep(
                    settings.recovery_action_poll_interval_seconds,
                )
                continue

            await heartbeat.record_success(
                {
                    "discovered": result.discovered,
                    "succeeded": result.succeeded,
                    "retryable_failures": result.retryable_failures,
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

        LOGGER.info(
            "Recovery message worker stopped",
        )


def parse_run_once() -> bool:
    parser = argparse.ArgumentParser(
        description=("Send ReclaimRail policy-controlled recovery messages."),
    )

    parser.add_argument(
        "--once",
        action="store_true",
        help=("Process at most one recovery-message batch and exit."),
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
            run_recovery_message_worker(
                run_once=parse_run_once(),
            ),
        )
    except KeyboardInterrupt:
        LOGGER.info(
            "Recovery message worker interrupted",
        )


if __name__ == "__main__":
    main()
