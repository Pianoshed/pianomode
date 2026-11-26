"""Lesson authoring for educators and admins; the checks are enforced here on the server.

Published lessons join the learner curriculum (`GET /api/v1/lessons`). Built-in lessons are read
only.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.deps import CurrentUser, SessionDep, require_roles
from app.core.rate_limit import rate_limited
from app.models.custom_lesson import CustomLesson
from app.models.user import Role
from app.schemas import lesson_admin as s
from app.schemas.errors import ErrorResponse
from app.services import lesson_admin_service as svc
from music_theory import movements as mv

MINUTE = 60
heavy = [Depends(rate_limited("lessons_admin_heavy", 60, MINUTE, by_session=True))]
router = APIRouter(
    prefix="/api/v1/admin/lessons",
    tags=["lessons-admin"],
    dependencies=[
        Depends(require_roles(Role.EDUCATOR, Role.ADMIN)),
        Depends(rate_limited("lessons_admin", 300, MINUTE, by_session=True)),
    ],
    responses={
        401: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
    },
)


def _out(row: CustomLesson) -> s.AdminLessonOut:
    return s.AdminLessonOut(
        id=str(row.id), lesson_id=row.lesson_id, title=row.title, level=row.level,
        status=row.status, revision=row.revision, definition=dict(row.definition),
        history=[s.LessonHistoryOut(**h) for h in row.history],
        allowed_transitions=list(mv.TRANSITIONS[row.status]),
        published_at=row.published_at.isoformat() if row.published_at else None,
        updated_at=row.updated_at.isoformat(),
    )  # fmt: skip


@router.get("", response_model=s.AdminLessonListOut)
def list_lessons(
    session: SessionDep,
    status: Annotated[s.LessonStatus | None, Query()] = None,
    q: Annotated[str | None, Query(max_length=60)] = None,
) -> s.AdminLessonListOut:
    rows = svc.admin_list(session, status, q)
    items = [
        s.AdminLessonSummaryOut(
            id=str(r.id), lesson_id=r.lesson_id, title=r.title, level=r.level,
            status=r.status, revision=r.revision, updated_at=r.updated_at.isoformat(),
        )
        for r in rows
    ]  # fmt: skip
    return s.AdminLessonListOut(items=items, total=len(items))


@router.post("", response_model=s.AdminLessonOut, status_code=201, dependencies=heavy)
def create_lesson(
    body: s.LessonDefinitionIn, session: SessionDep, user: CurrentUser
) -> s.AdminLessonOut:
    return _out(svc.create(session, body, user))


@router.post("/preview", response_model=s.LessonPreviewOut, dependencies=heavy)
def preview_unsaved(body: s.LessonDefinitionIn, session: SessionDep) -> s.LessonPreviewOut:
    """Build a lesson without saving it: what a learner would see, plus what blocks publication."""
    return s.LessonPreviewOut(**svc.preview_definition(session, body))


@router.get("/{row_id}", response_model=s.AdminLessonOut)
def read_lesson(row_id: uuid.UUID, session: SessionDep) -> s.AdminLessonOut:
    return _out(svc.admin_get(session, row_id))


@router.put("/{row_id}", response_model=s.AdminLessonOut, dependencies=heavy)
def update_lesson(
    row_id: uuid.UUID, body: s.LessonUpdateIn, session: SessionDep, user: CurrentUser
) -> s.AdminLessonOut:
    return _out(svc.update(session, row_id, body, user))


@router.get("/{row_id}/preview", response_model=s.LessonPreviewOut, dependencies=heavy)
def preview_stored(row_id: uuid.UUID, session: SessionDep) -> s.LessonPreviewOut:
    return s.LessonPreviewOut(**svc.preview_stored(session, row_id))


@router.post("/{row_id}/status", response_model=s.AdminLessonOut, dependencies=heavy)
def change_status(
    row_id: uuid.UUID, body: s.LessonStatusIn, session: SessionDep, user: CurrentUser
) -> s.AdminLessonOut:
    """Submit, approve, publish, unpublish, archive or restore. Publishing needs `approved`, an
    example and every prerequisite live; every change is written to the history."""
    return _out(svc.change_status(session, row_id, body, user))
