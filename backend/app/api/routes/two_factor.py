"""Turning two-factor sign-in on and off. See services/two_factor_service.py."""

from fastapi import APIRouter, Depends

from app.api.deps import CurrentUser, SessionDep
from app.core.rate_limit import rate_limited
from app.schemas.errors import ErrorResponse
from app.schemas.two_factor import CodeIn, DisableIn, RecoveryCodesOut, SetupOut
from app.services import two_factor_service as tf

router = APIRouter(
    prefix="/api/v1/auth/2fa",
    tags=["two-factor"],
    dependencies=[Depends(rate_limited("two-factor", 20, 900, by_session=True))],
    responses={401: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
)


@router.post("/setup", response_model=SetupOut)
def setup(user: CurrentUser, session: SessionDep) -> SetupOut:
    """Make a key for an authenticator app. Nothing changes until the code is confirmed."""
    s = tf.begin_setup(session, user)
    return SetupOut(secret=s.secret, uri=s.uri)


@router.post("/enable", response_model=RecoveryCodesOut)
def enable(body: CodeIn, user: CurrentUser, session: SessionDep) -> RecoveryCodesOut:
    """Confirm with a code from the app. The recovery codes are shown here once."""
    return RecoveryCodesOut(recovery_codes=tf.enable(session, user, body.code))


@router.post("/disable", status_code=204)
def disable(body: DisableIn, user: CurrentUser, session: SessionDep) -> None:
    tf.disable(session, user, body.password, body.code)


@router.post("/recovery-codes", response_model=RecoveryCodesOut)
def new_codes(body: CodeIn, user: CurrentUser, session: SessionDep) -> RecoveryCodesOut:
    """Replace the recovery codes (the old ones stop working)."""
    return RecoveryCodesOut(recovery_codes=tf.new_recovery_codes(session, user, body.code))
