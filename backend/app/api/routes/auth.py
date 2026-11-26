from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, RequireAuth, SessionDep, SettingsDep
from app.core.config import Settings
from app.core.net import client_ip
from app.core.rate_limit import LimiterDep, enforce, rate_limited
from app.core.security import hash_token
from app.models.user import Role, User
from app.schemas.auth import (
    ChangePasswordRequest,
    DeactivateRequest,
    LoginRequest,
    MessageResponse,
    PasswordResetConfirm,
    PasswordResetRequest,
    RegisterRequest,
    UpdatePreferencesRequest,
    UpdateProfileRequest,
    UserRead,
    VerifyEmailRequest,
)
from app.schemas.errors import ErrorResponse
from app.services import auth_service, billing_service, two_factor_service
from app.services.email import EmailSender, get_email_sender

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])
SenderDep = Annotated[EmailSender, Depends(get_email_sender)]

HOUR = 3600
FIFTEEN_MIN = 900


def _email_key(email: str) -> str:
    return hash_token(auth_service.normalize_email(email))[:32]


def _identifier_key(identifier: str) -> str:
    return hash_token(auth_service.normalize_identifier(identifier))[:32]


def user_to_read(user: User, session: Session, settings: Settings) -> UserRead:
    role: Literal["owner", "seat"] | None = None
    if billing_service.is_seat(session, user):
        role = "seat"
    elif billing_service.owned_institution(session, user) is not None:
        role = "owner"
    return UserRead(
        id=user.id,
        email=user.email,
        login_id=user.login_id,
        display_name=user.display_name,
        roles=sorted(user.role_names),
        email_verified=user.email_verified_at is not None,
        reminder_emails=user.reminder_emails,
        two_factor_enabled=two_factor_service.is_enabled(user),
        two_factor_setup_needed=(
            Role.ADMIN in user.role_names
            and settings.admins_need_two_factor
            and not two_factor_service.is_enabled(user)
        ),
        institution_role=role,
    )


def _cookie_args(settings: Settings) -> dict[str, object]:
    return {
        "key": settings.session_cookie_name,
        "path": "/",
        "httponly": True,
        "secure": settings.cookie_secure,
        "samesite": "lax",
    }


@router.post(
    "/register",
    status_code=202,
    response_model=MessageResponse,
    dependencies=[Depends(rate_limited("register", 5, HOUR))],
    responses={422: {"model": ErrorResponse}, 429: {"model": ErrorResponse}},
)
def register(
    body: RegisterRequest,
    session: SessionDep,
    settings: SettingsDep,
    limiter: LimiterDep,
    sender: SenderDep,
) -> MessageResponse:
    enforce(limiter, f"register:email:{_email_key(body.email)}", 3, HOUR)
    auth_service.register(
        session,
        email=body.email,
        password=body.password,
        display_name=body.display_name,
        sender=sender,
        settings=settings,
    )
    return MessageResponse(message="Check your email to finish creating your account.")


@router.post(
    "/verify-email",
    response_model=MessageResponse,
    dependencies=[Depends(rate_limited("verify", 20, HOUR))],
    responses={400: {"model": ErrorResponse}},
)
def verify_email(body: VerifyEmailRequest, session: SessionDep) -> MessageResponse:
    auth_service.verify_email(session, body.token)
    return MessageResponse(message="Email verified. You can sign in now.")


@router.post(
    "/login",
    response_model=UserRead,
    dependencies=[Depends(rate_limited("login", 20, FIFTEEN_MIN))],
    responses={401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
)
def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    session: SessionDep,
    settings: SettingsDep,
    limiter: LimiterDep,
) -> UserRead:
    enforce(limiter, f"login:email:{_identifier_key(body.identifier)}", 10, FIFTEEN_MIN)
    user, raw = auth_service.login(
        session,
        identifier=body.identifier,
        password=body.password,
        otp=body.otp,
        ip=client_ip(request, settings.trusted_proxies),
        user_agent=request.headers.get("user-agent"),
        settings=settings,
    )
    response.set_cookie(
        value=raw,
        max_age=settings.session_ttl_days * 86400,
        **_cookie_args(settings),  # type: ignore[arg-type]
    )
    return user_to_read(user, session, settings)


@router.post("/logout", status_code=204)
def logout(request: Request, session: SessionDep, settings: SettingsDep) -> Response:
    raw = request.cookies.get(settings.session_cookie_name)
    if raw:
        auth_service.revoke_session(session, raw)
    response = Response(status_code=204)
    response.delete_cookie(**_cookie_args(settings))  # type: ignore[arg-type]
    return response


@router.post(
    "/password-reset/request",
    status_code=202,
    response_model=MessageResponse,
    dependencies=[Depends(rate_limited("reset", 5, HOUR))],
)
def request_password_reset(
    body: PasswordResetRequest,
    session: SessionDep,
    settings: SettingsDep,
    limiter: LimiterDep,
    sender: SenderDep,
) -> MessageResponse:
    enforce(limiter, f"reset:email:{_email_key(body.email)}", 3, HOUR)
    auth_service.request_password_reset(session, email=body.email, sender=sender, settings=settings)
    return MessageResponse(message="If that email has an account, a reset link is on its way.")


@router.post(
    "/password-reset/confirm",
    response_model=MessageResponse,
    dependencies=[Depends(rate_limited("reset-confirm", 10, HOUR))],
    responses={400: {"model": ErrorResponse}, 422: {"model": ErrorResponse}},
)
def confirm_password_reset(body: PasswordResetConfirm, session: SessionDep) -> MessageResponse:
    auth_service.confirm_password_reset(
        session, raw_token=body.token, new_password=body.new_password
    )
    return MessageResponse(message="Password changed. Sign in with your new password.")


@router.get("/me", response_model=UserRead, responses={401: {"model": ErrorResponse}})
def me(user: CurrentUser, session: SessionDep, settings: SettingsDep) -> UserRead:
    return user_to_read(user, session, settings)


@router.patch("/me", response_model=UserRead)
def update_me(
    body: UpdateProfileRequest, user: CurrentUser, session: SessionDep, settings: SettingsDep
) -> UserRead:
    return user_to_read(
        auth_service.update_display_name(session, user, body.display_name), session, settings
    )


@router.patch("/me/preferences", response_model=UserRead)
def update_preferences(
    body: UpdatePreferencesRequest, user: CurrentUser, session: SessionDep, settings: SettingsDep
) -> UserRead:
    """Turn the plan-ending reminder emails on or off."""
    user.reminder_emails = body.reminder_emails
    session.commit()
    return user_to_read(user, session, settings)


@router.post(
    "/me/change-password",
    response_model=MessageResponse,
    dependencies=[Depends(rate_limited("change-password", 10, HOUR))],
)
def change_password(
    body: ChangePasswordRequest, ctx: RequireAuth, session: SessionDep
) -> MessageResponse:
    auth_service.change_password(
        session,
        ctx=ctx,
        current_password=body.current_password,
        new_password=body.new_password,
    )
    return MessageResponse(message="Password changed. Other devices were signed out.")


@router.post(
    "/me/deactivate",
    response_model=MessageResponse,
    dependencies=[Depends(rate_limited("deactivate", 5, HOUR))],
)
def deactivate(
    body: DeactivateRequest, user: CurrentUser, session: SessionDep, settings: SettingsDep
) -> Response:
    auth_service.deactivate_account(session, user=user, password=body.password)
    response = Response(status_code=204)
    response.delete_cookie(**_cookie_args(settings))  # type: ignore[arg-type]
    return response
