from collections.abc import Callable
from datetime import timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.core import crypto
from app.core.config import Settings, get_settings
from app.models.base import ensure_utc, utcnow
from app.models.billing import Payment, SavedCard, Subscription
from app.models.user import User
from app.services import billing_service, renewal_service
from app.services.email import InMemoryEmailSender
from app.services.paystack import (
    CardAuthorization,
    CheckoutSession,
    PaystackError,
    VerifiedTransaction,
    get_paystack_client,
)

SETTINGS = Settings(
    paystack_secret_key="sk_test_x",
    auto_renewal_enabled=True,
    public_web_url="https://piano.example",
    cors_origins=["http://localhost:3000"],
)
CARD = CardAuthorization(
    code="AUTH_abc123",
    reusable=True,
    channel="card",
    brand="visa",
    last4="4081",
    exp_month="12",
    exp_year="2030",
)


class FakePaystack:
    def __init__(self) -> None:
        self.amounts: dict[str, int] = {}
        self.statuses: dict[str, str] = {}
        self.auth: CardAuthorization | None = CARD
        self.charge_status = "success"
        self.charge_raises = False
        self.charges: list[tuple[str, int, str]] = []

    def initialize(self, *, email, amount_kobo, reference, callback_url, metadata):  # type: ignore[no-untyped-def]
        self.amounts[reference] = amount_kobo
        return CheckoutSession(f"https://checkout.test/{reference}", "code")

    def charge_authorization(self, *, email, amount_kobo, reference, authorization_code, metadata):  # type: ignore[no-untyped-def]
        if self.charge_raises:
            raise PaystackError("down")
        self.charges.append((reference, amount_kobo, authorization_code))
        self.amounts[reference] = amount_kobo
        self.statuses[reference] = self.charge_status

    def verify(self, reference: str) -> VerifiedTransaction:
        return VerifiedTransaction(
            reference,
            self.statuses.get(reference, "success"),
            self.amounts[reference],
            "NGN",
            "Approved",
            self.auth,
        )


@pytest.fixture
def ps() -> FakePaystack:
    return FakePaystack()


@pytest.fixture(autouse=True)
def overrides(app: FastAPI, ps: FakePaystack) -> None:
    app.dependency_overrides[get_paystack_client] = lambda: ps
    app.dependency_overrides[get_settings] = lambda: SETTINGS


def add_plan(
    sf: sessionmaker[Session], email: str, ends_in: timedelta, plan: str = "individual"
) -> None:
    with sf() as s:
        user = s.scalar(select(User).where(User.email == email))
        assert user is not None
        s.add(Subscription(user_id=user.id, plan_code=plan, current_period_end=utcnow() + ends_in))
        billing_service.remember_card(s, user.id, CARD)
        s.commit()


def run(
    sf: sessionmaker[Session],
    ps: FakePaystack,
    outbox: InMemoryEmailSender,
    settings: Settings = SETTINGS,
):
    with sf() as s:
        return renewal_service.run_renewals(s, ps, outbox, settings)


# ---------------------------------------------------------------- saving the card


def test_ticking_renew_at_checkout_saves_the_card_encrypted(
    client: TestClient, make_user: Callable[..., User], sign_in, session_factory, ps: FakePaystack
) -> None:
    make_user("a@example.com")
    sign_in("a@example.com")
    ref = client.post(
        "/api/v1/billing/checkout", json={"plan": "individual", "months": 1, "save_card": True}
    ).json()["reference"]
    assert client.post("/api/v1/billing/verify", json={"reference": ref}).status_code == 200

    body = client.get("/api/v1/billing/card").json()
    assert body["available"] and body["has_card"] and body["auto_renew"]
    assert body["last4"] == "4081"
    assert "AUTH_abc123" not in str(body)
    with session_factory() as s:
        stored = s.scalar(select(SavedCard.authorization_code))
        assert stored and "AUTH_abc123" not in stored
        assert crypto.decrypt(stored) == "AUTH_abc123"


def test_nothing_is_saved_without_the_tick_or_for_non_card_payments(
    client: TestClient, make_user: Callable[..., User], sign_in, ps: FakePaystack
) -> None:
    make_user("a@example.com")
    sign_in("a@example.com")
    ref = client.post("/api/v1/billing/checkout", json={"plan": "individual"}).json()["reference"]
    client.post("/api/v1/billing/verify", json={"reference": ref})
    assert client.get("/api/v1/billing/card").json()["has_card"] is False

    ps.auth = CardAuthorization(code="AUTH_t", reusable=True, channel="bank_transfer")
    ref = client.post(
        "/api/v1/billing/checkout", json={"plan": "individual", "save_card": True}
    ).json()["reference"]
    client.post("/api/v1/billing/verify", json={"reference": ref})
    assert client.get("/api/v1/billing/card").json()["has_card"] is False


def test_the_tick_is_ignored_while_the_feature_is_off(
    app: FastAPI, client: TestClient, make_user: Callable[..., User], sign_in
) -> None:
    app.dependency_overrides[get_settings] = lambda: SETTINGS.model_copy(
        update={"auto_renewal_enabled": False}
    )
    make_user("a@example.com")
    sign_in("a@example.com")
    ref = client.post(
        "/api/v1/billing/checkout", json={"plan": "individual", "save_card": True}
    ).json()["reference"]
    client.post("/api/v1/billing/verify", json={"reference": ref})
    card = client.get("/api/v1/billing/card").json()
    assert card["available"] is False and card["has_card"] is False
    assert client.post("/api/v1/billing/auto-renew", json={"enabled": True}).status_code == 409


def test_switch_off_enable_and_forget(
    client: TestClient, make_user: Callable[..., User], sign_in, session_factory
) -> None:
    make_user("a@example.com")
    sign_in("a@example.com")
    assert client.post("/api/v1/billing/auto-renew", json={"enabled": True}).status_code == 409
    add_plan(session_factory, "a@example.com", timedelta(days=10))
    assert (
        client.post("/api/v1/billing/auto-renew", json={"enabled": False}).json()["auto_renew"]
        is False
    )
    assert (
        client.post("/api/v1/billing/auto-renew", json={"enabled": True}).json()["auto_renew"]
        is True
    )
    assert client.delete("/api/v1/billing/card").status_code == 204
    assert client.get("/api/v1/billing/card").json()["has_card"] is False


# ---------------------------------------------------------------- the daily job


def test_a_plan_ending_tomorrow_is_renewed_once(
    client: TestClient,
    make_user: Callable[..., User],
    session_factory,
    ps: FakePaystack,
    outbox: InMemoryEmailSender,
) -> None:
    make_user("a@example.com")
    add_plan(session_factory, "a@example.com", timedelta(hours=10))
    before = utcnow() + timedelta(hours=10)

    r = run(session_factory, ps, outbox)
    assert (r.charged, r.failed) == (1, 0)
    assert ps.charges == [(ps.charges[0][0], 15_000 * 100, "AUTH_abc123")]
    with session_factory() as s:
        sub = s.scalar(select(Subscription))
        assert ensure_utc(sub.current_period_end) >= before + timedelta(days=29, hours=23)
        pay = s.scalar(select(Payment))
        assert (pay.kind, pay.status, pay.months) == ("renewal", "success", 1)
    receipt = outbox.messages[-1]
    assert "Automatic renewal" in receipt.subject and "4081" in receipt.body

    again = run(session_factory, ps, outbox)  # same day: nothing more is charged
    assert again.charged == 0 and len(ps.charges) == 1


@pytest.mark.parametrize(
    "ends_in",
    [timedelta(days=10), -timedelta(days=5)],
    ids=["not due yet", "ended too long ago"],
)
def test_only_plans_ending_within_a_day_are_charged(
    make_user: Callable[..., User],
    session_factory,
    ps: FakePaystack,
    outbox: InMemoryEmailSender,
    ends_in: timedelta,
) -> None:
    make_user("a@example.com")
    add_plan(session_factory, "a@example.com", ends_in)
    assert run(session_factory, ps, outbox).charged == 0 and not ps.charges


def test_trials_and_switched_off_cards_and_a_disabled_feature_are_never_charged(
    make_user: Callable[..., User], session_factory, ps: FakePaystack, outbox: InMemoryEmailSender
) -> None:
    make_user("a@example.com")
    add_plan(session_factory, "a@example.com", timedelta(hours=5), plan="trial")
    assert run(session_factory, ps, outbox).charged == 0

    with session_factory() as s:
        s.scalar(select(Subscription)).plan_code = "individual"
        s.scalar(select(SavedCard)).auto_renew = False
        s.commit()
    assert run(session_factory, ps, outbox).charged == 0

    with session_factory() as s:
        s.scalar(select(SavedCard)).auto_renew = True
        s.commit()
    off = SETTINGS.model_copy(update={"auto_renewal_enabled": False})
    assert run(session_factory, ps, outbox, off).charged == 0
    assert not ps.charges


def test_a_declined_card_is_emailed_and_switches_off_after_three_tries(
    make_user: Callable[..., User], session_factory, ps: FakePaystack, outbox: InMemoryEmailSender
) -> None:
    make_user("a@example.com")
    add_plan(session_factory, "a@example.com", timedelta(hours=5))
    ps.charge_status = "failed"
    for attempt in (1, 2, 3):
        assert run(session_factory, ps, outbox).failed == 1
        with session_factory() as s:
            card = s.scalar(select(SavedCard))
            assert card.failures == attempt
            assert ensure_utc(
                s.scalar(select(Subscription)).current_period_end
            ) < utcnow() + timedelta(days=1)
            # let the next day's attempt happen
            for p in s.scalars(select(Payment)):
                p.created_at = utcnow() - timedelta(days=attempt)
            s.commit()
    assert card.auto_renew is False
    assert "automatic renewal is now off" in outbox.messages[-1].body
    assert run(session_factory, ps, outbox).charged == 0  # now off: no fourth try


def test_paystack_being_down_counts_as_a_failed_try_not_a_crash(
    make_user: Callable[..., User], session_factory, ps: FakePaystack, outbox: InMemoryEmailSender
) -> None:
    make_user("a@example.com")
    add_plan(session_factory, "a@example.com", timedelta(hours=5))
    ps.charge_raises = True
    assert run(session_factory, ps, outbox).failed == 1
    with session_factory() as s:
        assert s.scalar(select(SavedCard)).failures == 1
        assert s.scalar(select(Payment)).status == "failed"


def test_reminders_tell_a_renewing_person_what_will_be_charged(
    make_user: Callable[..., User], session_factory, outbox: InMemoryEmailSender
) -> None:
    from app.services.expiry_service import send_expiry_reminders

    make_user("a@example.com")
    add_plan(session_factory, "a@example.com", timedelta(days=2))
    with session_factory() as s:
        send_expiry_reminders(s, outbox, SETTINGS)
    msg = outbox.messages[-1]
    assert "renews" in msg.subject and "4081" in msg.body and "NGN 15,000" in msg.body
