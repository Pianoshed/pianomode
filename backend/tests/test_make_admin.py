import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.models.user import Role, User
from scripts.make_admin import set_role


def roles(sf: sessionmaker[Session], email: str) -> set[Role]:
    with sf() as s:
        return s.scalar(select(User).where(User.email == email)).role_names


def test_promote_and_demote(make_user, session_factory) -> None:
    make_user("boss@example.com")
    with session_factory() as s:
        assert "now has the admin role" in set_role(s, "Boss@Example.com", Role.ADMIN)
    assert roles(session_factory, "boss@example.com") == {Role.LEARNER, Role.ADMIN}
    with session_factory() as s:
        assert "already has" in set_role(s, "boss@example.com", Role.ADMIN)
        assert "Removed" in set_role(s, "boss@example.com", Role.ADMIN, remove=True)
    assert roles(session_factory, "boss@example.com") == {Role.LEARNER}


def test_refuses_unknown_or_unverified_accounts_and_learner_removal(
    make_user, session_factory
) -> None:
    make_user("new@example.com", verified=False)
    make_user("ok@example.com")
    with session_factory() as s:
        with pytest.raises(SystemExit, match="Register"):
            set_role(s, "nobody@example.com", Role.ADMIN)
        with pytest.raises(SystemExit, match="verified"):
            set_role(s, "new@example.com", Role.ADMIN)
        with pytest.raises(SystemExit, match="learner"):
            set_role(s, "ok@example.com", Role.LEARNER, remove=True)


def test_admin_can_open_billing_admin(client, make_user, sign_in, session_factory) -> None:
    make_user("boss@example.com")
    with session_factory() as s:
        set_role(s, "boss@example.com", Role.ADMIN)
    sign_in("boss@example.com")
    assert client.get("/api/v1/admin/billing/payments").status_code == 200
