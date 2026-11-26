"""Practice tools. Scoring is deterministic and stateless; the browser sends what was played."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.deps import CurrentUser, SessionDep, require_access
from app.core.rate_limit import rate_limited
from app.schemas import practice as s
from app.schemas.errors import ErrorResponse
from app.services import practice_service

router = APIRouter(
    prefix="/api/v1/practice",
    tags=["practice"],
    dependencies=[
        Depends(require_access),
        Depends(rate_limited("practice", 120, 60, by_session=True)),
    ],
    responses={
        401: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
    },
)


@router.post("/score", response_model=s.ScoreResponse)
def score(body: s.ScoreRequest, session: SessionDep, user: CurrentUser) -> s.ScoreResponse:
    """Score a performance against explicit notes or a published movement.

    Reports hits, early/late, missed, near-miss and extra notes, timing figures, per-chord and
    per-hand results, and plain feedback. It is not a grade: it judges notes and timing only,
    and withholds a rush/drag tendency when too few notes were hit to say. With `save`, the
    server-computed result of a movement pass is added to the learner's history.
    """
    return s.ScoreResponse(**practice_service.score(session, body, user))


@router.post("/wait-results", response_model=s.AttemptOut, status_code=201)
def save_wait(body: s.WaitResultIn, session: SessionDep, user: CurrentUser) -> s.AttemptOut:
    """Keep the result of a wait-mode run (the music waited for every right note)."""
    row = practice_service.save_wait(session, user, body)
    return s.AttemptOut(**practice_service.attempt_out(row))


@router.get("/history", response_model=s.HistoryOut)
def history(
    session: SessionDep,
    user: CurrentUser,
    movement: Annotated[str | None, Query(max_length=80)] = None,
) -> s.HistoryOut:
    """The learner's own recent results and per-movement progress. Nobody else can read them."""
    return s.HistoryOut(**practice_service.history(session, user, movement))


@router.delete("/attempts/{attempt_id}", status_code=204)
def delete_attempt(attempt_id: uuid.UUID, session: SessionDep, user: CurrentUser) -> None:
    practice_service.delete_attempt(session, user, attempt_id)


@router.delete("/history")
def delete_history(session: SessionDep, user: CurrentUser) -> dict[str, int]:
    """Delete every saved practice result of the signed-in learner."""
    return {"deleted": practice_service.delete_history(session, user)}
