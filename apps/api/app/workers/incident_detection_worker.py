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
from app.services.incident_detection_batch import (
    IncidentDetectionBatchResult,
    run_incident_detection_batch,
)
from app.services.worker_supervision_service import (
    WorkerName,
    create_worker_heartbeat_reporter,
)

LOGGER = logging.getLogger(
    "reclaimrail.incident-detection-worker",
)


def utc_now() -> datetime:
    return datetime.now(UTC)


def log_batch_result(
    result: IncidentDetectionBatchResult,
) -> None:
    LOGGER.info(
        ("Incident detection batch completed: run_id=%s attempted=%d succeeded=%d failed=%d"),
        result.detector_run_id,
        result.attempted,
        result.succeeded,
        result.failed,
    )

    for failure in result.failures:
        LOGGER.warning(
            ("Payment-method detection failed: method=%s error_type=%s error=%s"),
            failure.payment_method,
            failure.error_type,
            failure.error_message,
        )


async def run_incident_detection_worker(
    *,
    run_once: bool = False,
) -> None:
    settings = get_settings()
    session_factory = get_session_factory()
    heartbeat = create_worker_heartbeat_reporter(
        settings,
        worker_name=WorkerName.INCIDENT_DETECTION,
    )

    window_size = timedelta(
        minutes=settings.incident_window_minutes,
    )

    LOGGER.info(
        (
            "Incident detection worker started: "
            "methods=%s currency=%s window_minutes=%d "
            "baseline_windows=%d mode=%s"
        ),
        ",".join(settings.incident_payment_methods),
        settings.incident_currency,
        settings.incident_window_minutes,
        settings.incident_baseline_window_count,
        "once" if run_once else "continuous",
    )

    await heartbeat.start()
    try:
        while True:
            try:
                result = await run_incident_detection_batch(
                    session_factory,
                    payment_methods=(settings.incident_payment_methods),
                    currency=settings.incident_currency,
                    reference_time=utc_now(),
                    window_size=window_size,
                    baseline_window_count=(settings.incident_baseline_window_count),
                )
            except asyncio.CancelledError:
                raise
            except Exception as error:
                await heartbeat.record_failure(error)
                LOGGER.exception(
                    "Incident detection batch failed",
                )

                if run_once:
                    raise

                await asyncio.sleep(
                    settings.incident_poll_interval_seconds,
                )
                continue

            await heartbeat.record_success(
                {
                    "attempted": result.attempted,
                    "succeeded": result.succeeded,
                    "failed": result.failed,
                },
            )

            log_batch_result(result)

            if run_once:
                return

            await asyncio.sleep(
                settings.incident_poll_interval_seconds,
            )
    finally:
        await heartbeat.stop()
        await asyncio.gather(close_redis(), close_database())
        LOGGER.info(
            "Incident detection worker stopped",
        )


def parse_run_once() -> bool:
    parser = argparse.ArgumentParser(
        description=("Detect ReclaimRail payment degradation incidents."),
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run one detection batch and exit.",
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
            run_incident_detection_worker(
                run_once=parse_run_once(),
            ),
        )
    except KeyboardInterrupt:
        LOGGER.info(
            "Incident detection worker interrupted",
        )


if __name__ == "__main__":
    main()
