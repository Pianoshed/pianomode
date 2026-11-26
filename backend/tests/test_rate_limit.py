import fakeredis

from app.core.rate_limit import InMemoryRateLimiter, RedisRateLimiter


def test_in_memory_limit_and_window_reset() -> None:
    now = [0.0]
    lim = InMemoryRateLimiter(clock=lambda: now[0])
    assert all(lim.hit("k", 3, 60) for _ in range(3))
    assert not lim.hit("k", 3, 60)
    assert lim.hit("other", 3, 60)  # keys are independent
    now[0] = 61.0
    assert lim.hit("k", 3, 60)  # new window


def test_redis_limiter_enforces_limit_and_sets_ttl() -> None:
    r = fakeredis.FakeRedis()
    lim = RedisRateLimiter(r)  # type: ignore[arg-type]
    assert all(lim.hit("k", 3, 60) for _ in range(3))
    assert not lim.hit("k", 3, 60)
    assert 0 < r.ttl("rl:k") <= 60
