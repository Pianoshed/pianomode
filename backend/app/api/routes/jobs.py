import uuid

from fastapi import APIRouter

from app.api.deps import CurrentUser, SessionDep
from app.schemas.errors import ErrorResponse
from app.schemas.job import JobRead
from app.services import job_service

router = APIRouter(prefix="/api/v1/jobs", tags=["jobs"])


@router.get(
    "/{job_id}",
    response_model=JobRead,
    responses={401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
def read_job(job_id: uuid.UUID, user: CurrentUser, session: SessionDep) -> JobRead:
    return JobRead.model_validate(job_service.get_job_for_user(session, job_id, user))


@router.post(
    "/{job_id}/cancel",
    response_model=JobRead,
    responses={404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
)
def cancel_job(job_id: uuid.UUID, user: CurrentUser, session: SessionDep) -> JobRead:
    job = job_service.get_job_for_user(session, job_id, user)
    return JobRead.model_validate(job_service.cancel_job(session, job))
