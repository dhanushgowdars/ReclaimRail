from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes import payment_lab
from app.core.config import Settings, get_settings
from app.core.database import get_database_session
from app.db.models.payment_lab import PaymentLabRunMode, PaymentLabRunProvenance
from app.integrations.razorpay.orders import RazorpayOrderProvider
from app.main import app
from app.services.payment_lab_service import PaymentLabRunCreationResult

NOW = datetime(2026, 8, 26, 16, 0, tzinfo=UTC)
CLIENT_REQUEST_ID = UUID("10000000-0000-0000-0000-000000000001")
RUN_ID = UUID("20000000-0000-0000-0000-000000000001")


async def override_database_session() -> AsyncIterator[AsyncSession]:
    yield MagicMock(spec=AsyncSession)


def build_test_settings() -> Settings:
    return Settings(
        razorpay_key_id=SecretStr("rzp_test_key"),
        razorpay_key_secret=SecretStr("test-secret"),
        payment_lab_access_token=SecretStr("lab-secret"),
    )


@pytest.fixture(autouse=True)
def dependency_overrides() -> Iterator[None]:
    app.dependency_overrides[get_database_session] = override_database_session
    app.dependency_overrides[get_settings] = build_test_settings

    yield

    app.dependency_overrides.clear()


def build_result(
    *,
    created: bool = True,
    test_email_contact_consent: bool = False,
) -> PaymentLabRunCreationResult:
    return PaymentLabRunCreationResult(
        payment_lab_run_id=RUN_ID,
        client_request_id=CLIENT_REQUEST_ID,
        mode=PaymentLabRunMode.GUIDED,
        provenance=PaymentLabRunProvenance.RAZORPAY_TEST,
        amount_minor=349_900,
        currency="INR",
        payment_method="netbanking",
        test_email_contact_consent=test_email_contact_consent,
        provider_order_id="order_test_001",
        checkout_expires_at=NOW + timedelta(minutes=10),
        created=created,
    )


def configure_provider_and_service(
    monkeypatch: pytest.MonkeyPatch,
    *,
    created: bool = True,
    test_email_contact_consent: bool = False,
) -> AsyncMock:
    provider = MagicMock(spec=RazorpayOrderProvider)
    provider.checkout_key_id = "rzp_test_key"
    create_run = AsyncMock(
        return_value=build_result(
            created=created,
            test_email_contact_consent=test_email_contact_consent,
        ),
    )

    monkeypatch.setattr(
        payment_lab,
        "create_razorpay_order_provider",
        lambda settings: provider,
    )
    monkeypatch.setattr(payment_lab, "create_payment_lab_run", create_run)
    return create_run


def test_creates_guided_test_mode_checkout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    create_run = configure_provider_and_service(monkeypatch)

    with TestClient(app) as client:
        response = client.post(
            "/payment-lab/runs",
            headers={"X-ReclaimRail-Lab-Token": "lab-secret"},
            json={
                "client_request_id": str(CLIENT_REQUEST_ID),
                "mode": "guided",
            },
        )

    assert response.status_code == 201
    body = response.json()
    assert body["payment_lab_run_id"] == str(RUN_ID)
    assert body["provenance"] == "razorpay_test"
    assert body["test_mode"] is True
    assert body["checkout"] == {
        "key_id": "rzp_test_key",
        "order_id": "order_test_001",
        "amount_minor": 349_900,
        "currency": "INR",
        "name": "ReclaimRail Payment Lab",
        "description": "Razorpay Test Mode recovery scenario",
        "timeout_seconds": 600,
        "theme_color": "#0B5FFF",
        "payment_method_hint": "netbanking",
        "prefill_email": None,
    }
    assert "test-secret" not in response.text
    assert "lab-secret" not in response.text
    await_args = create_run.await_args
    assert await_args is not None
    assert await_args.kwargs["amount_minor"] == 349_900
    assert await_args.kwargs["payment_method"] == "netbanking"
    assert await_args.kwargs["test_email_contact_consent"] is False


def test_creates_consent_recorded_test_email_checkout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def settings_with_demo_email() -> Settings:
        return Settings(
            razorpay_key_id=SecretStr("rzp_test_key"),
            razorpay_key_secret=SecretStr("test-secret"),
            payment_lab_access_token=SecretStr("lab-secret"),
            payment_lab_demo_email_recipient=SecretStr("demo@example.test"),
        )

    app.dependency_overrides[get_settings] = settings_with_demo_email
    create_run = configure_provider_and_service(
        monkeypatch,
        test_email_contact_consent=True,
    )

    with TestClient(app) as client:
        response = client.post(
            "/payment-lab/runs",
            headers={"X-ReclaimRail-Lab-Token": "lab-secret"},
            json={
                "client_request_id": str(CLIENT_REQUEST_ID),
                "mode": "guided",
                "enable_test_email_recovery_notification": True,
            },
        )

    assert response.status_code == 201
    assert response.json()["checkout"]["prefill_email"] == "demo@example.test"
    assert create_run.await_args.kwargs["test_email_contact_consent"] is True


def test_creates_custom_run_with_bounded_inputs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    create_run = configure_provider_and_service(monkeypatch)

    with TestClient(app) as client:
        response = client.post(
            "/payment-lab/runs",
            headers={"X-ReclaimRail-Lab-Token": "lab-secret"},
            json={
                "client_request_id": str(CLIENT_REQUEST_ID),
                "mode": "custom",
                "amount_minor": 250_000,
                "payment_method": "upi",
            },
        )

    assert response.status_code == 201
    await_args = create_run.await_args
    assert await_args is not None
    assert await_args.kwargs["amount_minor"] == 250_000
    assert await_args.kwargs["payment_method"] == "upi"


def test_rejects_missing_access_token_before_provider_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    create_provider = MagicMock()
    monkeypatch.setattr(
        payment_lab,
        "create_razorpay_order_provider",
        create_provider,
    )

    with TestClient(app) as client:
        response = client.post(
            "/payment-lab/runs",
            json={
                "client_request_id": str(CLIENT_REQUEST_ID),
                "mode": "guided",
            },
        )

    assert response.status_code == 401
    create_provider.assert_not_called()


def test_idempotent_replay_returns_existing_checkout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure_provider_and_service(monkeypatch, created=False)

    with TestClient(app) as client:
        response = client.post(
            "/payment-lab/runs",
            headers={"X-ReclaimRail-Lab-Token": "lab-secret"},
            json={
                "client_request_id": str(CLIENT_REQUEST_ID),
                "mode": "guided",
            },
        )

    assert response.status_code == 200


@pytest.mark.parametrize(
    "payload",
    [
        {"mode": "guided", "amount_minor": 100},
        {"mode": "custom", "payment_method": "upi"},
        {"mode": "replay"},
    ],
)
def test_rejects_invalid_mode_inputs(payload: dict[str, object]) -> None:
    payload["client_request_id"] = str(CLIENT_REQUEST_ID)

    with TestClient(app) as client:
        response = client.post(
            "/payment-lab/runs",
            headers={"X-ReclaimRail-Lab-Token": "lab-secret"},
            json=payload,
        )

    assert response.status_code == 422
