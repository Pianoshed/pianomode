"""Job lifecycle: queued -> processing -> completed | failed | cancelled.

All transitions go through `_transition`, so an illegal change (e.g. completing a
cancelled job) can never be persisted.
"""

import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.core.errors import ConflictError, NotFoundError
from app.models.base import utcnow
from app.models.job import Job, JobStatus
from app.models.user import Role, User

ALLOWED: dict[JobStatus, frozenset[JobStatus]] = {
    JobStatus.QUEUED: frozenset({JobStatus.PROCESSING, JobStatus.CANCELLED}),
    JobStatus.PROCESSING: frozenset({JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED}),
    JobStatus.COMPLETED: frozenset(),
    JobStatus.FAILED: frozenset(),
    JobStatus.CANCELLED: frozenset(),
}


class InvalidJobTransitionError(ConflictError):
    code = "invalid_job_transition"


def create_job(
    session: Session,
    kind: str,
    payload: dict[str, Any] | None = None,
    *,
    user_id: uuid.UUID | None = None,
) -> Job:
    job = Job(
        kind=kind, payload=payload or {}, status=JobStatus.QUEUED, progress=0, user_id=user_id
    )
    session.add(job)
    session.commit()
    return job


def get_job(session: Session, job_id: uuid.UUID) -> Job:
    job = session.get(Job, job_id)
    if job is None:
        raise NotFoundError("Job not found", code="job_not_found")
    return job


def get_job_for_user(session: Session, job_id: uuid.UUID, user: User) -> Job:
    """Owner or admin only. Other users get the same 404 as a missing job."""
    job = get_job(session, job_id)
    if job.user_id != user.id and Role.ADMIN not in user.role_names:
        raise NotFoundError("Job not found", code="job_not_found")
    return job


def _transition(job: Job, target: JobStatus) -> None:
    if target not in ALLOWED[job.status]:
        raise InvalidJobTransitionError(
            f"Cannot move job from {job.status.value} to {target.value}",
            details={"from": job.status.value, "to": target.value},
        )
    job.status = target
    if target is JobStatus.PROCESSING:
        job.started_at = utcnow()
    if target in {JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED}:
        job.finished_at = utcnow()


def start_job(session: Session, job: Job) -> Job:
    _transition(job, JobStatus.PROCESSING)
    session.commit()
    return job


def update_progress(session: Session, job: Job, progress: int) -> Job:
    if job.status is not JobStatus.PROCESSING:
        raise InvalidJobTransitionError("Progress can only be set while processing")
    if not 0 <= progress <= 100:
        raise ValueError("progress must be between 0 and 100")
    job.progress = max(job.progress, progress)  # never moves backwards
    session.commit()
    return job


def complete_job(session: Session, job: Job, result: dict[str, Any]) -> Job:
    _transition(job, JobStatus.COMPLETED)
    job.progress = 100
    job.result = result
    session.commit()
    return job


def fail_job(session: Session, job: Job, code: str, message: str) -> Job:
    _transition(job, JobStatus.FAILED)
    job.error_code = code
    job.error_message = message[:2000]
    session.commit()
    return job


def cancel_job(session: Session, job: Job) -> Job:
    _transition(job, JobStatus.CANCELLED)
    session.commit()
    return job
