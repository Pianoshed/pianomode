from collections.abc import Callable
from datetime import timedelta

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.core.errors import ServiceUnavailableError
from app.models.base import utcnow
from app.models.billing import ExpiryNotice, Institution, Subscription
from app.models.user import Role, User
from app.services import email as email_module
from app.services.email import (
    ConsoleEmailSender,
    EmailDeliveryError,
    EmailMessage,
    InMemoryEmailSender,
    ResendEmailSender,
)
from app.services.expiry_service import due_kind, send_expiry_reminders

SETTINGS = Settings(public_web_url="https://piano.example")


def add_sub(
    sf: sessionmaker[Session], user_email: str, ends_in: timedelta, plan: str = "individual"
):
    with sf() as s:
        user = s.scalar(select(User).where(User.email == user_email))
        sub = Subscription(user_id=user.id, plan_code=plan, current_period_end=utcnow() + ends_in)
        s.add(sub)
        s.commit()
        return sub.id


def run(sf: sessionmaker[Session], sender, now=None):
    with sf() as s:
        return send_expiry_reminders(s, sender, SETTINGS, now)


# ------------------------------------------------------------------ Resend


def test_resend_posts_the_message(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict = {}

    def fake_post(url, headers, json, timeout):
        seen.update(url=url, headers=headers, json=json)
        return httpx.Response(200, json={"id": "abc"})

    monkeypatch.setattr(httpx, "post", fake_post)
    ResendEmailSender("re_key", "Piano <hi@piano.example>").send(
        EmailMessage("a@b.com", "Hi", "Body")
    )
    assert seen["url"] == "https://api.resend.com/emails"
    assert seen["headers"]["Authorization"] == "Bearer re_key"
    assert seen["json"] == {
        "from": "Piano <hi@piano.example>",
        "to": ["a@b.com"],
        "subject": "Hi",
        "text": "Body",
    }


def test_resend_refusal_and_network_failure_raise_delivery_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        httpx, "post", lambda *a, **k: httpx.Response(403, text="domain not verified")
    )
    with pytest.raises(EmailDeliveryError):
        ResendEmailSender("k", "x").send(EmailMessage("a@b.com", "s", "b"))

    def boom(*a, **k):
        raise httpx.ConnectError("down")

    monkeypatch.setattr(httpx, "post", boom)
    with pytest.raises(EmailDeliveryError):
        ResendEmailSender("k", "x").send(EmailMessage("a@b.com", "s", "b"))


def test_sender_choice(monkeypatch: pytest.MonkeyPatch) -> None:
    def use(settings: Settings) -> None:
        monkeypatch.setattr(email_module, "get_settings", lambda: settings)

    use(Settings(resend_api_key="re_x"))
    assert isinstance(email_module.build_sender(), ResendEmailSender)
    use(Settings())
    assert isinstance(email_module.build_sender(), ConsoleEmailSender)
    use(Settings(env="production"))
    with pytest.raises(ServiceUnavailableError):
        email_module.build_sender()


# ------------------------------------------------------------------ timing


@pytest.mark.parametrize(
    "left,expected",
    [
        (timedelta(days=20), None),
        (timedelta(days=7), "d7"),
        (timedelta(days=5), "d7"),
        (timedelta(days=3), "d3"),
        (timedelta(days=2), "d3"),
        (timedelta(hours=23), "d1"),
        (timedelta(seconds=-1), "expired"),
        (timedelta(days=-3), "expired"),
        (timedelta(days=-4), None),
    ],
)
def test_due_kind(left: timedelta, expected: str | None) -> None:
    now = utcnow()
    assert due_kind(now + left, now) == expected


# ------------------------------------------------------------------ the job


def test_reminder_goes_out_once_per_kind(make_user: Callable[..., User], session_factory) -> None:
    make_user("a@example.com")
    add_sub(session_factory, "a@example.com", timedelta(days=2, hours=12))
    out = InMemoryEmailSender()
    assert run(session_factory, out).sent == 1
    assert run(session_factory, out).sent == 0  # same job again: nothing new
    assert len(out.messages) == 1
    m = out.messages[0]
    assert m.to == "a@example.com" and "ends in 3 days" in m.subject
    assert "https://piano.example/subscription" in m.body and "Account Settings" in m.body

    # A day later the next, more urgent reminder is due and goes out.
    assert run(session_factory, out, utcnow() + timedelta(days=1, hours=13)).sent == 1
    assert "ends in 1 day" in out.messages[-1].subject


def test_ended_email_then_silence(make_user, session_factory) -> None:
    make_user("a@example.com")
    add_sub(session_factory, "a@example.com", -timedelta(hours=5))
    out = InMemoryEmailSender()
    assert run(session_factory, out).sent == 1
    assert "has ended" in out.messages[0].subject
    assert run(session_factory, InMemoryEmailSender(), utcnow() + timedelta(days=5)).sent == 0


def test_nothing_for_plans_far_from_ending(make_user, session_factory) -> None:
    make_user("a@example.com")
    add_sub(session_factory, "a@example.com", timedelta(days=25))
    assert run(session_factory, InMemoryEmailSender()).sent == 0


def test_trial_wording(make_user, session_factory) -> None:
    make_user("a@example.com")
    add_sub(session_factory, "a@example.com", timedelta(days=1, hours=2), plan="trial")
    out = InMemoryEmailSender()
    run(session_factory, out)
    assert "trial" in out.messages[0].subject and "free trial" in out.messages[0].body


def test_renewal_starts_a_fresh_set_of_reminders(make_user, session_factory) -> None:
    make_user("a@example.com")
    sub_id = add_sub(session_factory, "a@example.com", timedelta(days=2))
    out = InMemoryEmailSender()
    run(session_factory, out)
    with session_factory() as s:  # renewed for a month, then that month runs down again
        s.get(Subscription, sub_id).current_period_end = utcnow() + timedelta(days=2)
        s.commit()
    assert run(session_factory, out).sent == 1
    assert len(out.messages) == 2


def test_opt_out_staff_inactive_and_seats_are_skipped(make_user, session_factory) -> None:
    make_user("off@example.com")
    make_user("edu@example.com", roles=(Role.EDUCATOR,))
    make_user("gone@example.com", active=False)
    for e in ("off@example.com", "edu@example.com", "gone@example.com"):
        add_sub(session_factory, e, timedelta(days=2))
    with session_factory() as s:
        s.scalar(select(User).where(User.email == "off@example.com")).reminder_emails = False
        s.commit()
    out = InMemoryEmailSender()
    assert run(session_factory, out).sent == 0 and out.messages == []


def test_institution_reminder_goes_to_the_owner(make_user, session_factory) -> None:
    make_user("owner@school.ng")
    with session_factory() as s:
        owner = s.scalar(select(User).where(User.email == "owner@school.ng"))
        inst = Institution(name="Grace School", code="GRAC", owner_id=owner.id)
        s.add(inst)
        s.flush()
        s.add(
            Subscription(
                institution_id=inst.id,
                plan_code="institution_10",
                seats=10,
                current_period_end=utcnow() + timedelta(days=6),
            )
        )
        s.commit()
    out = InMemoryEmailSender()
    assert run(session_factory, out).sent == 1
    m = out.messages[0]
    assert m.to == "owner@school.ng" and "Grace School" in m.body and "logins" in m.body


def test_failed_send_is_retried_next_run(make_user, session_factory) -> None:
    make_user("a@example.com")
    add_sub(session_factory, "a@example.com", timedelta(days=2))

    class Down:
        def send(self, message: EmailMessage) -> None:
            raise EmailDeliveryError("down")

    r = run(session_factory, Down())
    assert (r.sent, r.failed) == (0, 1)
    with session_factory() as s:
        assert s.scalars(select(ExpiryNotice)).all() == []
    out = InMemoryEmailSender()
    assert run(session_factory, out).sent == 1


# ------------------------------------------------------------------ API


def test_reminders_can_be_switched_off_in_settings(client: TestClient, make_user, sign_in) -> None:
    make_user("a@example.com")
    sign_in("a@example.com")
    assert client.get("/api/v1/auth/me").json()["reminder_emails"] is True
    r = client.patch("/api/v1/auth/me/preferences", json={"reminder_emails": False})
    assert r.status_code == 200 and r.json()["reminder_emails"] is False
    assert client.get("/api/v1/auth/me").json()["reminder_emails"] is False


def test_admin_lookup_payments_and_manual_reminder_run(
    client: TestClient, make_user, sign_in, session_factory, outbox
) -> None:
    make_user("admin@example.com", roles=(Role.ADMIN,))
    make_user("buyer@example.com")
    add_sub(session_factory, "buyer@example.com", timedelta(days=2))
    sign_in("admin@example.com")

    assert client.get("/api/v1/admin/billing/lookup", params={"email": "nobody@x.com"}).json() == {
        "found": False,
        "user": None,
        "entitlement": None,
        "institution": None,
    }
    # Looking up someone with no plan must not start a trial for them.
    make_user("fresh@example.com")
    r = client.get("/api/v1/admin/billing/lookup", params={"email": "Fresh@Example.com"}).json()
    assert r["found"] and r["entitlement"]["reason"] == "none"
    with session_factory() as s:
        fresh = s.scalar(select(User).where(User.email == "fresh@example.com"))
        assert s.scalar(select(Subscription).where(Subscription.user_id == fresh.id)) is None

    client.post(
        "/api/v1/admin/billing/grant",
        json={"email": "fresh@example.com", "plan": "institution_10", "institution_name": "Zion"},
    )
    r = client.get("/api/v1/admin/billing/lookup", params={"email": "fresh@example.com"}).json()
    assert r["institution"]["name"] == "Zion" and r["institution"]["seats_allowed"] == 10

    pays = client.get("/api/v1/admin/billing/payments").json()["payments"]
    assert pays[0]["email"] == "fresh@example.com" and pays[0]["reference"].startswith("manual_")

    run_result = client.post("/api/v1/admin/billing/send-reminders").json()
    assert run_result["sent"] >= 1 and any(m.to == "buyer@example.com" for m in outbox.messages)


def test_admin_billing_tools_are_admin_only(client: TestClient, make_user, sign_in) -> None:
    make_user("a@example.com")
    sign_in("a@example.com")
    assert (
        client.get("/api/v1/admin/billing/lookup", params={"email": "a@example.com"}).status_code
        == 403
    )
    assert client.get("/api/v1/admin/billing/payments").status_code == 403
    assert client.post("/api/v1/admin/billing/send-reminders").status_code == 403
