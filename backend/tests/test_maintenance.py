from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.security import hash_token
from app.models.base import utcnow
from app.models.user import OneTimeToken, User, UserSession
from app.services.maintenance_service import purge_expired


def _user(s: Session) -> User:
    u = User(email="a@example.com", password_hash="x", display_name="A")
    s.add(u)
    s.flush()
    return u


def test_purges_only_long_dead_rows(session_factory: sessionmaker[Session]) -> None:
    now = utcnow()
    with session_factory() as s:
        u = _user(s)

        def sess(name: str, expires: timedelta, revoked: timedelta | None = None) -> None:
            s.add(
                UserSession(
                    user_id=u.id,
                    token_hash=hash_token(name),
                    expires_at=now + expires,
                    revoked_at=None if revoked is None else now + revoked,
                )
            )

        def tok(name: str, expires: timedelta, used: timedelta | None = None) -> None:
            s.add(
                OneTimeToken(
                    user_id=u.id,
                    purpose="password_reset",
                    token_hash=hash_token(name),
                    expires_at=now + expires,
                    used_at=None if used is None else now + used,
                )
            )

        sess("live", timedelta(days=5))
        sess("just-expired", -timedelta(days=2))
        sess("long-expired", -timedelta(days=40))
        sess("long-revoked", timedelta(days=5), -timedelta(days=40))
        sess("recently-revoked", timedelta(days=5), -timedelta(days=1))
        tok("fresh", timedelta(hours=1))
        tok("just-used", timedelta(hours=1), -timedelta(days=1))
        tok("old-expired", -timedelta(days=10))
        tok("old-used", timedelta(hours=1), -timedelta(days=10))
        s.commit()

        result = purge_expired(s, now)

        assert (result.sessions, result.tokens) == (2, 2)
        left = set(s.scalars(select(UserSession.token_hash)))
        assert left == {hash_token(n) for n in ("live", "just-expired", "recently-revoked")}
        assert s.scalar(select(func.count()).select_from(OneTimeToken)) == 2
        again = purge_expired(s, now)
        assert (again.sessions, again.tokens) == (0, 0)
