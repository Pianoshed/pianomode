import base64
import re
from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core import totp
from app.core.config import Settings, get_settings
from app.models.base import utcnow
from app.models.billing import Payment, Subscription
from app.models.exercise_attempt import ExerciseAttempt
from app.models.library import LibraryItem
from app.models.user import Role, User
from app.services import billing_service, two_factor_service
from app.services.file_store import FileStore, get_file_store
from tests.conftest import ORIGIN, PASSWORD

MIDI = base64.b64encode(b"MThd\x00\x00\x00\x06\x00\x01\x00\x01\x01\xe0").decode()


class Clock:
    """A clock tests can move, so two sign-ins can happen in different 30-second steps."""

    def __init__(self) -> None:
        self.now = 1_800_000_000.0

    def time(self) -> float:
        return self.now


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> Clock:
    c = Clock()
    monkeypatch.setattr(two_factor_service, "time", c)
    return c


@pytest.fixture
def policy() -> dict[str, object]:
    return {}


@pytest.fixture(autouse=True)
def overrides(app: FastAPI, tmp_path: Path, policy: dict[str, object]) -> None:
    app.dependency_overrides[get_file_store] = lambda: FileStore(tmp_path)
    app.dependency_overrides[get_settings] = lambda: Settings(
        cors_origins=["http://localhost:3000"], public_web_url="https://piano.example", **policy
    )


@pytest.fixture
def second(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app, headers=ORIGIN) as c:
        yield c


@pytest.fixture
def me(client: TestClient, make_user, sign_in) -> TestClient:
    make_user("a@example.com")
    sign_in("a@example.com")
    return client


def code(secret: str, clock: Clock, ahead: int = 0) -> str:
    return totp._code(secret, totp.step_at(clock.now) + ahead)


def turn_on(c: TestClient, clock: Clock) -> tuple[str, list[str]]:
    secret = c.post("/api/v1/auth/2fa/setup").json()["secret"]
    r = c.post("/api/v1/auth/2fa/enable", json={"code": code(secret, clock)})
    assert r.status_code == 200, r.text
    return secret, r.json()["recovery_codes"]


def login(c: TestClient, who: str, otp: str | None = None, password: str = PASSWORD):
    body = {"identifier": who, "password": password, **({"otp": otp} if otp else {})}
    return c.post("/api/v1/auth/login", json=body)


# =============================================================== two-factor


def test_two_factor_setup_enable_and_sign_in(me, second, clock) -> None:
    secret, recovery = turn_on(me, clock)
    assert len(recovery) == 10 and len(set(recovery)) == 10
    assert me.get("/api/v1/auth/me").json()["two_factor_enabled"] is True

    clock.now += 31  # a fresh 30-second step: the code used to enable cannot be reused
    r = login(second, "a@example.com")
    assert r.status_code == 401 and r.json()["error"]["code"] == "two_factor_required"
    r = login(second, "a@example.com", "000000")
    assert r.status_code == 401 and r.json()["error"]["code"] == "invalid_code"
    good = code(secret, clock)
    assert login(second, "a@example.com", good).status_code == 200


def test_a_code_works_only_once_and_the_password_still_matters(me, second, clock) -> None:
    secret, _ = turn_on(me, clock)
    clock.now += 31
    good = code(secret, clock)
    assert login(second, "a@example.com", good).status_code == 200
    with TestClient(second.app, headers=ORIGIN) as third:
        r = login(third, "a@example.com", good)  # the same code again, seconds later
        assert r.status_code == 401 and r.json()["error"]["code"] == "invalid_code"
        clock.now += 31
        r = login(third, "a@example.com", code(secret, clock), password="wrong wrong wrong")
        assert r.status_code == 401 and r.json()["error"]["code"] == "invalid_credentials"


def test_recovery_codes_work_once_each(me, second, clock) -> None:
    _, recovery = turn_on(me, clock)
    assert login(second, "a@example.com", recovery[0]).status_code == 200
    with TestClient(second.app, headers=ORIGIN) as third:
        assert login(third, "a@example.com", recovery[0]).status_code == 401  # used up
        assert (
            login(third, "a@example.com", recovery[1].upper()).status_code == 200
        )  # case-insensitive


def test_setup_needs_a_correct_code_and_cannot_be_repeated(me, clock) -> None:
    secret = me.post("/api/v1/auth/2fa/setup").json()["secret"]
    r = me.post("/api/v1/auth/2fa/enable", json={"code": "123456"})
    assert r.status_code == 401
    assert me.get("/api/v1/auth/me").json()["two_factor_enabled"] is False  # nothing changed
    assert me.post("/api/v1/auth/2fa/enable", json={"code": code(secret, clock)}).status_code == 200
    assert me.post("/api/v1/auth/2fa/setup").status_code == 409


def test_turning_it_off_needs_password_and_a_code(me, clock) -> None:
    secret, _ = turn_on(me, clock)
    clock.now += 31
    bad = me.post(
        "/api/v1/auth/2fa/disable", json={"password": "nope nope nope", "code": code(secret, clock)}
    )
    assert bad.status_code == 401
    clock.now += 31
    ok = me.post(
        "/api/v1/auth/2fa/disable", json={"password": PASSWORD, "code": code(secret, clock)}
    )
    assert ok.status_code == 204
    assert me.get("/api/v1/auth/me").json()["two_factor_enabled"] is False


def test_the_key_is_stored_encrypted(me, clock, session_factory) -> None:
    secret, _ = turn_on(me, clock)
    with session_factory() as s:
        stored = s.scalar(select(User).where(User.email == "a@example.com")).totp_secret
    assert stored and secret not in stored


@pytest.mark.parametrize("policy", [{"admin_require_two_factor": True}])
def test_admins_cannot_use_admin_tools_until_two_factor_is_on(
    client: TestClient, make_user, sign_in, clock
) -> None:
    make_user("boss@example.com", roles=(Role.ADMIN,))
    sign_in("boss@example.com")
    me_ = client.get("/api/v1/auth/me").json()
    assert me_["two_factor_setup_needed"] is True
    r = client.get("/api/v1/admin/billing/payments")
    assert r.status_code == 403 and r.json()["error"]["code"] == "two_factor_setup_required"
    assert client.get("/api/v1/lessons").status_code == 200  # still usable as a learner
    turn_on(client, clock)
    assert client.get("/api/v1/admin/billing/payments").status_code == 200
    assert client.get("/api/v1/auth/me").json()["two_factor_setup_needed"] is False


@pytest.mark.parametrize("policy", [{"admin_require_two_factor": False}])
def test_the_policy_can_be_off(client: TestClient, make_user, sign_in) -> None:
    make_user("boss@example.com", roles=(Role.ADMIN,))
    sign_in("boss@example.com")
    assert client.get("/api/v1/admin/billing/payments").status_code == 200


def test_the_policy_is_on_by_default_in_production_only() -> None:
    assert Settings(env="production").admins_need_two_factor is True
    assert Settings().admins_need_two_factor is False
    assert (
        Settings(env="production", admin_require_two_factor=False).admins_need_two_factor is False
    )


def test_reset_script_turns_it_off_for_a_lost_phone(me, clock, session_factory, second) -> None:
    from scripts.make_admin import reset_two_factor

    turn_on(me, clock)
    with session_factory() as s:
        assert "off for a@example.com" in reset_two_factor(s, "a@example.com")
    assert me.get("/api/v1/auth/me").status_code == 401  # signed out
    assert login(second, "a@example.com").status_code == 200  # no code needed any more


# =============================================================== export


def test_export_has_everything_and_no_secrets(me, session_factory) -> None:
    me.post("/api/v1/library", json={"kind": "audio", "title": "Take", "data": {"v": 1}})
    with session_factory() as s:
        user = s.scalar(select(User).where(User.email == "a@example.com"))
        s.add(
            ExerciseAttempt(
                user_id=user.id, exercise_id="x", kind="k", difficulty="d", status="s", correct=True
            )
        )
        s.commit()
        billing_service.admin_grant(
            s,
            user=user,
            plan_code="individual",
            months=1,
            institution_name=None,
            settings=Settings(),
        )
    r = me.get("/api/v1/account/export")
    assert r.status_code == 200 and "attachment" in r.headers["content-disposition"]
    d = r.json()
    assert d["profile"]["email"] == "a@example.com" and d["profile"]["roles"] == ["learner"]
    assert [i["title"] for i in d["library"]] == ["Take"]
    assert len(d["theory_answers"]) == 1 and d["payments"][0]["amount_naira"] == 15000
    assert d["subscription"]["plan"] == "individual" and len(d["sign_ins"]) >= 1
    for secret_word in ("password_hash", "totp_secret", "token_hash", "recovery_codes"):
        assert secret_word not in r.text


def test_export_needs_sign_in(client: TestClient) -> None:
    assert client.get("/api/v1/account/export").status_code == 401


def test_nobody_else_appears_in_your_export(me, second, make_user, session_factory) -> None:
    make_user("b@example.com")
    login(second, "b@example.com")
    second.post("/api/v1/library", json={"kind": "audio", "title": "Not yours"})
    assert "Not yours" not in me.get("/api/v1/account/export").text


# =============================================================== change email


def link_token(outbox, to: str) -> str:
    body = next(m.body for m in reversed(outbox.messages) if m.to == to)
    return re.search(r"token=([\w-]+)", body).group(1)


def test_change_email_end_to_end(me, second, outbox) -> None:
    r = me.post(
        "/api/v1/account/change-email", json={"new_email": "New@Example.com", "password": PASSWORD}
    )
    assert r.status_code == 202
    assert me.get("/api/v1/auth/me").json()["email"] == "a@example.com"  # not yet
    token = link_token(outbox, "new@example.com")
    assert not any(m.to == "a@example.com" for m in outbox.messages if "Confirm" in m.subject)

    r = second.post("/api/v1/account/confirm-email-change", json={"token": token})
    assert r.status_code == 200
    assert me.get("/api/v1/auth/me").status_code == 401  # every device signed out
    assert login(second, "a@example.com").status_code == 401
    assert login(second, "new@example.com").status_code == 200
    assert any(m.to == "a@example.com" and "changed" in m.subject for m in outbox.messages)
    assert (
        second.post("/api/v1/account/confirm-email-change", json={"token": token}).status_code
        == 400
    )  # once


def test_change_email_checks_password_and_does_not_reveal_who_has_an_account(
    me, make_user, outbox
) -> None:
    assert (
        me.post(
            "/api/v1/account/change-email",
            json={"new_email": "x@example.com", "password": "wrong wrong wrong"},
        ).status_code
        == 401
    )
    assert (
        me.post(
            "/api/v1/account/change-email",
            json={"new_email": "a@example.com", "password": PASSWORD},
        ).status_code
        == 409
    )
    make_user("taken@example.com")
    r = me.post(
        "/api/v1/account/change-email",
        json={"new_email": "taken@example.com", "password": PASSWORD},
    )
    fresh = me.post(
        "/api/v1/account/change-email", json={"new_email": "free@example.com", "password": PASSWORD}
    )
    assert r.status_code == 202 and r.json() == fresh.json()  # same answer either way
    assert not any(
        "Confirm your new email" in m.subject and m.to == "taken@example.com"
        for m in outbox.messages
    )


def test_an_old_reset_link_dies_when_the_email_changes(me, second, outbox) -> None:
    second.post("/api/v1/auth/password-reset/request", json={"email": "a@example.com"})
    reset = link_token(outbox, "a@example.com")
    me.post(
        "/api/v1/account/change-email", json={"new_email": "new@example.com", "password": PASSWORD}
    )
    second.post(
        "/api/v1/account/confirm-email-change",
        json={"token": link_token(outbox, "new@example.com")},
    )
    r = second.post(
        "/api/v1/auth/password-reset/confirm",
        json={"token": reset, "new_password": "Brand new passphrase 99"},
    )
    assert r.status_code in (400, 401, 422)


# =============================================================== delete


def delete(c: TestClient, **over):
    return c.post(
        "/api/v1/account/delete", json={"password": PASSWORD, "confirm": "DELETE", **over}
    )


def test_delete_erases_personal_data_but_keeps_payment_records(
    me, second, session_factory, tmp_path: Path
) -> None:
    item = me.post(
        "/api/v1/library",
        json={"kind": "midi", "title": "Etude", "file_name": "e.mid", "file_base64": MIDI},
    ).json()
    assert any(p.is_file() for p in tmp_path.rglob("*"))
    with session_factory() as s:
        user = s.scalar(select(User).where(User.email == "a@example.com"))
        uid = user.id
        s.add(
            ExerciseAttempt(
                user_id=uid, exercise_id="x", kind="k", difficulty="d", status="s", correct=True
            )
        )
        s.commit()
        billing_service.admin_grant(
            s,
            user=user,
            plan_code="individual",
            months=1,
            institution_name=None,
            settings=Settings(),
        )

    assert delete(me).status_code == 204
    assert me.get("/api/v1/auth/me").status_code == 401
    assert login(second, "a@example.com").status_code == 401
    assert not any(p.is_file() for p in tmp_path.rglob("*"))  # the saved file is gone

    with session_factory() as s:
        u = s.get(User, uid)
        assert (u.email, u.login_id, u.display_name, u.is_active) == (
            None,
            None,
            "Deleted account",
            False,
        )
        assert u.deleted_at is not None and u.role_names == {Role.LEARNER}
        assert s.scalars(select(LibraryItem).where(LibraryItem.user_id == uid)).all() == []
        assert s.scalars(select(ExerciseAttempt).where(ExerciseAttempt.user_id == uid)).all() == []
        assert s.scalar(select(Subscription).where(Subscription.user_id == uid)) is None
        kept = s.scalars(select(Payment).where(Payment.user_id == uid)).all()
        assert len(kept) == 1 and kept[0].amount_kobo == 1_500_000  # the law requires this record
    assert item["id"]


def test_the_email_can_be_used_again_after_deleting(me, second, outbox) -> None:
    assert delete(me).status_code == 204
    r = second.post(
        "/api/v1/auth/register",
        json={"email": "a@example.com", "password": PASSWORD, "display_name": "Again"},
    )
    assert r.status_code in (200, 201, 202)
    assert not any("already exists" in m.body for m in outbox.messages)  # treated as brand new


def test_delete_needs_the_password_and_the_word(me) -> None:
    assert delete(me, password="wrong wrong wrong").status_code == 401
    assert delete(me, confirm="delete").status_code == 422
    assert delete(me, confirm="").status_code == 422
    assert me.get("/api/v1/auth/me").status_code == 200  # still there


def test_delete_with_two_factor_needs_a_code(me, clock) -> None:
    secret, _ = turn_on(me, clock)
    assert delete(me).status_code == 401
    clock.now += 31
    assert delete(me, otp=code(secret, clock)).status_code == 204


def test_the_last_administrator_cannot_delete_themselves(client, make_user, sign_in) -> None:
    make_user("boss@example.com", roles=(Role.ADMIN,))
    sign_in("boss@example.com")
    r = delete(client)
    assert r.status_code == 409 and r.json()["error"]["code"] == "last_admin"
    make_user("other@example.com", roles=(Role.ADMIN,))
    assert delete(client).status_code == 204


def test_an_institution_owner_with_a_running_plan_cannot_delete_but_can_when_it_has_ended(
    me, session_factory
) -> None:
    with session_factory() as s:
        user = s.scalar(select(User).where(User.email == "a@example.com"))
        billing_service.admin_grant(
            s,
            user=user,
            plan_code="institution_10",
            months=1,
            institution_name="School",
            settings=Settings(),
        )
    r = delete(me)
    assert r.status_code == 409 and r.json()["error"]["code"] == "institution_active"
    seat = me.post("/api/v1/institution/seats", json={"names": ["Ada"]}).json()["credentials"][0]
    with session_factory() as s:
        sub = s.scalar(select(Subscription).where(Subscription.institution_id.is_not(None)))
        sub.current_period_end = utcnow() - timedelta(days=1)
        s.commit()
    assert delete(me).status_code == 204
    with session_factory() as s:
        seat_user = s.scalar(select(User).where(User.login_id == seat["login_id"]))
        assert seat_user.is_active is False  # its people are closed out with it


def test_a_seat_login_cannot_delete_itself_or_change_its_email(me, second, session_factory) -> None:
    with session_factory() as s:
        user = s.scalar(select(User).where(User.email == "a@example.com"))
        billing_service.admin_grant(
            s,
            user=user,
            plan_code="institution_10",
            months=1,
            institution_name="School",
            settings=Settings(),
        )
    seat = me.post("/api/v1/institution/seats", json={"names": ["Ada"]}).json()["credentials"][0]
    assert login(second, seat["login_id"], password=seat["password"]).status_code == 200
    r = delete(second, password=seat["password"])
    assert r.status_code == 403 and r.json()["error"]["code"] == "seat_managed"
    r = second.post(
        "/api/v1/account/change-email",
        json={"new_email": "x@example.com", "password": seat["password"]},
    )
    assert r.status_code == 403
    assert second.post("/api/v1/auth/2fa/setup").status_code == 409  # no email to attach it to
