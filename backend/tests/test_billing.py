import hashlib
import hmac
import json
from collections.abc import Callable, Iterator
from datetime import timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings, get_settings
from app.models.base import ensure_utc, utcnow
from app.models.billing import Institution, Payment, Subscription
from app.models.user import Role, User
from app.services.paystack import (
    CheckoutSession,
    PaystackError,
    VerifiedTransaction,
    get_paystack_client,
)
from tests.conftest import ORIGIN, PASSWORD

SECRET = "sk_test_secret"
KOBO = 100


class FakePaystack:
    """Stands in for Paystack. `outcome[ref]` sets what verify reports (default: paid in full)."""

    def __init__(self) -> None:
        self.initialized: dict[str, int] = {}
        self.outcome: dict[str, tuple[str, int | None]] = {}
        self.fail_initialize = False
        self.fail_verify = False

    def initialize(
        self, *, email: str, amount_kobo: int, reference: str, callback_url: str, metadata: dict
    ) -> CheckoutSession:
        if self.fail_initialize:
            raise PaystackError("down")
        self.initialized[reference] = amount_kobo
        assert callback_url.endswith("/subscription/verify")
        return CheckoutSession(f"https://checkout.paystack.test/{reference}", "code")

    def verify(self, reference: str) -> VerifiedTransaction:
        if self.fail_verify:
            raise PaystackError("down")
        status, amount = self.outcome.get(reference, ("success", None))
        return VerifiedTransaction(
            reference,
            status,
            amount if amount is not None else self.initialized[reference],
            "NGN",
            "Approved",
        )


@pytest.fixture
def paystack() -> FakePaystack:
    return FakePaystack()


@pytest.fixture(autouse=True)
def billing_overrides(app: FastAPI, paystack: FakePaystack) -> None:
    app.dependency_overrides[get_paystack_client] = lambda: paystack
    app.dependency_overrides[get_settings] = lambda: Settings(
        paystack_secret_key=SECRET, trial_days=7, cors_origins=["http://localhost:3000"]
    )


@pytest.fixture
def other_client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app, headers=ORIGIN) as c:
        yield c


def login(c: TestClient, identifier: str, password: str = PASSWORD) -> None:
    r = c.post("/api/v1/auth/login", json={"identifier": identifier, "password": password})
    assert r.status_code == 200, r.text


def pay(c: TestClient, paystack: FakePaystack, plan: str, months: int = 1, **extra: str) -> dict:
    r = c.post("/api/v1/billing/checkout", json={"plan": plan, "months": months, **extra})
    assert r.status_code == 200, r.text
    ref = r.json()["reference"]
    v = c.post("/api/v1/billing/verify", json={"reference": ref})
    assert v.status_code == 200, v.text
    return v.json()


def status(c: TestClient) -> dict:
    return c.get("/api/v1/billing/status").json()


def sub_end(session_factory: sessionmaker[Session], email: str):
    with session_factory() as s:
        user = s.scalar(select(User).where(User.email == email))
        sub = s.scalar(select(Subscription).where(Subscription.user_id == user.id))
        return ensure_utc(sub.current_period_end), sub.plan_code


# ------------------------------------------------------------------ plans & trial


def test_plans_are_public_and_priced_in_kobo(client: TestClient) -> None:
    body = client.get("/api/v1/billing/plans").json()
    prices = {p["code"]: (p["monthly_kobo"], p["seats"]) for p in body["plans"]}
    assert prices == {
        "individual": (15_000 * KOBO, None),
        "institution_10": (80_000 * KOBO, 10),
        "institution_20": (150_000 * KOBO, 20),
    }
    assert body["currency"] == "NGN"


def test_new_account_gets_a_trial_then_loses_access_when_it_ends(
    client: TestClient, make_user: Callable[..., User], sign_in, session_factory
) -> None:
    make_user("a@example.com")
    sign_in("a@example.com")
    assert client.get("/api/v1/lessons").status_code == 200
    st = status(client)
    assert st["entitlement"]["source"] == "trial" and st["entitlement"]["days_left"] in (6, 7)

    with session_factory() as s:
        sub = s.scalar(select(Subscription))
        sub.current_period_end = utcnow() - timedelta(minutes=1)
        s.commit()
    r = client.get("/api/v1/lessons")
    assert r.status_code == 402
    assert r.json()["error"]["code"] == "subscription_required"
    assert r.json()["error"]["details"]["reason"] == "expired"
    assert client.get("/api/v1/auth/me").status_code == 200  # account pages still work


def test_staff_never_need_a_subscription(
    client: TestClient, make_user: Callable[..., User], sign_in
) -> None:
    make_user("edu@example.com", roles=(Role.EDUCATOR,))
    sign_in("edu@example.com")
    assert status(client)["entitlement"]["source"] == "staff"


# ------------------------------------------------------------------ individual payments


def test_individual_payment_grants_30_days_per_month_and_stacks(
    client: TestClient, make_user, sign_in, paystack: FakePaystack, session_factory
) -> None:
    make_user("a@example.com")
    sign_in("a@example.com")
    r = client.post("/api/v1/billing/checkout", json={"plan": "individual", "months": 2})
    assert r.json()["amount_kobo"] == 2 * 15_000 * KOBO
    assert paystack.initialized[r.json()["reference"]] == 2 * 15_000 * KOBO

    first = pay(client, paystack, "individual", 1)
    assert first["payment"]["status"] == "success"
    assert first["entitlement"]["source"] == "individual"
    end1, plan = sub_end(session_factory, "a@example.com")
    assert plan == "individual"
    assert timedelta(days=29, hours=23) < end1 - utcnow() <= timedelta(days=30)

    pay(client, paystack, "individual", 1)  # renewing early adds to the end date
    end2, _ = sub_end(session_factory, "a@example.com")
    assert end2 - end1 == timedelta(days=30)


def test_paying_during_trial_does_not_keep_trial_days(
    client: TestClient, make_user, sign_in, paystack, session_factory
) -> None:
    make_user("a@example.com")
    sign_in("a@example.com")
    status(client)  # starts the trial
    pay(client, paystack, "individual", 1)
    end, plan = sub_end(session_factory, "a@example.com")
    assert plan == "individual" and end - utcnow() <= timedelta(days=30)


def test_verify_twice_is_idempotent(
    client: TestClient, make_user, sign_in, paystack, session_factory
) -> None:
    make_user("a@example.com")
    sign_in("a@example.com")
    ref = client.post("/api/v1/billing/checkout", json={"plan": "individual"}).json()["reference"]
    client.post("/api/v1/billing/verify", json={"reference": ref})
    end1, _ = sub_end(session_factory, "a@example.com")
    client.post("/api/v1/billing/verify", json={"reference": ref})
    assert sub_end(session_factory, "a@example.com")[0] == end1


def test_underpayment_is_rejected(
    client: TestClient, make_user, sign_in, paystack, session_factory
) -> None:
    make_user("a@example.com")
    sign_in("a@example.com")
    ref = client.post("/api/v1/billing/checkout", json={"plan": "individual"}).json()["reference"]
    paystack.outcome[ref] = ("success", 100)  # paid 1 naira
    v = client.post("/api/v1/billing/verify", json={"reference": ref}).json()
    assert v["payment"]["status"] == "failed"
    assert v["entitlement"]["source"] == "trial"


def test_abandoned_payment_stays_pending_and_can_be_retried(
    client: TestClient, make_user, sign_in, paystack
) -> None:
    make_user("a@example.com")
    sign_in("a@example.com")
    ref = client.post("/api/v1/billing/checkout", json={"plan": "individual"}).json()["reference"]
    paystack.outcome[ref] = ("abandoned", None)
    assert (
        client.post("/api/v1/billing/verify", json={"reference": ref}).json()["payment"]["status"]
        == "pending"
    )
    paystack.outcome[ref] = ("success", None)
    assert (
        client.post("/api/v1/billing/verify", json={"reference": ref}).json()["payment"]["status"]
        == "success"
    )


def test_cannot_verify_someone_elses_payment(
    client: TestClient, other_client: TestClient, make_user, sign_in, paystack
) -> None:
    make_user("a@example.com")
    make_user("b@example.com")
    sign_in("a@example.com")
    ref = client.post("/api/v1/billing/checkout", json={"plan": "individual"}).json()["reference"]
    login(other_client, "b@example.com")
    r = other_client.post("/api/v1/billing/verify", json={"reference": ref})
    assert r.status_code == 404


@pytest.mark.parametrize(
    "body,code",
    [
        ({"plan": "gold"}, "invalid_plan"),
        ({"plan": "individual", "months": 13}, "validation_error"),
        ({"plan": "institution_10"}, "institution_name_required"),
    ],
)
def test_checkout_validation(client: TestClient, make_user, sign_in, body, code) -> None:
    make_user("a@example.com")
    sign_in("a@example.com")
    r = client.post("/api/v1/billing/checkout", json=body)
    assert r.status_code == 422 and r.json()["error"]["code"] == code


def test_paystack_down_marks_payment_failed(
    client: TestClient, make_user, sign_in, paystack, session_factory
) -> None:
    make_user("a@example.com")
    sign_in("a@example.com")
    paystack.fail_initialize = True
    r = client.post("/api/v1/billing/checkout", json={"plan": "individual"})
    assert r.status_code == 503 and r.json()["error"]["code"] == "payment_unavailable"
    with session_factory() as s:
        assert s.scalar(select(Payment)).status == "failed"


def test_verify_when_paystack_unreachable_keeps_payment_pending(
    client: TestClient, make_user, sign_in, paystack
) -> None:
    make_user("a@example.com")
    sign_in("a@example.com")
    ref = client.post("/api/v1/billing/checkout", json={"plan": "individual"}).json()["reference"]
    paystack.fail_verify = True
    assert client.post("/api/v1/billing/verify", json={"reference": ref}).status_code == 503
    paystack.fail_verify = False
    assert (
        client.post("/api/v1/billing/verify", json={"reference": ref}).json()["payment"]["status"]
        == "success"
    )


def test_checkout_requires_sign_in(client: TestClient) -> None:
    assert client.post("/api/v1/billing/checkout", json={"plan": "individual"}).status_code == 401


# ------------------------------------------------------------------ webhook


def signed(body: dict, key: str = SECRET) -> tuple[bytes, dict[str, str]]:
    raw = json.dumps(body).encode()
    return raw, {"x-paystack-signature": hmac.new(key.encode(), raw, hashlib.sha512).hexdigest()}


def test_webhook_grants_access_once(
    client: TestClient, make_user, sign_in, paystack, session_factory
) -> None:
    make_user("a@example.com")
    sign_in("a@example.com")
    ref = client.post("/api/v1/billing/checkout", json={"plan": "individual"}).json()["reference"]
    raw, headers = signed({"event": "charge.success", "data": {"reference": ref}})
    anon = {"content-type": "application/json", **headers}
    assert (
        client.post("/api/v1/billing/webhooks/paystack", content=raw, headers=anon).status_code
        == 200
    )
    end1, plan = sub_end(session_factory, "a@example.com")
    assert plan == "individual"
    client.post("/api/v1/billing/webhooks/paystack", content=raw, headers=anon)  # Paystack retries
    assert sub_end(session_factory, "a@example.com")[0] == end1


def test_webhook_rejects_bad_or_missing_signature(
    client: TestClient, make_user, sign_in, paystack
) -> None:
    make_user("a@example.com")
    sign_in("a@example.com")
    ref = client.post("/api/v1/billing/checkout", json={"plan": "individual"}).json()["reference"]
    raw, _ = signed({"event": "charge.success", "data": {"reference": ref}})
    _, wrong = signed({"event": "charge.success", "data": {"reference": ref}}, key="sk_other")
    assert (
        client.post("/api/v1/billing/webhooks/paystack", content=raw, headers=wrong).status_code
        == 401
    )
    assert client.post("/api/v1/billing/webhooks/paystack", content=raw).status_code == 401
    assert status(client)["entitlement"]["source"] == "trial"


def test_webhook_ignores_unknown_reference_and_other_events(client: TestClient) -> None:
    for body in (
        {"event": "charge.success", "data": {"reference": "not_ours"}},
        {"event": "transfer.success", "data": {"reference": "x"}},
    ):
        raw, headers = signed(body)
        assert (
            client.post(
                "/api/v1/billing/webhooks/paystack", content=raw, headers=headers
            ).status_code
            == 200
        )


def test_webhook_asks_paystack_to_retry_when_it_cannot_verify(
    client: TestClient, make_user, sign_in, paystack
) -> None:
    make_user("a@example.com")
    sign_in("a@example.com")
    ref = client.post("/api/v1/billing/checkout", json={"plan": "individual"}).json()["reference"]
    paystack.fail_verify = True
    raw, headers = signed({"event": "charge.success", "data": {"reference": ref}})
    assert (
        client.post("/api/v1/billing/webhooks/paystack", content=raw, headers=headers).status_code
        == 503
    )


# ------------------------------------------------------------------ institutions


@pytest.fixture
def owner(client: TestClient, make_user, sign_in, paystack) -> TestClient:
    make_user("owner@school.ng")
    sign_in("owner@school.ng")
    pay(client, paystack, "institution_10", 1, institution_name="  Grace   Music School ")
    return client


def make_seats(c: TestClient, *names: str):
    r = c.post("/api/v1/institution/seats", json={"names": list(names)})
    assert r.status_code == 201, r.text
    return r.json()["credentials"]


def test_institution_purchase_creates_institution_with_seat_cap(owner: TestClient) -> None:
    o = owner.get("/api/v1/institution").json()
    assert o["name"] == "Grace Music School"
    assert (o["plan_code"], o["seats_allowed"], o["seats_used"], o["subscription_live"]) == (
        "institution_10",
        10,
        0,
        True,
    )
    assert len(o["code"]) == 4
    assert status(owner)["institution_role"] == "owner"
    assert owner.get("/api/v1/auth/me").json()["institution_role"] == "owner"


def test_seat_logins_are_unique_per_person_and_capped(owner: TestClient, other_client) -> None:
    creds = make_seats(owner, *[f"Student {i}" for i in range(10)])
    ids = [c["login_id"] for c in creds]
    assert len(set(ids)) == 10 and all(
        i.startswith(owner.get("/api/v1/institution").json()["code"] + "-") for i in ids
    )
    assert len({c["password"] for c in creds}) == 10 and all(
        len(c["password"]) >= 10 for c in creds
    )

    r = owner.post("/api/v1/institution/seats", json={"names": ["One too many"]})
    assert r.status_code == 409 and r.json()["error"]["code"] == "seat_limit_reached"
    assert r.json()["error"]["details"] == {"free": 0, "allowed": 10}

    # A seat signs in with its login ID (any case) and has learning access.
    login(other_client, ids[0].lower(), creds[0]["password"])
    assert other_client.get("/api/v1/lessons").status_code == 200
    me = other_client.get("/api/v1/auth/me").json()
    assert me["email"] is None and me["login_id"] == ids[0] and me["institution_role"] == "seat"
    assert status(other_client)["entitlement"]["source"] == "institution"


def test_passwords_are_not_readable_again(owner: TestClient) -> None:
    make_seats(owner, "Ada")
    text = owner.get("/api/v1/institution").text
    assert "password" not in text


def test_a_seat_login_works_on_one_device_at_a_time(
    owner: TestClient, app: FastAPI, other_client: TestClient
) -> None:
    cred = make_seats(owner, "Ada")[0]
    login(other_client, cred["login_id"], cred["password"])
    assert other_client.get("/api/v1/lessons").status_code == 200
    with TestClient(app, headers=ORIGIN) as second_device:
        login(second_device, cred["login_id"], cred["password"])
        assert second_device.get("/api/v1/lessons").status_code == 200
        assert other_client.get("/api/v1/lessons").status_code == 401  # signed out by the new login


def test_normal_accounts_can_still_use_several_devices(
    client: TestClient, make_user, sign_in, app: FastAPI
) -> None:
    make_user("a@example.com")
    sign_in("a@example.com")
    with TestClient(app, headers=ORIGIN) as second:
        login(second, "a@example.com")
        assert client.get("/api/v1/auth/me").status_code == 200


def test_closing_a_login_frees_the_seat_and_signs_that_person_out(
    owner: TestClient, other_client: TestClient
) -> None:
    creds = make_seats(owner, *[f"S{i}" for i in range(10)])
    login(other_client, creds[0]["login_id"], creds[0]["password"])
    assert owner.post(f"/api/v1/institution/seats/{creds[0]['id']}/deactivate").status_code == 204
    assert other_client.get("/api/v1/lessons").status_code == 401
    bad = other_client.post(
        "/api/v1/auth/login",
        json={"identifier": creds[0]["login_id"], "password": creds[0]["password"]},
    )
    assert bad.status_code == 401

    new = make_seats(owner, "Replacement")[0]
    assert new["login_id"] not in {c["login_id"] for c in creds}  # numbers are never reused
    # The old login cannot come back while the plan is full.
    r = owner.post(f"/api/v1/institution/seats/{creds[0]['id']}/activate")
    assert r.status_code == 409 and r.json()["error"]["code"] == "seat_limit_reached"
    assert owner.get("/api/v1/institution").json()["seats_used"] == 10


def test_reset_password_signs_the_seat_out_and_old_password_stops_working(
    owner: TestClient, other_client: TestClient
) -> None:
    cred = make_seats(owner, "Ada")[0]
    login(other_client, cred["login_id"], cred["password"])
    new = owner.post(f"/api/v1/institution/seats/{cred['id']}/reset-password").json()[
        "credentials"
    ][0]
    assert new["password"] != cred["password"] and new["login_id"] == cred["login_id"]
    assert other_client.get("/api/v1/lessons").status_code == 401
    assert (
        other_client.post(
            "/api/v1/auth/login",
            json={"identifier": cred["login_id"], "password": cred["password"]},
        ).status_code
        == 401
    )
    login(other_client, cred["login_id"], new["password"])


def test_seat_cannot_buy_or_close_its_own_account(
    owner: TestClient, other_client: TestClient
) -> None:
    cred = make_seats(owner, "Ada")[0]
    login(other_client, cred["login_id"], cred["password"])
    r = other_client.post("/api/v1/billing/checkout", json={"plan": "individual"})
    assert r.status_code == 403 and r.json()["error"]["code"] == "seat_cannot_purchase"
    assert status(other_client)["can_purchase"] is False
    r = other_client.post("/api/v1/auth/me/deactivate", json={"password": cred["password"]})
    assert r.status_code == 403 and r.json()["error"]["code"] == "seat_managed"
    # ...and cannot manage seats.
    assert other_client.post("/api/v1/institution/seats", json={"names": ["x"]}).status_code == 404


def test_only_the_owner_can_manage_their_seats(
    owner: TestClient, other_client: TestClient, make_user
) -> None:
    cred = make_seats(owner, "Ada")[0]
    make_user("rival@school.ng")
    login(other_client, "rival@school.ng")
    assert other_client.get("/api/v1/institution").status_code == 404
    r = other_client.post(f"/api/v1/institution/seats/{cred['id']}/reset-password")
    assert r.status_code == 404


def test_other_institutions_cannot_touch_seats(
    owner: TestClient, other_client: TestClient, make_user, paystack
) -> None:
    cred = make_seats(owner, "Ada")[0]
    make_user("rival@school.ng")
    login(other_client, "rival@school.ng")
    pay(other_client, paystack, "institution_10", 1, institution_name="Rival")
    r = other_client.post(f"/api/v1/institution/seats/{cred['id']}/deactivate")
    assert r.status_code == 404 and r.json()["error"]["code"] == "seat_not_found"


def test_when_the_institution_plan_ends_seats_lose_access_and_owner_cannot_add(
    owner: TestClient, other_client: TestClient, session_factory
) -> None:
    cred = make_seats(owner, "Ada")[0]
    login(other_client, cred["login_id"], cred["password"])
    with session_factory() as s:
        sub = s.scalar(select(Subscription).where(Subscription.institution_id.is_not(None)))
        sub.current_period_end = utcnow() - timedelta(days=1)
        s.commit()
    r = other_client.get("/api/v1/lessons")
    assert r.status_code == 402 and r.json()["error"]["details"]["reason"] == "institution_expired"
    r = owner.post("/api/v1/institution/seats", json={"names": ["Late"]})
    assert r.status_code == 403 and r.json()["error"]["code"] == "institution_expired"


def test_renewing_restores_seat_access(
    owner: TestClient, other_client: TestClient, session_factory, paystack
) -> None:
    cred = make_seats(owner, "Ada")[0]
    login(other_client, cred["login_id"], cred["password"])
    with session_factory() as s:
        sub = s.scalar(select(Subscription).where(Subscription.institution_id.is_not(None)))
        sub.current_period_end = utcnow() - timedelta(days=1)
        s.commit()
    pay(owner, paystack, "institution_10", 1)
    assert other_client.get("/api/v1/lessons").status_code == 200
    with session_factory() as s:
        assert len(s.scalars(select(Institution)).all()) == 1  # renewed, not duplicated


def test_a_bigger_plan_mid_term_is_an_upgrade_and_a_smaller_one_waits(
    owner: TestClient, session_factory, paystack
) -> None:
    # Bigger while the plan is running: allowed, as a prorated upgrade (see test_billing_extras).
    r = owner.post("/api/v1/billing/checkout", json={"plan": "institution_20"})
    assert r.status_code == 200 and r.json()["amount_kobo"] < 150_000 * KOBO
    # Smaller while it is running: not until the period ends.
    with session_factory() as s:
        sub = s.scalar(select(Subscription).where(Subscription.institution_id.is_not(None)))
        sub.plan_code, sub.seats = "institution_20", 20
        s.commit()
    r = owner.post("/api/v1/billing/checkout", json={"plan": "institution_10"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "plan_change_not_allowed"
    # After it ends, the smaller plan can be chosen.
    with session_factory() as s:
        sub = s.scalar(select(Subscription).where(Subscription.institution_id.is_not(None)))
        sub.current_period_end = utcnow() - timedelta(days=1)
        s.commit()
    pay(owner, paystack, "institution_10", 1)
    assert owner.get("/api/v1/institution").json()["seats_allowed"] == 10


def test_cannot_move_to_a_smaller_plan_while_too_many_logins_are_active(
    owner: TestClient, session_factory, paystack
) -> None:
    with session_factory() as s:
        sub = s.scalar(select(Subscription).where(Subscription.institution_id.is_not(None)))
        sub.plan_code, sub.seats = "institution_20", 20
        s.commit()
    make_seats(owner, *[f"S{i}" for i in range(11)])
    with session_factory() as s:
        sub = s.scalar(select(Subscription).where(Subscription.institution_id.is_not(None)))
        sub.current_period_end = utcnow() - timedelta(days=1)
        s.commit()
    r = owner.post("/api/v1/billing/checkout", json={"plan": "institution_10"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "too_many_active_seats"


def test_seat_names_are_validated(owner: TestClient) -> None:
    assert owner.post("/api/v1/institution/seats", json={"names": []}).status_code == 422
    assert owner.post("/api/v1/institution/seats", json={"names": ["  "]}).status_code == 422
    assert owner.post("/api/v1/institution/seats", json={"names": ["x"] * 21}).status_code == 422


# ------------------------------------------------------------------ admin


def test_admin_can_record_a_bank_transfer(
    client: TestClient, make_user, sign_in, other_client: TestClient
) -> None:
    make_user("admin@example.com", roles=(Role.ADMIN,))
    make_user("buyer@example.com")
    sign_in("admin@example.com")
    r = client.post(
        "/api/v1/admin/billing/grant",
        json={"email": "buyer@example.com", "plan": "individual", "months": 3},
    )
    assert r.status_code == 200 and r.json()["status"] == "success"
    assert r.json()["reference"].startswith("manual_")
    login(other_client, "buyer@example.com")
    assert status(other_client)["entitlement"]["source"] == "individual"


def test_grant_is_admin_only(client: TestClient, make_user, sign_in) -> None:
    make_user("a@example.com")
    sign_in("a@example.com")
    r = client.post(
        "/api/v1/admin/billing/grant", json={"email": "a@example.com", "plan": "individual"}
    )
    assert r.status_code == 403
