import pytest
import sentry_sdk
from fastapi import Depends, FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from starlette.requests import Request

from app import main as main_module
from app.core.config import Settings, get_settings
from app.core.errors import RateLimitedError
from app.core.monitoring import init_monitoring
from app.core.net import client_ip
from app.core.rate_limit import InMemoryRateLimiter, get_rate_limiter, rate_limited
from tests.conftest import ORIGIN


def make_request(forwarded: str | None, host: str = "10.0.0.9") -> Request:
    headers = [(b"x-forwarded-for", forwarded.encode())] if forwarded else []
    return Request({"type": "http", "headers": headers, "client": (host, 5000)})


# ------------------------------------------------------------------ real client address


@pytest.mark.parametrize(
    "forwarded,trusted,expected",
    [
        (None, 0, "10.0.0.9"),
        ("1.2.3.4", 0, "10.0.0.9"),  # no proxy configured: the header is ignored, cannot be spoofed
        ("1.2.3.4", 1, "1.2.3.4"),
        (
            "9.9.9.9, 1.2.3.4",
            1,
            "1.2.3.4",
        ),  # the caller wrote 9.9.9.9; our proxy appended the real one
        ("1.2.3.4, 172.18.0.5", 2, "1.2.3.4"),
        ("1.2.3.4", 2, "10.0.0.9"),  # shorter than our proxy chain: do not guess
        (None, 1, "10.0.0.9"),
        ("not-an-ip", 1, "10.0.0.9"),
        ("2001:db8::1", 1, "2001:db8::1"),
    ],
)
def test_client_ip(forwarded: str | None, trusted: int, expected: str) -> None:
    assert client_ip(make_request(forwarded), trusted) == expected


# ------------------------------------------------------------------ limits that fit schools


def limited_app(trusted: int = 0, by_session: bool = False) -> FastAPI:
    app = FastAPI()

    @app.exception_handler(RateLimitedError)
    async def too_many(_: Request, exc: RateLimitedError) -> JSONResponse:
        return JSONResponse(status_code=429, content={})

    limiter = InMemoryRateLimiter()
    app.dependency_overrides[get_rate_limiter] = lambda: limiter
    app.dependency_overrides[get_settings] = lambda: Settings(trusted_proxies=trusted)

    @app.get("/x", dependencies=[Depends(rate_limited("t", 2, 60, by_session=by_session))])
    def x() -> dict[str, bool]:
        return {"ok": True}

    return app


def test_students_on_one_connection_do_not_share_a_session_limit() -> None:
    app = limited_app(by_session=True)
    with TestClient(app) as a, TestClient(app) as b:
        a.cookies.set("piano_session", "token-a")
        b.cookies.set("piano_session", "token-b")
        assert [a.get("/x").status_code for _ in range(3)] == [200, 200, 429]
        assert [b.get("/x").status_code for _ in range(3)] == [
            200,
            200,
            429,
        ]  # same IP, own allowance


def test_without_session_mode_one_connection_shares_the_limit() -> None:
    app = limited_app()
    with TestClient(app) as a, TestClient(app) as b:
        a.cookies.set("piano_session", "token-a")
        b.cookies.set("piano_session", "token-b")
        assert a.get("/x").status_code == 200 and a.get("/x").status_code == 200
        assert b.get("/x").status_code == 429


def test_behind_a_proxy_different_visitors_get_different_limits() -> None:
    app = limited_app(trusted=1)
    with TestClient(app) as c:
        for _ in range(2):
            assert c.get("/x", headers={"x-forwarded-for": "1.1.1.1"}).status_code == 200
        assert c.get("/x", headers={"x-forwarded-for": "1.1.1.1"}).status_code == 429
        assert c.get("/x", headers={"x-forwarded-for": "2.2.2.2"}).status_code == 200


def test_session_mode_does_not_let_anonymous_callers_pick_their_own_bucket() -> None:
    # No cookie: falls back to the address, so it cannot be dodged by sending nothing.
    app = limited_app(by_session=True)
    with TestClient(app) as c:
        assert [c.get("/x").status_code for _ in range(3)] == [200, 200, 429]


# ------------------------------------------------------------------ responses


def test_every_response_carries_safe_headers_and_a_request_id(client: TestClient) -> None:
    r = client.get("/api/health")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["referrer-policy"] == "no-referrer"
    assert r.headers["cache-control"] == "no-store"
    assert len(r.headers["x-request-id"]) == 16


def test_unexpected_errors_are_logged_and_hide_internals(app: FastAPI) -> None:
    @app.get("/boom")
    def boom() -> None:
        raise RuntimeError("secret database password in this message")

    with TestClient(app, headers=ORIGIN, raise_server_exceptions=False) as c:
        r = c.get("/boom")
    assert r.status_code == 500
    body = r.json()["error"]
    assert body["code"] == "internal_error"
    assert "secret" not in r.text
    assert body["details"]["request_id"] == r.headers["x-request-id"]


def test_api_docs_are_hidden_in_production(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        main_module, "get_settings", lambda: Settings(env="production", trusted_proxies=1)
    )
    app = main_module.create_app()
    with TestClient(app) as c:
        assert [c.get(p).status_code for p in ("/docs", "/redoc", "/openapi.json")] == [
            404,
            404,
            404,
        ]
    monkeypatch.setattr(main_module, "get_settings", lambda: Settings())
    with TestClient(main_module.create_app()) as c:
        assert c.get("/docs").status_code == 200


# ------------------------------------------------------------------ production settings


GOOD = {
    "PIANO_ENV": "production",
    "PIANO_SECRET_KEY": "x" * 48,
    "PIANO_RATE_LIMIT_BACKEND": "redis",
    "PIANO_PAYSTACK_SECRET_KEY": "sk_live_x",
    "PIANO_RESEND_API_KEY": "re_x",
    "PIANO_PUBLIC_WEB_URL": "https://piano.example",
    "PIANO_TRUSTED_PROXIES": "1",
    "PIANO_REDIS_URL": "redis://:s3cret@redis:6379/0",
}


def production(monkeypatch: pytest.MonkeyPatch, **changes: str | None) -> Settings:
    get_settings.cache_clear()
    for k, v in {**GOOD, **changes}.items():
        if v is None:
            monkeypatch.delenv(k, raising=False)
        else:
            monkeypatch.setenv(k, v)
    try:
        return get_settings()
    finally:
        get_settings.cache_clear()


def test_a_complete_production_configuration_starts(monkeypatch: pytest.MonkeyPatch) -> None:
    assert production(monkeypatch).is_production


@pytest.mark.parametrize(
    "change,message",
    [
        ({"PIANO_SECRET_KEY": "change-me"}, "SECRET_KEY"),
        ({"PIANO_SECRET_KEY": "too-short"}, "at least 32"),
        ({"PIANO_RATE_LIMIT_BACKEND": "memory"}, "RATE_LIMIT_BACKEND"),
        ({"PIANO_PAYSTACK_SECRET_KEY": ""}, "PAYSTACK"),
        ({"PIANO_RESEND_API_KEY": ""}, "RESEND"),
        ({"PIANO_PUBLIC_WEB_URL": "http://piano.example"}, "https"),
        ({"PIANO_SECURE_COOKIES": "false"}, "SECURE_COOKIES"),
        ({"PIANO_TRUSTED_PROXIES": "0"}, "TRUSTED_PROXIES"),
    ],
)
def test_production_refuses_unsafe_settings(
    monkeypatch: pytest.MonkeyPatch, change: dict[str, str], message: str
) -> None:
    with pytest.raises(RuntimeError, match=message):
        production(monkeypatch, **change)


# ------------------------------------------------------------------ error reporting


def test_error_reporting_is_off_without_a_dsn(monkeypatch: pytest.MonkeyPatch) -> None:
    called: list[dict] = []
    monkeypatch.setattr(sentry_sdk, "init", lambda **kw: called.append(kw))
    assert init_monitoring(Settings()) is False and called == []


def test_error_reporting_never_sends_personal_data(monkeypatch: pytest.MonkeyPatch) -> None:
    called: list[dict] = []
    monkeypatch.setattr(sentry_sdk, "init", lambda **kw: called.append(kw))
    assert init_monitoring(Settings(sentry_dsn="https://k@o0.ingest.sentry.io/1", env="production"))
    assert called[0]["send_default_pii"] is False and called[0]["traces_sample_rate"] == 0.0
    assert called[0]["environment"] == "production"


# ------------------------------------------------------------------ password hashing under load


def test_only_a_few_password_hashes_run_at_the_same_time(monkeypatch: pytest.MonkeyPatch) -> None:
    """Each hash holds ~19 MB. Fifty sign-ins at once once peaked near 1 GB; now they queue."""
    import threading
    import time

    from app.core import security

    security.reset_hash_limit()
    monkeypatch.setattr(security, "get_settings", lambda: Settings(max_concurrent_hashes=3))
    running = peak = 0
    lock = threading.Lock()

    def slow_verify(stored: str, password: str) -> bool:
        nonlocal running, peak
        with lock:
            running += 1
            peak = max(peak, running)
        time.sleep(0.05)
        with lock:
            running -= 1
        return True

    class SlowHasher:
        verify = staticmethod(slow_verify)

    monkeypatch.setattr(security, "_hasher", SlowHasher())
    threads = [
        threading.Thread(target=security.verify_password, args=("h", "p")) for _ in range(20)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    security.reset_hash_limit()
    assert peak <= 3  # twenty callers, never more than three at once
    assert peak >= 2  # and they did still overlap (the limit is not 1)


def test_hashing_and_verifying_still_work_normally() -> None:
    from app.core.security import hash_password, verify_password

    h = hash_password("a long enough passphrase")
    assert verify_password(h, "a long enough passphrase") and not verify_password(h, "wrong")
    assert not verify_password("not a hash", "x")


def test_production_refuses_a_redis_without_a_password(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(RuntimeError, match="REDIS_URL"):
        production(monkeypatch, PIANO_REDIS_URL="redis://redis:6379/0")
