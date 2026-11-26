"""Give an existing account the admin (or educator) role, or take it away.

The person registers and verifies their email in the app first, then on the server:

    cd backend
    python -m scripts.make_admin you@example.com
    python -m scripts.make_admin teacher@example.com --role educator
    python -m scripts.make_admin former@example.com --remove
    python -m scripts.make_admin boss@example.com --reset-2fa     (lost phone)

Admins can use Billing Admin and Content Admin. There is no way to become an admin from the web
app itself, on purpose: this needs access to the server.
"""

import argparse

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_session
from app.models.user import Role, User, UserRole
from app.services import auth_service, two_factor_service
from app.services.auth_service import normalize_email


def set_role(session: Session, email: str, role: Role, *, remove: bool = False) -> str:
    """Add or remove `role`. Returns a sentence saying what happened."""
    user = session.scalar(select(User).where(User.email == normalize_email(email)))
    if user is None:
        raise SystemExit(f"No account has the email {email}. Register in the app first.")
    if user.email_verified_at is None and not remove:
        raise SystemExit(
            f"{email} has not verified their email yet. Ask them to, then run this again."
        )
    has = role in user.role_names
    if remove:
        if not has:
            return f"{email} did not have the {role.value} role."
        if role is Role.LEARNER:
            raise SystemExit("Every account keeps the learner role.")
        user.roles = [r for r in user.roles if r.role is not role]
        session.commit()
        return f"Removed the {role.value} role from {email}."
    if has:
        return f"{email} already has the {role.value} role."
    user.roles.append(UserRole(role=role))
    session.commit()
    return f"{email} now has the {role.value} role."


def reset_two_factor(session: Session, email: str) -> str:
    """For someone who lost their phone and recovery codes. Needs server access, by design."""
    user = session.scalar(select(User).where(User.email == normalize_email(email)))
    if user is None:
        raise SystemExit(f"No account has the email {email}.")
    two_factor_service.clear(session, user)
    auth_service.revoke_all_sessions(session, user.id)
    session.commit()
    return f"Two-factor is off for {email} and they were signed out. They should set it up again."


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("email")
    parser.add_argument("--role", choices=[Role.ADMIN.value, Role.EDUCATOR.value], default="admin")
    parser.add_argument("--remove", action="store_true", help="take the role away instead")
    parser.add_argument(
        "--reset-2fa", action="store_true", help="turn off two-factor sign-in (lost phone)"
    )
    args = parser.parse_args(argv)
    session = next(get_session())
    try:
        if args.reset_2fa:
            print(reset_two_factor(session, args.email))
        else:
            print(set_role(session, args.email, Role(args.role), remove=args.remove))
    finally:
        session.close()


if __name__ == "__main__":
    main()
