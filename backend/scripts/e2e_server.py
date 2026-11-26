"""Run the real API on in-memory SQLite for the browser end-to-end tests in frontend/e2e.

Creates a verified learner (learner@example.com), an educator (teacher@example.com), an admin
(admin@example.com) and publishes
the built-in chord movements. Not for production: no persistence, fixed password.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from collections.abc import Iterator

import uvicorn
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.db import get_session
from app.core.rate_limit import InMemoryRateLimiter, get_rate_limiter
from app.core.security import hash_password
from app.main import create_app
from app.models import Base
from app.models.base import utcnow
from app.models.user import Role, User, UserRole
from app.services.email import InMemoryEmailSender, get_email_sender

engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
Base.metadata.create_all(engine)
factory = sessionmaker(bind=engine, expire_on_commit=False)
with factory() as s:
    s.add(
        User(
            email="learner@example.com",
            password_hash=hash_password("correct horse battery"),
            display_name="Test User",
            is_active=True,
            email_verified_at=utcnow(),
            roles=[UserRole(role=Role.LEARNER)],
        )
    )
    s.add(
        User(
            email="teacher@example.com",
            password_hash=hash_password("correct horse battery"),
            display_name="Test Teacher",
            is_active=True,
            email_verified_at=utcnow(),
            roles=[UserRole(role=Role.EDUCATOR)],
        )
    )
    s.add(
        User(
            email="admin@example.com",
            password_hash=hash_password("correct horse battery"),
            display_name="Boss Admin",
            is_active=True,
            email_verified_at=utcnow(),
            roles=[UserRole(role=Role.ADMIN)],
        )
    )
    s.commit()
    from app.services import movement_service

    movement_service.seed_default_movements(s)
app = create_app()
limiter, outbox = InMemoryRateLimiter(), InMemoryEmailSender()


def override() -> Iterator[Session]:
    with factory() as s:
        yield s


app.dependency_overrides[get_session] = override
app.dependency_overrides[get_rate_limiter] = lambda: limiter
app.dependency_overrides[get_email_sender] = lambda: outbox


@app.get("/__e2e/outbox", include_in_schema=False)
def _e2e_outbox() -> list[dict[str, str]]:
    """Test-only: the emails the app "sent", so browser tests can follow their links."""
    return [{"to": m.to, "subject": m.subject, "body": m.body} for m in outbox.messages]


uvicorn.run(app, host="127.0.0.1", port=8000, log_level="warning")
