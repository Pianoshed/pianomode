"""A simple load test: many pretend people use the app at once, and we time every request.

    # 1. make test accounts (on a TEST database, never the real one)
    python -m scripts.loadtest seed --users 50
    # 2. run against a running API
    python -m scripts.loadtest run --base http://localhost:8000 --users 50 --seconds 60
    # 3. remove the test accounts
    python -m scripts.loadtest clean

Each pretend person signs in once, then keeps doing what learners do (dashboard, lessons, library,
theory pages, billing status, progressions) with a short pause between requests.

Read the result with care. Run it on a server like the one you will deploy to, from a DIFFERENT
machine (a load generator on the same machine steals its CPU), and against the same PostgreSQL and
Redis settings as production. Numbers from a laptop or a tiny test box show relative cost and
errors, not how many users the real site holds.

Each pretend person has their own fake client address (X-Forwarded-For), so per-address rate limits
behave as they would with real users; start the API with PIANO_TRUSTED_PROXIES=1 for that to work.
"""

import argparse
import asyncio
import random
import statistics
import time
from collections import defaultdict

import httpx
from sqlalchemy import delete, select

from app.core.db import get_session
from app.core.security import hash_password
from app.models.base import utcnow
from app.models.user import Role, User, UserRole

PASSWORD = "load test passphrase 42"
DOMAIN = "loadtest.invalid"

# (weight, method, path). Weights are rough shares of what people do.
MIX: list[tuple[int, str, str]] = [
    (20, "GET", "/api/v1/dashboard"),
    (15, "GET", "/api/v1/lessons"),
    (10, "GET", "/api/v1/auth/me"),
    (10, "GET", "/api/v1/library"),
    (10, "GET", "/api/v1/billing/status"),
    (10, "GET", "/api/v1/movements"),
    (10, "GET", "/api/v1/theory/scales"),
    (5, "GET", "/api/v1/theory/chords/types"),
    (5, "GET", "/api/v1/theory/progressions/templates"),
    (5, "GET", "/api/v1/practice/history"),
]


def seed(users: int) -> None:
    session = next(get_session())
    try:
        hashed = hash_password(
            PASSWORD
        )  # one hash, reused: the test is about the app, not about us hashing
        existing = set(session.scalars(select(User.email).where(User.email.like(f"%@{DOMAIN}"))))
        added = 0
        for n in range(users):
            email = f"load{n}@{DOMAIN}"
            if email in existing:
                continue
            session.add(
                User(
                    email=email,
                    password_hash=hashed,
                    display_name=f"Load {n}",
                    email_verified_at=utcnow(),
                    roles=[UserRole(role=Role.LEARNER)],
                )
            )
            added += 1
        session.commit()
        print(f"{added} test accounts added ({len(existing)} already there)")
    finally:
        session.close()


def clean() -> None:
    session = next(get_session())
    try:
        ids = list(session.scalars(select(User.id).where(User.email.like(f"%@{DOMAIN}"))))
        session.execute(delete(User).where(User.id.in_(ids)))
        session.commit()
        print(f"{len(ids)} test accounts removed")
    finally:
        session.close()


def pct(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(len(ordered) * p))]


async def person(
    n: int,
    base: str,
    origin: str,
    deadline: float,
    stats: dict[str, list[tuple[float, int]]],
    logins: list[float],
    errors: list[str],
) -> None:
    headers = {"Origin": origin, "X-Forwarded-For": f"10.{n // 250}.{n % 250}.{(n * 7) % 250 + 1}"}
    async with httpx.AsyncClient(base_url=base, headers=headers, timeout=30.0) as c:
        t = time.perf_counter()
        r = await c.post(
            "/api/v1/auth/login", json={"identifier": f"load{n}@{DOMAIN}", "password": PASSWORD}
        )
        logins.append(time.perf_counter() - t)
        if r.status_code != 200:
            errors.append(f"login {r.status_code}")
            return
        weights = [w for w, _, _ in MIX]
        while time.perf_counter() < deadline:
            _, method, path = random.choices(MIX, weights)[0]
            t = time.perf_counter()
            try:
                res = await c.request(method, path)
                stats[path].append((time.perf_counter() - t, res.status_code))
            except httpx.HTTPError as exc:
                stats[path].append((time.perf_counter() - t, 0))
                errors.append(type(exc).__name__)
            await asyncio.sleep(random.uniform(0.3, 1.0))  # a person reads the page


async def run(base: str, origin: str, users: int, seconds: int) -> None:
    stats: dict[str, list[tuple[float, int]]] = defaultdict(list)
    logins: list[float] = []
    errors: list[str] = []
    start = time.perf_counter()
    deadline = start + seconds
    await asyncio.gather(
        *(person(n, base, origin, deadline, stats, logins, errors) for n in range(users))
    )
    elapsed = time.perf_counter() - start

    total = sum(len(v) for v in stats.values())
    bad = sum(1 for v in stats.values() for _, code in v if code >= 400 or code == 0)
    print(f"\n{users} people for {elapsed:.0f}s against {base}")
    rate = total / elapsed
    n_login_errors = len([e for e in errors if e.startswith("login")])
    print(f"requests: {total} ({rate:.1f}/s)   failed (4xx/5xx/network): {bad}")
    print(f"sign-in errors: {n_login_errors}")
    if logins:
        slowest = max(logins) * 1000
        print(
            f"sign-in: median {statistics.median(logins) * 1000:.0f} ms, slowest {slowest:.0f} ms"
        )
    print(f"\n{'endpoint':42} {'count':>6} {'median':>8} {'p95':>8} {'p99':>8} {'errors':>7}")
    for path, rows in sorted(stats.items()):
        lat = [x * 1000 for x, _ in rows]
        errs = sum(1 for _, code in rows if code >= 400 or code == 0)
        med, p95, p99 = statistics.median(lat), pct(lat, 0.95), pct(lat, 0.99)
        print(f"{path:42} {len(rows):6d} {med:7.0f}m {p95:7.0f}m {p99:7.0f}m {errs:7d}")
    codes: dict[int, int] = defaultdict(int)
    for rows in stats.values():
        for _, code in rows:
            codes[code] += 1
    print("\nstatus codes:", dict(sorted(codes.items())))
    if errors:
        print("other errors:", sorted(set(errors))[:5])


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    sub = parser.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("seed")
    s.add_argument("--users", type=int, default=50)
    sub.add_parser("clean")
    r = sub.add_parser("run")
    r.add_argument("--base", default="http://localhost:8000")
    r.add_argument(
        "--origin",
        default="http://localhost:3000",
        help="the site address the API allows (PIANO_CORS_ORIGINS), sent as the Origin header",
    )
    r.add_argument("--users", type=int, default=50)
    r.add_argument("--seconds", type=int, default=60)
    args = parser.parse_args(argv)
    if args.cmd == "seed":
        seed(args.users)
    elif args.cmd == "clean":
        clean()
    else:
        asyncio.run(run(args.base, args.origin, args.users, args.seconds))


if __name__ == "__main__":
    main()
