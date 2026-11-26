"""Housekeeping: delete rows that can never be used again.

Sessions and one-time links (verify email, password reset, email change) pile up forever
otherwise, and each row holds an IP address and a browser name. Nothing here touches the audit
log, payments or anything a person created. Safe to run as often as you like.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import and_, delete, or_
from sqlalchemy.orm import Session

from app.models.base import utcnow
from app.models.user import OneTimeToken, UserSession

# Kept a little after they stop working, so a support question ("did my link expire?") can still
# be answered from the data.
SESSION_GRACE = timedelta(days=30)
TOKEN_GRACE = timedelta(days=7)


@dataclass(frozen=True)
class PurgeResult:
    sessions: int
    tokens: int


def purge_expired(session: Session, now: datetime | None = None) -> PurgeResult:
    now = now or utcnow()
    session_cutoff = now - SESSION_GRACE
    token_cutoff = now - TOKEN_GRACE
    sessions = session.execute(
        delete(UserSession).where(
            or_(
                UserSession.expires_at < session_cutoff,
                and_(UserSession.revoked_at.is_not(None), UserSession.revoked_at < session_cutoff),
            )
        )
    )
    tokens = session.execute(
        delete(OneTimeToken).where(
            or_(
                OneTimeToken.expires_at < token_cutoff,
                and_(OneTimeToken.used_at.is_not(None), OneTimeToken.used_at < token_cutoff),
            )
        )
    )
    session.commit()
    return PurgeResult(sessions=sessions.rowcount or 0, tokens=tokens.rowcount or 0)
