import argparse
import asyncio
import logging
from datetime import UTC, datetime, timedelta

from app.core.cache import close_redis
from app.core.config import get_settings
from app.core.database import close_database, get_session_factory
from app.domain.recovery import RecoveryPlannerPolicy
from app.integrations.gemini import create_gemini_recovery_plan_provider
from app.integrations.razorpay.orders import create_razorpay_order_provider
from app.services.payment_lab_provider_verification import (
    verify_payment_lab_provider_evidence_batch,
)
from app.services.payment_lab_recovery_batch import (
    PaymentLabRecoveryBatchResult,
    run_payment_lab_recovery_batch,
)
from app.services.worker_supervision_service import (
    WorkerName,
    create_worker_heartbeat_reporter,
)

LOGGER = logging.getLogger("reclaimrail.payment-lab-recovery-worker")


def utc_now() -> datetime:
    return datetime.now(UTC)


def log_batch_result(result: PaymentLabRecoveryBatchResult) -> None:
    LOGGER.info(
        (
            "Payment Lab recovery batch completed: "
            "discovered=%d started=%d already_running=%d "
            "already_planned=%d gemini_plans=%d "
            "deterministic_plans=%d fallback_plans=%d "
            "retryable_failures=%d permanent_failures=%d skipped=%d"
        ),
        result.discovered,
        result.started,
        result.already_running,
        result.already_planned,
        result.gemini_plans,
        result.deterministic_plans,
        result.fallback_plans,
        result.retryable_failures,
        result.permanent_failures,
        result.skipped,
    )

    for failure in result.failures:
        LOGGER.warning(
            ("Payment Lab recovery failed: run_id=%s error_type=%s retryable=%s"),
            failure.payment_lab_run_id,
            failure.error_type,
            failure.retryable,
        )


async def run_payment_lab_recovery_worker(*, run_once: bool = False) -> None:
    settings = get_settings()
    provider = create_gemini_recovery_plan_provider(settings)
    order_provider = create_razorpay_order_provider(settings)
    session_factory = get_session_factory()
    heartbeat = create_worker_heartbeat_reporter(
        settings,
        worker_name=WorkerName.PAYMENT_LAB_RECOVERY,
    )

    LOGGER.info(
        (
            "Payment Lab recovery worker started: batch_size=%d "
            "poll_interval_seconds=%s planner=%s mode=%s"
        ),
        settings.payment_lab_recovery_batch_size,
        settings.payment_lab_recovery_poll_interval_seconds,
        "gemini_with_deterministic_fallback" if provider is not None else "deterministic",
        "once" if run_once else "continuous",
    )
    claim_timeout = timedelta(
        seconds=settings.payment_lab_recovery_claim_timeout_seconds,
    )
    planner_policy = RecoveryPlannerPolicy(
        incident_recheck_delay=timedelta(
            seconds=settings.recovery_incident_recheck_delay_seconds,
        ),
    )

    await heartbeat.start()
    try:
        while True:
            try:
                if order_provider is not None:
                    verification = await verify_payment_lab_provider_evidence_batch(
                        session_factory,
                        provider=order_provider,
                        reference_time=utc_now(),
                        batch_size=settings.payment_lab_recovery_batch_size,
                    )
                    if verification.projected > 0:
                        LOGGER.info(
                            "Payment Lab provider verification projected=%d checked=%d",
                            verification.projected,
                            verification.checked,
                        )
                result = await run_payment_lab_recovery_batch(
                    session_factory,
                    reference_time=utc_now(),
                    provider=provider,
                    batch_size=settings.payment_lab_recovery_batch_size,
                    claim_timeout=claim_timeout,
                    approval_threshold_minor=(settings.recovery_approval_threshold_minor),
                    approval_window=timedelta(
                        seconds=settings.recovery_approval_ttl_seconds,
                    ),
                    planner_policy=planner_policy,
                )
            except asyncio.CancelledError:
                raise
            except Exception as error:
                await heartbeat.record_failure(error)
                LOGGER.exception("Payment Lab recovery batch failed")

                if run_once:
                    raise

                await asyncio.sleep(
                    settings.payment_lab_recovery_poll_interval_seconds,
                )
                continue

            await heartbeat.record_success(
                {
                    "discovered": result.discovered,
                    "started": result.started,
                    "retryable_failures": result.retryable_failures,
                },
            )

            if result.discovered > 0:
                log_batch_result(result)

            if run_once:
                return

            if result.discovered == 0:
                await asyncio.sleep(
                    settings.payment_lab_recovery_poll_interval_seconds,
                )
    finally:
        await heartbeat.stop()
        await asyncio.gather(close_redis(), close_database())
        LOGGER.info("Payment Lab recovery worker stopped")


def parse_run_once() -> bool:
    parser = argparse.ArgumentParser(
        description="Start bounded recovery for verified Payment Lab failures.",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Process at most one Payment Lab recovery batch and exit.",
    )
    return bool(parser.parse_args().once)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    try:
        asyncio.run(run_payment_lab_recovery_worker(run_once=parse_run_once()))
    except KeyboardInterrupt:
        LOGGER.info("Payment Lab recovery worker interrupted")


if __name__ == "__main__":
    main()
