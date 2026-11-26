"""Your own account: export your data, change your email, delete your account."""

import json
from typing import Annotated

from fastapi import APIRouter, Depends, Response

from app.api.deps import CurrentUser, SessionDep, SettingsDep
from app.api.routes.auth import _cookie_args
from app.core.errors import AppError
from app.core.rate_limit import rate_limited
from app.schemas.account import ChangeEmailIn, ConfirmEmailChangeIn, DeleteAccountIn
from app.schemas.auth import MessageResponse
from app.schemas.errors import ErrorResponse
from app.services import account_service
from app.services.email import EmailSender, get_email_sender
from app.services.file_store import FileStore, get_file_store

HOUR = 3600
SenderDep = Annotated[EmailSender, Depends(get_email_sender)]
StoreDep = Annotated[FileStore, Depends(get_file_store)]

router = APIRouter(
    prefix="/api/v1/account",
    tags=["account"],
    responses={401: {"model": ErrorResponse}},
)


class ConfirmationWordError(AppError):
    status_code = 422
    code = "confirmation_required"


@router.get("/export", dependencies=[Depends(rate_limited("export", 5, HOUR, by_session=True))])
def export(user: CurrentUser, session: SessionDep) -> Response:
    """Everything we hold about you, as a JSON file."""
    body = json.dumps(account_service.export_data(session, user), indent=2, ensure_ascii=False)
    return Response(
        content=body,
        media_type="application/json",
        headers={"Content-Disposition": 'attachment; filename="my-keystudy-data.json"'},
    )


@router.post(
    "/change-email",
    status_code=202,
    response_model=MessageResponse,
    dependencies=[Depends(rate_limited("change-email", 5, HOUR, by_session=True))],
    responses={403: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
)
def change_email(
    body: ChangeEmailIn,
    user: CurrentUser,
    session: SessionDep,
    settings: SettingsDep,
    sender: SenderDep,
) -> MessageResponse:
    account_service.request_email_change(
        session,
        user,
        new_email=body.new_email,
        password=body.password,
        settings=settings,
        sender=sender,
    )
    return MessageResponse(
        message="If that address can be used, we sent a link to it. "
        "Your email changes when you open it."
    )


@router.post(
    "/confirm-email-change",
    response_model=MessageResponse,
    dependencies=[Depends(rate_limited("confirm-email-change", 20, HOUR))],
)
def confirm_email_change(
    body: ConfirmEmailChangeIn, session: SessionDep, settings: SettingsDep, sender: SenderDep
) -> MessageResponse:
    """Opened from the email link, so it works without being signed in."""
    account_service.confirm_email_change(session, body.token, settings=settings, sender=sender)
    return MessageResponse(message="Your email was changed. Sign in again with the new address.")


@router.post(
    "/delete",
    status_code=204,
    dependencies=[Depends(rate_limited("delete-account", 5, HOUR, by_session=True))],
    responses={403: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
)
def delete_account(
    body: DeleteAccountIn,
    user: CurrentUser,
    session: SessionDep,
    settings: SettingsDep,
    store: StoreDep,
    sender: SenderDep,
) -> Response:
    """Erase your personal data for good. Needs your password and the word DELETE."""
    if body.confirm.strip() != "DELETE":
        raise ConfirmationWordError("Type the word DELETE to confirm.")
    account_service.delete_account(
        session, store, user, password=body.password, otp=body.otp, sender=sender
    )
    response = Response(status_code=204)
    response.delete_cookie(**_cookie_args(settings))  # type: ignore[arg-type]
    return response
