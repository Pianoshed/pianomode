"""Theory lessons. Content is authored data; examples are built by the theory engine."""

from typing import Annotated

from fastapi import APIRouter, Depends, Path

from app.api.deps import CurrentUser, SessionDep, require_access
from app.core.rate_limit import rate_limited
from app.schemas import lesson as s
from app.schemas.errors import ErrorResponse
from app.services import lesson_service

router = APIRouter(
    prefix="/api/v1/lessons",
    tags=["lessons"],
    dependencies=[
        Depends(require_access),
        Depends(rate_limited("lessons", 300, 60, by_session=True)),
    ],
    responses={401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)


@router.get("", response_model=s.LessonListOut)
def list_lessons(user: CurrentUser, session: SessionDep) -> s.LessonListOut:
    """Every lesson in curriculum order, with the signed-in learner's practice status."""
    return s.LessonListOut(
        items=[s.LessonSummaryOut(**i) for i in lesson_service.list_lessons(session, user)]
    )


@router.get("/{lesson_id}", response_model=s.LessonDetailOut)
def read_lesson(
    lesson_id: Annotated[str, Path(max_length=64)], user: CurrentUser, session: SessionDep
) -> s.LessonDetailOut:
    """One lesson: objectives, explanation, engine-built examples and practice progress."""
    return s.LessonDetailOut(**lesson_service.lesson_detail(session, user, lesson_id))
