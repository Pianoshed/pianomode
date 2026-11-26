from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.db import get_session
from app.core.errors import ForbiddenError, PaymentRequiredError, UnauthorizedError
from app.models.user import Role, User
from app.services import auth_service, billing_service, two_factor_service
from app.services.auth_service import AuthContext

SessionDep = Annotated[Session, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]

_UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def enforce_same_origin(request: Request, settings: SettingsDep) -> None:
    """CSRF defence on top of SameSite=Lax cookies.

    State-changing requests must come from an allowed web origin. Browsers always send `Origin`
    on such requests; a request carrying a session cookie but no Origin is rejected.
    """
    if request.method not in _UNSAFE_METHODS:
        return
    origin = request.headers.get("origin")
    allowed = {o.rstrip("/") for o in settings.cors_origins} | {settings.public_web_url.rstrip("/")}
    if origin is not None:
        if origin.rstrip("/") not in allowed:
            raise ForbiddenError("Request origin is not allowed.", code="origin_not_allowed")
        return
    if request.cookies.get(settings.session_cookie_name):
        raise ForbiddenError("Origin header is required.", code="origin_required")


def get_auth_context(
    request: Request, session: SessionDep, settings: SettingsDep
) -> AuthContext | None:
    raw = request.cookies.get(settings.session_cookie_name)
    if not raw or len(raw) > 200:
        return None
    return auth_service.authenticate_session(session, raw, settings)


OptionalAuth = Annotated[AuthContext | None, Depends(get_auth_context)]


def require_auth(ctx: OptionalAuth) -> AuthContext:
    if ctx is None:
        raise UnauthorizedError("Sign in to continue.")
    return ctx


RequireAuth = Annotated[AuthContext, Depends(require_auth)]


def require_user(ctx: RequireAuth) -> User:
    return ctx.user


CurrentUser = Annotated[User, Depends(require_user)]


def require_roles(*roles: Role) -> Callable[..., User]:
    """Backend authorization. Hiding UI controls is never a substitute for this."""
    allowed = set(roles)

    def dependency(user: CurrentUser, settings: SettingsDep) -> User:
        if not allowed & user.role_names:
            raise ForbiddenError("You do not have permission to do this.")
        if (
            Role.ADMIN in user.role_names
            and settings.admins_need_two_factor
            and not two_factor_service.is_enabled(user)
        ):
            # An administrator can grant access and see everyone's details, so a stolen
            # password alone must not be enough. They can still use the app as a learner.
            raise ForbiddenError(
                "Turn on two-factor sign-in in Account Settings to use admin tools.",
                code="two_factor_setup_required",
            )
        return user

    return dependency


def require_access(ctx: RequireAuth, session: SessionDep, settings: SettingsDep) -> User:
    """Signed in and allowed to use the learning tools (paid, trial, active seat, or staff)."""
    ent = billing_service.resolve_entitlement(session, ctx.user, settings)
    if not ent.has_access:
        raise PaymentRequiredError(
            "Your access has ended. Open Subscription to continue.",
            details={"reason": ent.reason},
        )
    return ctx.user
