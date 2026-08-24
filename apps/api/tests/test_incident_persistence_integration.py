import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import (
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import get_settings
from app.db.models.incident import (
    IncidentDetectionObservation,
    RevenueIncident,
)
from app.domain.incidents import (
    IncidentDetectionOutcome,
    IncidentScope,
    PaymentWindowMetrics,
    build_baseline_profile,
    build_incident_fingerprint,
    detect_payment_degradation,
)
from app.services.incident_persistence import (
    IncidentPersistenceResult,
    persist_incident_detection,
)

BASE_TIME = datetime(
    2026,
    8,
    24,
    10,
    0,
    tzinfo=UTC,
)


def create_window(
    index: int,
    *,
    dimension_value: str,
    total_attempts: int,
    failed_attempts: int,
    failed_amount_minor: int,
) -> PaymentWindowMetrics:
    window_start = BASE_TIME + timedelta(
        minutes=index * 5,
    )

    return PaymentWindowMetrics(
        scope=IncidentScope.PAYMENT_METHOD,
        dimension_value=dimension_value,
        window_start=window_start,
        window_end=window_start + timedelta(minutes=5),
        total_attempts=total_attempts,
        failed_attempts=failed_attempts,
        total_amount_minor=5_000_000,
        failed_amount_minor=failed_amount_minor,
    )


@pytest.mark.asyncio
async def test_concurrent_detection_creates_one_active_incident() -> None:
    settings = get_settings()

    if settings.database_url is None:
        pytest.skip("Database URL is not configured")

    database_url = settings.database_url.get_secret_value()

    if not database_url:
        pytest.skip("Database URL is empty")

    engine = create_async_engine(
        database_url,
        pool_pre_ping=True,
    )
    session_factory = async_sessionmaker(
        engine,
        expire_on_commit=False,
    )

    unique_suffix = uuid4().hex[:12]
    dimension_value = f"upi-concurrency-{unique_suffix}"

    historical_windows = [
        create_window(
            index,
            dimension_value=dimension_value,
            total_attempts=100,
            failed_attempts=failed_count,
            failed_amount_minor=failed_count * 10_000,
        )
        for index, failed_count in enumerate(
            [
                4,
                5,
                6,
                5,
                5,
                4,
                6,
                5,
            ],
        )
    ]

    baseline = build_baseline_profile(
        historical_windows,
    )
    metrics = create_window(
        20,
        dimension_value=dimension_value,
        total_attempts=100,
        failed_attempts=40,
        failed_amount_minor=800_000,
    )
    decision = detect_payment_degradation(
        metrics,
        baseline,
    )
    fingerprint = build_incident_fingerprint(
        IncidentScope.PAYMENT_METHOD,
        dimension_value,
    )

    assert decision.outcome is IncidentDetectionOutcome.INCIDENT

    async def persist_once(
        detector_run_id: UUID,
    ) -> IncidentPersistenceResult:
        async with (
            session_factory() as session,
            session.begin(),
        ):
            return await persist_incident_detection(
                session,
                detector_run_id=detector_run_id,
                metrics=metrics,
                baseline=baseline,
                decision=decision,
                currency="INR",
                detected_at=BASE_TIME + timedelta(hours=4),
            )

    try:
        results = await asyncio.gather(
            persist_once(uuid4()),
            persist_once(uuid4()),
        )

        assert sum(result.created_incident for result in results) == 1
        assert sum(result.duplicate_observation for result in results) == 1
        assert all(result.incident_id is not None for result in results)
        assert results[0].incident_id == results[1].incident_id

        async with session_factory() as session:
            incident_count_result = await session.execute(
                select(
                    func.count(RevenueIncident.id),
                ).where(
                    RevenueIncident.fingerprint == fingerprint,
                    RevenueIncident.currency == "INR",
                ),
            )
            observation_count_result = await session.execute(
                select(
                    func.count(
                        IncidentDetectionObservation.id,
                    ),
                ).where(
                    IncidentDetectionObservation.fingerprint == fingerprint,
                    IncidentDetectionObservation.currency == "INR",
                ),
            )
            incident_result = await session.execute(
                select(RevenueIncident).where(
                    RevenueIncident.fingerprint == fingerprint,
                    RevenueIncident.currency == "INR",
                ),
            )

            incident_count = incident_count_result.scalar_one()
            observation_count = observation_count_result.scalar_one()
            incident = incident_result.scalar_one()

        assert incident_count == 1
        assert observation_count == 1
        assert incident.occurrence_count == 1
        assert incident.fingerprint == fingerprint
        assert incident.revenue_at_risk_minor == 800_000
    finally:
        try:
            async with (
                session_factory() as cleanup_session,
                cleanup_session.begin(),
            ):
                await cleanup_session.execute(
                    delete(
                        IncidentDetectionObservation,
                    ).where(
                        IncidentDetectionObservation.fingerprint == fingerprint,
                    ),
                )
                await cleanup_session.execute(
                    delete(RevenueIncident).where(
                        RevenueIncident.fingerprint == fingerprint,
                    ),
                )
        finally:
            await engine.dispose()
