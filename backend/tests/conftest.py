from collections.abc import Callable, Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
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

PASSWORD = "correct horse battery"
ORIGIN = {"Origin": "http://localhost:3000"}


@pytest.fixture
def session_factory() -> sessionmaker[Session]:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


@pytest.fixture
def session(session_factory: sessionmaker[Session]) -> Iterator[Session]:
    with session_factory() as s:
        yield s


@pytest.fixture
def outbox() -> InMemoryEmailSender:
    return InMemoryEmailSender()


@pytest.fixture
def app(session_factory: sessionmaker[Session], outbox: InMemoryEmailSender) -> FastAPI:
    application = create_app()
    limiter = InMemoryRateLimiter()

    def override_session() -> Iterator[Session]:
        with session_factory() as s:
            yield s

    application.dependency_overrides[get_session] = override_session
    application.dependency_overrides[get_email_sender] = lambda: outbox
    application.dependency_overrides[get_rate_limiter] = lambda: limiter
    return application


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app, headers=ORIGIN) as c:
        yield c


@pytest.fixture
def make_user(session_factory: sessionmaker[Session]) -> Callable[..., User]:
    def _make(
        email: str = "learner@example.com",
        *,
        roles: tuple[Role, ...] = (Role.LEARNER,),
        verified: bool = True,
        active: bool = True,
        password: str = PASSWORD,
    ) -> User:
        with session_factory() as s:
            user = User(
                email=email,
                password_hash=hash_password(password),
                display_name="Test User",
                is_active=active,
                email_verified_at=utcnow() if verified else None,
                roles=[UserRole(role=r) for r in roles],
            )
            s.add(user)
            s.commit()
            return user

    return _make


@pytest.fixture
def sign_in(client: TestClient) -> Callable[..., None]:
    def _sign_in(email: str = "learner@example.com", password: str = PASSWORD) -> None:
        r = client.post("/api/v1/auth/login", json={"email": email, "password": password})
        assert r.status_code == 200, r.text

    return _sign_in
