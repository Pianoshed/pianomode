import threading
import time
from collections.abc import Callable
from functools import lru_cache
from typing import Annotated, Protocol, cast

import redis
from fastapi import Depends, Request

from app.core.config import Settings, get_settings
from app.core.errors import RateLimitedError, ServiceUnavailableError
from app.core.net import client_ip
from app.core.security import hash_token

SettingsDep = Annotated[Settings, Depends(get_settings)]


class RateLimiter(Protocol):
    def hit(self, key: str, limit: int, window_seconds: int) -> bool:
        """Record one attempt. Returns False once the limit for the window is exceeded."""
        ...


class InMemoryRateLimiter:
    """Fixed-window limiter for tests and single-process development only."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._hits: dict[str, tuple[float, int]] = {}
        self._lock = threading.Lock()

    def hit(self, key: str, limit: int, window_seconds: int) -> bool:
        with self._lock:
            now = self._clock()
            start, count = self._hits.get(key, (now, 0))
            if now - start >= window_seconds:
                start, count = now, 0
            count += 1
            self._hits[key] = (start, count)
            return count <= limit


class _RedisLike(Protocol):
    def set(self, name: str, value: int, ex: int, nx: bool) -> object: ...
    def incr(self, name: str) -> int: ...


class RedisRateLimiter:
    """Fixed-window limiter shared across API processes. Fails closed if Redis is unreachable."""

    def __init__(self, client: _RedisLike) -> None:
        self._r = client

    def hit(self, key: str, limit: int, window_seconds: int) -> bool:
        name = f"rl:{key}"
        try:
            self._r.set(name, 0, ex=window_seconds, nx=True)  # creates the key with a TTL, once
            return self._r.incr(name) <= limit
        except redis.RedisError as exc:
            raise ServiceUnavailableError(
                "Rate limiting is unavailable. Try again shortly.", code="rate_limiter_unavailable"
            ) from exc


@lru_cache
def _build(backend: str, redis_url: str) -> RateLimiter:
    if backend == "redis":
        return RedisRateLimiter(cast(_RedisLike, redis.Redis.from_url(redis_url)))
    return InMemoryRateLimiter()


def get_rate_limiter() -> RateLimiter:
    s = get_settings()
    return _build(s.rate_limit_backend, s.redis_url)


LimiterDep = Annotated[RateLimiter, Depends(get_rate_limiter)]


def enforce(limiter: RateLimiter, key: str, limit: int, window_seconds: int) -> None:
    if not limiter.hit(key, limit, window_seconds):
        raise RateLimitedError(
            "Too many attempts. Wait a while and try again.",
            headers={"Retry-After": str(window_seconds)},
        )


def rate_limited(
    name: str, limit: int, window_seconds: int, *, by_session: bool = False
) -> Callable[..., None]:
    """A limit as a route dependency, counted per client IP.

    `by_session=True` counts per signed-in session instead (when a session cookie is present), for
    routes that already require sign-in. That keeps a school whose students share one internet
    connection from using up each other's allowance. Never use it on routes open to anonymous
    callers: a made-up cookie would give every request a fresh allowance.
    """

    def dependency(request: Request, limiter: LimiterDep, settings: SettingsDep) -> None:
        cookie = request.cookies.get(settings.session_cookie_name) if by_session else None
        who = (
            f"s:{hash_token(cookie)[:24]}"
            if cookie
            else f"ip:{client_ip(request, settings.trusted_proxies)}"
        )
        enforce(limiter, f"{name}:{who}", limit, window_seconds)

    return dependency
