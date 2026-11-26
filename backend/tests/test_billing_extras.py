"""Receipts, upgrades, refunds, and the administrator tools around them."""

# ruff: noqa: F811  (test arguments reuse the names of the fixtures imported from test_billing)

import hashlib
import hmac
import json
from datetime import timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.config import get_settings
from app.core.errors import AppError
from app.models.audit import AdminAction
from app.models.base import ensure_utc, utcnow
from app.models.billing import Payment, Subscription
from app.models.user import Role, User
from app.services.email import EmailMessage, get_email_sender
from tests.test_billing import (  # noqa: F401  (fixtures and helpers shared with test_billing)
    SECRET,
    FakePaystack,
    billing_overrides,
    login,
    make_seats,
    other_client,
    owner,
    pay,
    paystack,
    status,
)

KOBO = 100


def sub_of(session_factory, *, institution: bool):
    with session_factory() as s:
        q = select(Subscription).where(
            Subscription.institution_id.is_not(None)
            if institution
            else Subscription.user_id.is_not(None)
        )
        sub = s.scalar(q)
        return sub.plan_code, sub.seats, ensure_utc(sub.current_period_end)


def move_end(session_factory, delta: timedelta) -> None:
    with session_factory() as s:
        sub = s.scalar(select(Subscription).where(Subscription.institution_id.is_not(None)))
        sub.current_period_end = utcnow() + delta
        s.commit()


def attempt(c: TestClient, who: str, password: str = "correct horse battery"):
    """A sign-in whose result the test checks itself (the shared `login` insists on success)."""
    return c.post("/api/v1/auth/login", json={"identifier": who, "password": password})


def webhook(client: TestClient, body: dict, key: str = SECRET):
    raw = json.dumps(body).encode()
    sig = hmac.new(key.encode(), raw, hashlib.sha512).hexdigest()
    return client.post(
        "/api/v1/billing/webhooks/paystack", content=raw, headers={"x-paystack-signature": sig}
    )


# ------------------------------------------------------------------ receipts


def test_a_receipt_is_emailed_once_when_a_payment_succeeds(
    client, make_user, sign_in, paystack, outbox
) -> None:
    make_user("a@example.com")
    sign_in("a@example.com")
    ref = client.post("/api/v1/billing/checkout", json={"plan": "individual", "months": 2}).json()[
        "reference"
    ]
    client.post("/api/v1/billing/verify", json={"reference": ref})
    client.post("/api/v1/billing/verify", json={"reference": ref})  # asking again does not resend
    receipts = [m for m in outbox.messages if m.subject.startswith("Receipt")]
    assert len(receipts) == 1
    m = receipts[0]
    assert m.to == "a@example.com" and "Individual, 2 months" in m.subject
    assert "NGN 30,000" in m.body and ref in m.body and "Access until" in m.body


def test_the_webhook_sends_the_receipt_too(client, make_user, sign_in, paystack, outbox) -> None:
    make_user("a@example.com")
    sign_in("a@example.com")
    ref = client.post("/api/v1/billing/checkout", json={"plan": "individual"}).json()["reference"]
    assert (
        webhook(client, {"event": "charge.success", "data": {"reference": ref}}).status_code == 200
    )
    assert sum(m.subject.startswith("Receipt") for m in outbox.messages) == 1


def test_an_email_failure_never_undoes_a_payment(
    app: FastAPI, client, make_user, sign_in, paystack
) -> None:
    class Down:
        def send(self, message: EmailMessage) -> None:
            raise AppError("down")

    app.dependency_overrides[get_email_sender] = lambda: Down()
    make_user("a@example.com")
    sign_in("a@example.com")
    result = pay(client, paystack, "individual")
    assert (
        result["payment"]["status"] == "success" and result["entitlement"]["source"] == "individual"
    )


def test_institution_receipt_points_to_creating_logins(owner, outbox) -> None:
    m = next(m for m in outbox.messages if m.subject.startswith("Receipt"))
    assert "/institution" in m.body and "NGN 80,000" in m.body


# ------------------------------------------------------------------ upgrades


def test_the_upgrade_price_is_the_difference_for_the_time_left(owner, session_factory) -> None:
    full = owner.get("/api/v1/billing/upgrade-quote", params={"plan": "institution_20"}).json()
    assert 6_990_000 <= full["amount_kobo"] <= 7_000_000  # N70,000 for a whole month
    assert (full["from_plan"], full["plan"], full["seats"]) == (
        "institution_10",
        "institution_20",
        20,
    )

    move_end(session_factory, timedelta(days=15, minutes=1))
    half = owner.get("/api/v1/billing/upgrade-quote", params={"plan": "institution_20"}).json()
    assert 3_490_000 <= half["amount_kobo"] <= 3_501_000 and half["days_left"] == 15


def test_paying_for_an_upgrade_changes_the_plan_but_not_the_end_date(
    owner, paystack, session_factory, outbox
) -> None:
    move_end(session_factory, timedelta(days=10, minutes=1))
    before = sub_of(session_factory, institution=True)[2]
    make_seats(owner, *[f"S{i}" for i in range(10)])
    r = owner.post("/api/v1/billing/checkout", json={"plan": "institution_20", "months": 5})
    assert r.status_code == 200
    quote = owner.get("/api/v1/billing/upgrade-quote", params={"plan": "institution_20"}).json()
    assert (
        abs(r.json()["amount_kobo"] - quote["amount_kobo"]) < 1000
    )  # the browser's "5 months" was ignored
    ref = r.json()["reference"]
    assert paystack.initialized[ref] == r.json()["amount_kobo"]
    v = owner.post("/api/v1/billing/verify", json={"reference": ref}).json()
    assert v["payment"]["status"] == "success" and v["payment"]["kind"] == "upgrade"
    plan, seats, after = sub_of(session_factory, institution=True)
    assert (plan, seats) == ("institution_20", 20) and after == before
    assert len(make_seats(owner, *[f"T{i}" for i in range(10)])) == 10  # room for ten more now
    assert any(m.subject == "Receipt: Upgrade to Institution, 20 people" for m in outbox.messages)


def test_downgrades_still_wait_for_the_end_of_the_period(owner, paystack, session_factory) -> None:
    move_end(session_factory, timedelta(days=10))
    pay(owner, paystack, "institution_10", 1)  # renewing the same plan is fine
    r = owner.post("/api/v1/billing/checkout", json={"plan": "institution_20"})
    pay_ref = r.json()["reference"]
    owner.post("/api/v1/billing/verify", json={"reference": pay_ref})
    r = owner.post("/api/v1/billing/checkout", json={"plan": "institution_10"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "plan_change_not_allowed"


def test_upgrade_edge_cases(owner, session_factory) -> None:
    assert (
        owner.get("/api/v1/billing/upgrade-quote", params={"plan": "institution_10"}).json()[
            "error"
        ]["code"]
        == "not_an_upgrade"
    )
    assert (
        owner.get("/api/v1/billing/upgrade-quote", params={"plan": "individual"}).status_code == 422
    )
    assert owner.get("/api/v1/billing/upgrade-quote", params={"plan": "nope"}).status_code == 422
    move_end(session_factory, timedelta(hours=5))
    r = owner.get("/api/v1/billing/upgrade-quote", params={"plan": "institution_20"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "too_late"
    move_end(session_factory, -timedelta(days=1))
    r = owner.get("/api/v1/billing/upgrade-quote", params={"plan": "institution_20"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "plan_ended"


def test_only_a_running_institution_owner_gets_a_quote(client, make_user, sign_in) -> None:
    make_user("a@example.com")
    sign_in("a@example.com")
    assert (
        client.get("/api/v1/billing/upgrade-quote", params={"plan": "institution_20"}).status_code
        == 422
    )


# ------------------------------------------------------------------ refunds


@pytest.fixture
def boss(app: FastAPI, make_user, other_client: TestClient) -> TestClient:
    make_user("boss@example.com", roles=(Role.ADMIN,))
    login(other_client, "boss@example.com")
    return other_client


def refund(admin: TestClient, ref: str, reason: str = "customer asked"):
    return admin.post(f"/api/v1/admin/billing/payments/{ref}/refund", json={"reason": reason})


def test_refunding_a_purchase_takes_back_those_months(
    client, make_user, sign_in, paystack, boss, session_factory
) -> None:
    make_user("a@example.com")
    sign_in("a@example.com")
    pay(client, paystack, "individual", 1)
    result = pay(client, paystack, "individual", 2)  # now 3 months in total
    ref = result["payment"]["reference"]
    before = sub_of(session_factory, institution=False)[2]
    r = refund(boss, ref)
    assert r.status_code == 200 and r.json()["status"] == "refunded"
    assert before - sub_of(session_factory, institution=False)[2] == timedelta(days=60)
    assert refund(boss, ref).status_code == 409  # only once
    again = client.post("/api/v1/billing/verify", json={"reference": ref}).json()
    assert again["payment"]["status"] == "refunded"  # a late webhook cannot grant it again


def test_a_refund_never_pushes_access_into_the_past(
    client, make_user, sign_in, paystack, boss, session_factory
) -> None:
    make_user("a@example.com")
    sign_in("a@example.com")
    ref = pay(client, paystack, "individual", 1)["payment"]["reference"]
    with session_factory() as s:
        s.scalar(select(Subscription)).current_period_end = utcnow() + timedelta(days=3)
        s.commit()
    refund(boss, ref)
    assert status(client)["entitlement"]["has_access"] is False
    assert sub_of(session_factory, institution=False)[2] <= utcnow() + timedelta(seconds=5)


def test_refunding_an_upgrade_goes_back_to_the_old_plan(
    owner, paystack, boss, session_factory
) -> None:
    move_end(session_factory, timedelta(days=10, minutes=1))
    ref = owner.post("/api/v1/billing/checkout", json={"plan": "institution_20"}).json()[
        "reference"
    ]
    owner.post("/api/v1/billing/verify", json={"reference": ref})
    assert sub_of(session_factory, institution=True)[:2] == ("institution_20", 20)
    assert refund(boss, ref).status_code == 200
    assert sub_of(session_factory, institution=True)[:2] == ("institution_10", 10)


def test_an_upgrade_cannot_be_refunded_while_too_many_logins_are_open(
    owner, paystack, boss, session_factory
) -> None:
    move_end(session_factory, timedelta(days=10, minutes=1))
    ref = owner.post("/api/v1/billing/checkout", json={"plan": "institution_20"}).json()[
        "reference"
    ]
    owner.post("/api/v1/billing/verify", json={"reference": ref})
    make_seats(owner, *[f"S{i}" for i in range(15)])
    r = refund(boss, ref)
    assert r.status_code == 409 and r.json()["error"]["code"] == "too_many_active_seats"
    assert sub_of(session_factory, institution=True)[:2] == (
        "institution_20",
        20,
    )  # nothing changed


def test_refunds_are_admin_only_and_need_a_reason(
    client, make_user, sign_in, paystack, boss
) -> None:
    make_user("a@example.com")
    sign_in("a@example.com")
    ref = pay(client, paystack, "individual")["payment"]["reference"]
    assert refund(client, ref).status_code == 403
    assert refund(boss, ref, reason="x").status_code == 422
    assert refund(boss, "pp_nothing").status_code == 404


def full_refund_event(ref: str, amount: int) -> dict:
    return {
        "event": "refund.processed",
        "data": {"status": "processed", "transaction_reference": ref, "amount": amount},
    }


def test_paystack_telling_us_about_a_full_refund_takes_the_access_back(
    client, make_user, sign_in, paystack, session_factory
) -> None:
    make_user("a@example.com")
    sign_in("a@example.com")
    ref = pay(client, paystack, "individual", 1)["payment"]["reference"]
    assert webhook(client, full_refund_event(ref, 15_000 * KOBO)).status_code == 200
    with session_factory() as s:
        assert s.scalar(select(Payment).where(Payment.reference == ref)).status == "refunded"
        log = s.scalars(select(AdminAction).order_by(AdminAction.created_at)).all()
        assert log[-1].action == "payment_refunded" and log[-1].actor_email == "system (Paystack)"
    assert (
        webhook(client, full_refund_event(ref, 15_000 * KOBO)).status_code == 200
    )  # repeated: no harm


def test_a_partial_refund_is_left_for_an_administrator(
    client, make_user, sign_in, paystack, session_factory
) -> None:
    make_user("a@example.com")
    sign_in("a@example.com")
    ref = pay(client, paystack, "individual", 1)["payment"]["reference"]
    before = sub_of(session_factory, institution=False)[2]
    assert webhook(client, full_refund_event(ref, 5_000 * KOBO)).status_code == 200
    assert (
        webhook(
            client, {"event": "refund.processed", "data": {"transaction_reference": ref}}
        ).status_code
        == 200
    )  # no amount
    assert sub_of(session_factory, institution=False)[2] == before
    with session_factory() as s:
        assert s.scalar(select(Payment).where(Payment.reference == ref)).status == "success"
        assert [a.action for a in s.scalars(select(AdminAction))].count("refund_needs_review") == 2


def test_refund_webhook_ignores_strangers_and_bad_signatures(client) -> None:
    assert webhook(client, full_refund_event("pp_unknown", 100)).status_code == 200
    assert webhook(client, full_refund_event("pp_unknown", 100), key="sk_wrong").status_code == 401


# ------------------------------------------------------------------ admin: people


def row_for(admin: TestClient, q: str) -> dict:
    users = admin.get("/api/v1/admin/users", params={"q": q}).json()["users"]
    assert len(users) == 1, users
    return users[0]


def test_admins_can_search_and_filter_people(boss, make_user) -> None:
    make_user("ada@school.ng")
    make_user("tunde@example.com", roles=(Role.EDUCATOR,))
    everyone = boss.get("/api/v1/admin/users").json()
    assert everyone["total"] >= 3
    assert row_for(boss, "ADA")["email"] == "ada@school.ng"  # not case sensitive
    assert row_for(boss, "school.ng")["email"] == "ada@school.ng"
    staff = boss.get("/api/v1/admin/users", params={"role": "educator"}).json()["users"]
    assert [u["email"] for u in staff] == ["tunde@example.com"]
    assert boss.get("/api/v1/admin/users", params={"q": "zzzz"}).json()["total"] == 0
    page = boss.get("/api/v1/admin/users", params={"limit": 1, "offset": 1}).json()
    assert len(page["users"]) == 1 and page["total"] == everyone["total"]


def test_user_detail_shows_plan_payments_and_library(
    boss, client, make_user, sign_in, paystack
) -> None:
    make_user("a@example.com")
    sign_in("a@example.com")
    pay(client, paystack, "individual")
    client.post("/api/v1/library", json={"kind": "audio", "title": "Take"})
    d = boss.get(f"/api/v1/admin/users/{row_for(boss, 'a@example.com')['id']}").json()
    assert d["entitlement"]["source"] == "individual" and d["kind"] == "individual"
    assert (
        d["library_items"] == 1
        and len(d["payments"]) == 1
        and d["payments"][0]["status"] == "success"
    )


def test_detail_names_the_institution_for_owners_and_their_logins(boss, owner, make_user) -> None:
    cred = make_seats(owner, "Ada")[0]
    o = boss.get(f"/api/v1/admin/users/{row_for(boss, 'owner@school.ng')['id']}").json()
    assert o["kind"] == "institution_owner" and o["institution_name"] == "Grace Music School"
    seat = boss.get(f"/api/v1/admin/users/{row_for(boss, cred['login_id'])['id']}").json()
    assert (
        seat["kind"] == "seat"
        and seat["institution_name"] == "Grace Music School"
        and seat["email"] is None
    )


def test_closing_and_reopening_an_account(boss, client, make_user, sign_in, other_client) -> None:
    make_user("a@example.com")
    sign_in("a@example.com")
    uid = row_for(boss, "a@example.com")["id"]
    assert boss.post(f"/api/v1/admin/users/{uid}/close").status_code == 204
    assert client.get("/api/v1/auth/me").status_code == 401  # signed out at once
    assert attempt(other_client, "a@example.com").status_code == 401
    assert boss.post(f"/api/v1/admin/users/{uid}/reopen").status_code == 204
    assert attempt(other_client, "a@example.com").status_code == 200


def test_admins_cannot_close_themselves_or_institution_logins(boss, owner, make_user) -> None:
    me_id = row_for(boss, "boss@example.com")["id"]
    assert boss.post(f"/api/v1/admin/users/{me_id}/close").json()["error"]["code"] == "self_action"
    cred = make_seats(owner, "Ada")[0]
    seat_id = row_for(boss, cred["login_id"])["id"]
    assert (
        boss.post(f"/api/v1/admin/users/{seat_id}/close").json()["error"]["code"] == "seat_managed"
    )


def test_sign_out_everywhere(boss, client, make_user, sign_in) -> None:
    make_user("a@example.com")
    sign_in("a@example.com")
    assert (
        boss.post(
            f"/api/v1/admin/users/{row_for(boss, 'a@example.com')['id']}/sign-out"
        ).status_code
        == 204
    )
    assert client.get("/api/v1/auth/me").status_code == 401


def test_roles_can_be_granted_and_removed_with_safeguards(
    boss, client, make_user, sign_in, other_client
) -> None:
    make_user("t@example.com")
    make_user("new@example.com", verified=False)
    uid = row_for(boss, "t@example.com")["id"]
    assert (
        boss.post(
            f"/api/v1/admin/users/{uid}/roles", json={"role": "educator", "grant": True}
        ).status_code
        == 204
    )
    assert row_for(boss, "t@example.com")["roles"] == ["educator", "learner"]
    assert (
        boss.post(
            f"/api/v1/admin/users/{uid}/roles", json={"role": "educator", "grant": True}
        ).status_code
        == 204
    )  # no-op
    assert (
        boss.post(
            f"/api/v1/admin/users/{uid}/roles", json={"role": "educator", "grant": False}
        ).status_code
        == 204
    )
    assert row_for(boss, "t@example.com")["roles"] == ["learner"]
    me_id = row_for(boss, "boss@example.com")["id"]
    assert (
        boss.post(
            f"/api/v1/admin/users/{me_id}/roles", json={"role": "admin", "grant": False}
        ).json()["error"]["code"]
        == "self_action"
    )
    unverified = row_for(boss, "new@example.com")["id"]
    assert (
        boss.post(
            f"/api/v1/admin/users/{unverified}/roles", json={"role": "admin", "grant": True}
        ).json()["error"]["code"]
        == "not_eligible"
    )
    assert (
        boss.post(
            f"/api/v1/admin/users/{uid}/roles", json={"role": "superuser", "grant": True}
        ).status_code
        == 422
    )


def test_removing_a_role_signs_that_person_out(boss, client, make_user, sign_in) -> None:
    make_user("t@example.com", roles=(Role.EDUCATOR,))
    sign_in("t@example.com")
    boss.post(
        f"/api/v1/admin/users/{row_for(boss, 't@example.com')['id']}/roles",
        json={"role": "educator", "grant": False},
    )
    assert client.get("/api/v1/auth/me").status_code == 401


def test_institution_logins_cannot_become_staff(boss, owner) -> None:
    cred = make_seats(owner, "Ada")[0]
    r = boss.post(
        f"/api/v1/admin/users/{row_for(boss, cred['login_id'])['id']}/roles",
        json={"role": "educator", "grant": True},
    )
    assert r.status_code == 403


def test_resetting_two_factor_for_a_learner_but_not_for_an_admin(
    boss, client, make_user, sign_in, session_factory
) -> None:
    from app.core import crypto
    from app.models.base import utcnow as now

    make_user("a@example.com")
    make_user("admin2@example.com", roles=(Role.ADMIN,))
    for email in ("a@example.com", "admin2@example.com"):
        with session_factory() as s:
            u = s.scalar(select(User).where(User.email == email))
            u.totp_secret, u.totp_enabled_at = crypto.encrypt("JBSWY3DPEHPK3PXP"), now()
            s.commit()
    a = row_for(boss, "a@example.com")["id"]
    assert boss.post(f"/api/v1/admin/users/{a}/reset-two-factor").status_code == 204
    assert row_for(boss, "a@example.com")["two_factor_enabled"] is False
    assert (
        boss.post(f"/api/v1/admin/users/{a}/reset-two-factor").json()["error"]["code"]
        == "not_enabled"
    )
    other_admin = row_for(boss, "admin2@example.com")["id"]
    assert (
        boss.post(f"/api/v1/admin/users/{other_admin}/reset-two-factor").json()["error"]["code"]
        == "admin_two_factor"
    )


def test_the_audit_log_records_who_did_what(boss, client, make_user, sign_in) -> None:
    make_user("a@example.com")
    uid = row_for(boss, "a@example.com")["id"]
    boss.post(f"/api/v1/admin/users/{uid}/roles", json={"role": "educator", "grant": True})
    boss.post(
        "/api/v1/admin/billing/grant",
        json={"email": "a@example.com", "plan": "individual", "months": 3},
    )
    boss.post(f"/api/v1/admin/users/{uid}/close")
    log = boss.get("/api/v1/admin/audit").json()["actions"]
    assert [a["action"] for a in log[:3]] == ["account_closed", "payment_recorded", "role_granted"]
    assert log[0]["actor_email"] == "boss@example.com" and log[0]["target_label"] == "a@example.com"
    assert log[1]["detail"]["months"] == 3 and log[2]["detail"] == {"role": "educator"}
    only_a = boss.get("/api/v1/admin/audit", params={"user_id": uid}).json()["actions"]
    assert len(only_a) == 3


def test_failed_admin_actions_leave_no_log_line(boss) -> None:
    me_id = row_for(boss, "boss@example.com")["id"]
    boss.post(f"/api/v1/admin/users/{me_id}/close")
    assert boss.get("/api/v1/admin/audit").json()["actions"] == []


def test_people_tools_are_admin_only_and_hide_deleted_accounts(
    client, make_user, sign_in, boss
) -> None:
    make_user("a@example.com")
    sign_in("a@example.com")
    for path in ("/api/v1/admin/users", "/api/v1/admin/audit"):
        assert client.get(path).status_code == 403
    uid = row_for(boss, "a@example.com")["id"]
    assert (
        client.post(
            "/api/v1/account/delete",
            json={"password": "correct horse battery", "confirm": "DELETE"},
        ).status_code
        == 204
    )
    assert boss.get(f"/api/v1/admin/users/{uid}").status_code == 404
    assert boss.get("/api/v1/admin/users", params={"q": "a@example.com"}).json()["total"] == 0


# ------------------------------------------------------------------ partial refunds


def partial(
    admin: TestClient, ref: str, amount_kobo: int | None = None, cut_days: int | None = None
):
    body: dict = {"reason": "goodwill"}
    if amount_kobo is not None:
        body["amount_kobo"] = amount_kobo
    if cut_days is not None:
        body["cut_days"] = cut_days
    return admin.post(f"/api/v1/admin/billing/payments/{ref}/refund", json=body)


def paid_three_months(client, make_user, sign_in, paystack, session_factory):
    make_user("a@example.com")
    sign_in("a@example.com")
    result = pay(client, paystack, "individual", 3)
    ref = result["payment"]["reference"]
    return ref, result["payment"]["amount_kobo"], sub_of(session_factory, institution=False)[2]


def test_a_partial_refund_takes_back_the_same_share_of_the_days(
    client, make_user, sign_in, paystack, boss, session_factory
) -> None:
    ref, total, end = paid_three_months(client, make_user, sign_in, paystack, session_factory)
    r = partial(boss, ref, amount_kobo=total // 3)  # a third of the money: 30 of 90 days
    assert r.status_code == 200
    assert r.json()["status"] == "success" and r.json()["refunded_kobo"] == total // 3
    assert end - sub_of(session_factory, institution=False)[2] == timedelta(days=30)


def test_the_admin_can_choose_how_many_days_come_back(
    client, make_user, sign_in, paystack, boss, session_factory
) -> None:
    ref, total, end = paid_three_months(client, make_user, sign_in, paystack, session_factory)
    assert (
        partial(boss, ref, amount_kobo=total // 2, cut_days=0).status_code == 200
    )  # goodwill money
    assert sub_of(session_factory, institution=False)[2] == end
    assert partial(boss, ref, amount_kobo=total // 6, cut_days=10).status_code == 200
    assert end - sub_of(session_factory, institution=False)[2] == timedelta(days=10)


def test_refunding_the_rest_after_a_partial_refund_takes_back_only_the_rest(
    client, make_user, sign_in, paystack, boss, session_factory
) -> None:
    ref, total, end = paid_three_months(client, make_user, sign_in, paystack, session_factory)
    partial(boss, ref, amount_kobo=total // 3)  # 30 days back
    r = partial(boss, ref)  # everything that is left
    assert r.status_code == 200 and r.json()["status"] == "refunded"
    assert r.json()["refunded_kobo"] == total
    # All 90 days are gone, but access never goes back before now.
    assert abs(sub_of(session_factory, institution=False)[2] - utcnow()) < timedelta(minutes=1)
    assert partial(boss, ref).status_code == 409  # nothing left


def test_refund_amounts_and_days_are_checked(
    client, make_user, sign_in, paystack, boss, session_factory
) -> None:
    ref, total, end = paid_three_months(client, make_user, sign_in, paystack, session_factory)
    assert partial(boss, ref, amount_kobo=total + 1).status_code == 409
    assert partial(boss, ref, amount_kobo=total // 3, cut_days=91).status_code == 409
    assert partial(boss, ref, amount_kobo=0).status_code == 422
    assert sub_of(session_factory, institution=False)[2] == end  # nothing changed


def test_an_upgrade_cannot_be_refunded_in_part(owner, paystack, boss, session_factory) -> None:
    move_end(session_factory, timedelta(days=10, minutes=1))
    ref = owner.post("/api/v1/billing/checkout", json={"plan": "institution_20"}).json()[
        "reference"
    ]
    owner.post("/api/v1/billing/verify", json={"reference": ref})
    r = partial(boss, ref, amount_kobo=100)
    assert r.status_code == 409 and r.json()["error"]["code"] == "not_refundable_partly"
    assert sub_of(session_factory, institution=True)[:2] == ("institution_20", 20)
    assert partial(boss, ref).status_code == 200  # in full it still goes back


# ------------------------------------------------------------------ late and repeat refunds


def backdate(session_factory, ref: str, days: int) -> None:
    with session_factory() as s:
        p = s.scalar(select(Payment).where(Payment.reference == ref))
        p.paid_at = utcnow() - timedelta(days=days)
        s.commit()


def check(admin: TestClient, ref: str) -> dict:
    r = admin.get(f"/api/v1/admin/billing/payments/{ref}/refund-check")
    assert r.status_code == 200, r.text
    return r.json()


def with_override(admin: TestClient, ref: str, **extra):
    return admin.post(
        f"/api/v1/admin/billing/payments/{ref}/refund",
        json={"reason": "exception approved", "override": True, **extra},
    )


def test_a_refund_inside_the_window_needs_no_confirmation(
    client, make_user, sign_in, paystack, boss, session_factory
) -> None:
    make_user("a@example.com")
    sign_in("a@example.com")
    ref = pay(client, paystack, "individual", 1)["payment"]["reference"]
    backdate(session_factory, ref, 13)
    c = check(boss, ref)
    assert (c["outside_window"], c["needs_override"], c["window_days"]) == (False, False, 14)
    assert refund(boss, ref).status_code == 200


def test_a_late_refund_needs_an_override_that_is_logged(
    client, make_user, sign_in, paystack, boss, session_factory
) -> None:
    make_user("a@example.com")
    sign_in("a@example.com")
    ref = pay(client, paystack, "individual", 1)["payment"]["reference"]
    backdate(session_factory, ref, 20)
    assert check(boss, ref)["outside_window"] is True
    r = refund(boss, ref)
    assert r.status_code == 409 and r.json()["error"]["code"] == "outside_refund_window"
    assert client.get("/api/v1/billing/payments").json()["payments"][0]["status"] == "success"
    assert with_override(boss, ref).status_code == 200
    with session_factory() as s:
        last = s.scalars(select(AdminAction).order_by(AdminAction.created_at.desc())).first()
        assert last.action == "payment_refunded"
        assert last.detail["override"] is True and last.detail["days_since_paid"] == 20


def test_the_window_can_be_switched_off(
    app, client, make_user, sign_in, paystack, boss, session_factory
) -> None:
    base = get_settings()
    app.dependency_overrides[get_settings] = lambda: base.model_copy(
        update={"refund_window_days": 0}
    )
    make_user("a@example.com")
    sign_in("a@example.com")
    ref = pay(client, paystack, "individual", 1)["payment"]["reference"]
    backdate(session_factory, ref, 400)
    assert check(boss, ref)["needs_override"] is False
    assert refund(boss, ref).status_code == 200


def test_someone_refunded_before_needs_a_second_look(
    client, make_user, sign_in, paystack, boss, session_factory
) -> None:
    make_user("a@example.com")
    sign_in("a@example.com")
    refs = [pay(client, paystack, "individual", 1)["payment"]["reference"] for _ in range(3)]
    assert refund(boss, refs[0]).status_code == 200
    assert check(boss, refs[1])["repeat"] is False  # one earlier refund is normal
    assert refund(boss, refs[1]).status_code == 200
    c = check(boss, refs[2])
    assert (c["prior_refunds"], c["repeat"], c["needs_override"]) == (2, True, True)
    r = refund(boss, refs[2])
    assert r.status_code == 409 and r.json()["error"]["code"] == "repeat_refunds"
    assert with_override(boss, refs[2]).status_code == 200


def test_a_refund_paystack_already_made_is_always_recorded(
    client, make_user, sign_in, paystack, boss, session_factory, app
) -> None:
    make_user("a@example.com")
    sign_in("a@example.com")
    ref = pay(client, paystack, "individual", 1)["payment"]["reference"]
    amount = client.get("/api/v1/billing/payments").json()["payments"][0]["amount_kobo"]
    backdate(session_factory, ref, 60)  # far outside the window
    assert webhook(client, full_refund_event(ref, amount)).status_code == 200
    assert client.get("/api/v1/billing/payments").json()["payments"][0]["status"] == "refunded"


def test_the_refund_check_is_admin_only(client, make_user, sign_in, paystack) -> None:
    make_user("a@example.com")
    sign_in("a@example.com")
    ref = pay(client, paystack, "individual", 1)["payment"]["reference"]
    assert client.get(f"/api/v1/admin/billing/payments/{ref}/refund-check").status_code == 403
