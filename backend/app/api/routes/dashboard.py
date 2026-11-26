from fastapi import APIRouter, Depends

from app.api.deps import CurrentUser, SessionDep
from app.core.rate_limit import rate_limited
from app.schemas.dashboard import DashboardOut
from app.schemas.errors import ErrorResponse
from app.services import dashboard_service

router = APIRouter(
    prefix="/api/v1/dashboard",
    tags=["dashboard"],
    dependencies=[Depends(rate_limited("dashboard", 120, 60, by_session=True))],
    responses={401: {"model": ErrorResponse}},
)


@router.get("", response_model=DashboardOut)
def dashboard(user: CurrentUser, session: SessionDep) -> DashboardOut:
    """Needs sign-in only, so the page still works when a plan has ended."""
    return DashboardOut(**dashboard_service.build_dashboard(session, user))
