import re
from collections.abc import Callable
from datetime import timedelta

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.api.deps import require_roles
from app.models.base import utcnow
from app.models.user import OneTimeToken, Role, User, UserSession
from app.services.email import InMemoryEmailSender
from tests.conftest import PASSWORD

REG = {"email": "new@example.com", "password": PASSWORD, "display_name": "Ada"}


def token_from(outbox: InMemoryEmailSender, index: int = -1) -> str:
    match = re.search(r"token=([A-Za-z0-9_\-]+)", outbox.messages[index].body)
    assert match
    return match.group(1)


def test_register_verify_login_me_logout(client: TestClient, outbox: InMemoryEmailSender) -> None:
    r = client.post("/api/v1/auth/register", json=REG)
    assert r.status_code == 202
    assert len(outbox.messages) == 1 and outbox.messages[0].to == "new@example.com"

    r = client.post("/api/v1/auth/login", json={"email": REG["email"], "password": PASSWORD})
    assert r.status_code == 403 and r.json()["error"]["code"] == "email_not_verified"

    r = client.post("/api/v1/auth/verify-email", json={"token": token_from(outbox)})
    assert r.status_code == 200

    r = client.post("/api/v1/auth/login", json={"email": "NEW@example.com ", "password": PASSWORD})
    assert r.status_code == 200 and r.json()["roles"] == ["learner"]
    set_cookie = r.headers["set-cookie"].lower()
    assert "httponly" in set_cookie and "samesite=lax" in set_cookie

    assert client.get("/api/v1/auth/me").json()["display_name"] == "Ada"

    assert client.post("/api/v1/auth/logout").status_code == 204
    assert client.get("/api/v1/auth/me").status_code == 401


def test_register_does_not_reveal_existing_accounts(
    client: TestClient, outbox: InMemoryEmailSender, make_user: Callable[..., User]
) -> None:
    make_user("taken@example.com")
    fresh = client.post("/api/v1/auth/register", json={**REG, "email": "free@example.com"})
    taken = client.post("/api/v1/auth/register", json={**REG, "email": "taken@example.com"})
    assert (fresh.status_code, fresh.json()) == (taken.status_code, taken.json())
    assert [m.to for m in outbox.messages] == ["free@example.com", "taken@example.com"]
    assert "already exists" in outbox.messages[1].body


def test_password_is_argon2id_and_policy_enforced(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    assert client.post("/api/v1/auth/register", json=REG).status_code == 202
    with session_factory() as s:
        user = s.scalar(select(User))
        assert user is not None and user.password_hash.startswith("$argon2id$")
    for bad in ("short", "password123", "x@example.com"):
        r = client.post(
            "/api/v1/auth/register", json={**REG, "email": "x@example.com", "password": bad}
        )
        assert r.status_code == 422 and r.json()["error"]["code"] == "weak_password"


def test_login_errors_are_indistinguishable(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    make_user("real@example.com")
    wrong = client.post(
        "/api/v1/auth/login", json={"email": "real@example.com", "password": "x" * 12}
    )
    unknown = client.post(
        "/api/v1/auth/login", json={"email": "nobody@example.com", "password": "x" * 12}
    )
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json()


def test_verification_token_is_single_use_and_expires(
    client: TestClient, outbox: InMemoryEmailSender, session_factory: sessionmaker[Session]
) -> None:
    client.post("/api/v1/auth/register", json=REG)
    token = token_from(outbox)
    assert client.post("/api/v1/auth/verify-email", json={"token": token}).status_code == 200
    again = client.post("/api/v1/auth/verify-email", json={"token": token})
    assert again.status_code == 400 and again.json()["error"]["code"] == "invalid_token"

    client.post("/api/v1/auth/register", json={**REG, "email": "late@example.com"})
    late = token_from(outbox)
    with session_factory() as s:
        for t in s.scalars(select(OneTimeToken)):
            t.expires_at = utcnow() - timedelta(minutes=1)
        s.commit()
    assert client.post("/api/v1/auth/verify-email", json={"token": late}).status_code == 400


def test_session_expiry_and_idle_timeout(
    client: TestClient,
    make_user: Callable[..., User],
    sign_in: Callable[..., None],
    session_factory: sessionmaker[Session],
) -> None:
    make_user()
    sign_in()
    assert client.get("/api/v1/auth/me").status_code == 200
    with session_factory() as s:
        row = s.scalar(select(UserSession))
        assert row is not None
        row.last_seen_at = utcnow() - timedelta(days=8)
        s.commit()
    assert client.get("/api/v1/auth/me").status_code == 401

    sign_in()
    with session_factory() as s:
        row = s.scalars(select(UserSession).order_by(UserSession.created_at.desc())).first()
        assert row is not None
        row.expires_at = utcnow() - timedelta(seconds=1)
        s.commit()
    assert client.get("/api/v1/auth/me").status_code == 401


def test_password_reset_flow(
    client: TestClient,
    outbox: InMemoryEmailSender,
    make_user: Callable[..., User],
    sign_in: Callable[..., None],
) -> None:
    make_user("reset@example.com")
    sign_in("reset@example.com")

    unknown = client.post(
        "/api/v1/auth/password-reset/request", json={"email": "ghost@example.com"}
    )
    known = client.post("/api/v1/auth/password-reset/request", json={"email": "reset@example.com"})
    assert unknown.status_code == known.status_code == 202 and unknown.json() == known.json()
    assert [m.to for m in outbox.messages] == ["reset@example.com"]

    token = token_from(outbox)
    new_pw = "a brand new passphrase"
    assert (
        client.post(
            "/api/v1/auth/password-reset/confirm", json={"token": token, "new_password": new_pw}
        ).status_code
        == 200
    )
    assert (
        client.post(
            "/api/v1/auth/password-reset/confirm", json={"token": token, "new_password": new_pw}
        ).status_code
        == 400
    )

    assert client.get("/api/v1/auth/me").status_code == 401  # old session revoked
    bad = client.post(
        "/api/v1/auth/login", json={"email": "reset@example.com", "password": PASSWORD}
    )
    assert bad.status_code == 401
    ok = client.post("/api/v1/auth/login", json={"email": "reset@example.com", "password": new_pw})
    assert ok.status_code == 200


def test_change_password_keeps_current_session_only(
    app: FastAPI, client: TestClient, make_user: Callable[..., User], sign_in: Callable[..., None]
) -> None:
    make_user()
    sign_in()
    with TestClient(app, headers={"Origin": "http://localhost:3000"}) as other:
        other.post(
            "/api/v1/auth/login", json={"email": "learner@example.com", "password": PASSWORD}
        )
        assert other.get("/api/v1/auth/me").status_code == 200

        wrong = client.post(
            "/api/v1/auth/me/change-password",
            json={"current_password": "nope" * 3, "new_password": "another good passphrase"},
        )
        assert wrong.status_code == 401 and wrong.json()["error"]["code"] == "wrong_password"

        r = client.post(
            "/api/v1/auth/me/change-password",
            json={"current_password": PASSWORD, "new_password": "another good passphrase"},
        )
        assert r.status_code == 200
        assert client.get("/api/v1/auth/me").status_code == 200
        assert other.get("/api/v1/auth/me").status_code == 401


def test_update_profile_and_deactivate(
    client: TestClient, make_user: Callable[..., User], sign_in: Callable[..., None]
) -> None:
    make_user()
    sign_in()
    r = client.patch("/api/v1/auth/me", json={"display_name": "  Grace  "})
    assert r.json()["display_name"] == "Grace"
    assert client.patch("/api/v1/auth/me", json={"display_name": "   "}).status_code == 422

    assert (
        client.post("/api/v1/auth/me/deactivate", json={"password": "wrong password!"}).status_code
        == 401
    )
    assert client.post("/api/v1/auth/me/deactivate", json={"password": PASSWORD}).status_code == 204
    assert client.get("/api/v1/auth/me").status_code == 401
    r = client.post(
        "/api/v1/auth/login", json={"email": "learner@example.com", "password": PASSWORD}
    )
    assert r.status_code == 401


def test_register_rate_limit(client: TestClient) -> None:
    codes = [
        client.post("/api/v1/auth/register", json={**REG, "email": f"u{i}@example.com"}).status_code
        for i in range(6)
    ]
    assert codes[:5] == [202] * 5 and codes[5] == 429


def test_login_rate_limit_per_email(client: TestClient, make_user: Callable[..., User]) -> None:
    make_user()
    body = {"email": "learner@example.com", "password": "wrong password!"}
    codes = [client.post("/api/v1/auth/login", json=body).status_code for _ in range(11)]
    assert codes[:10] == [401] * 10 and codes[10] == 429
    r = client.post("/api/v1/auth/login", json=body)
    assert r.headers["retry-after"] == "900"


def test_origin_checks(
    app: FastAPI, client: TestClient, make_user: Callable[..., User], sign_in: Callable[..., None]
) -> None:
    make_user()
    evil = client.post(
        "/api/v1/auth/login",
        json={"email": "learner@example.com", "password": PASSWORD},
        headers={"Origin": "https://evil.example"},
    )
    assert evil.status_code == 403 and evil.json()["error"]["code"] == "origin_not_allowed"

    sign_in()
    with TestClient(app) as no_origin:  # same session cookie, but no Origin header
        no_origin.cookies.update(client.cookies)
        r = no_origin.post("/api/v1/auth/logout")
        assert r.status_code == 403 and r.json()["error"]["code"] == "origin_required"
        assert no_origin.get("/api/v1/auth/me").status_code == 200  # safe methods are fine


def test_role_enforcement_happens_on_the_backend(
    app: FastAPI, client: TestClient, make_user: Callable[..., User], sign_in: Callable[..., None]
) -> None:
    @app.get(
        "/api/v1/_admin-only", dependencies=[Depends(require_roles(Role.ADMIN, Role.EDUCATOR))]
    )
    def admin_only() -> dict[str, bool]:
        return {"ok": True}

    assert client.get("/api/v1/_admin-only").status_code == 401
    make_user("learner@example.com")
    make_user("admin@example.com", roles=(Role.ADMIN,))
    sign_in("learner@example.com")
    r = client.get("/api/v1/_admin-only")
    assert r.status_code == 403 and r.json()["error"]["code"] == "forbidden"
    client.post("/api/v1/auth/logout")
    sign_in("admin@example.com")
    assert client.get("/api/v1/_admin-only").status_code == 200
