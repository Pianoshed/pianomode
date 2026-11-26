"""Chord-movement library.

Learners (any signed-in user) read published movements. Educators and admins manage them under
`/api/v1/admin/movements`; those checks are enforced here on the server.
"""

import uuid
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query

from app.api.deps import CurrentUser, SessionDep, require_access, require_roles
from app.core.rate_limit import rate_limited
from app.models.movement import Movement
from app.models.user import Role
from app.schemas import movement as s
from app.schemas.errors import ErrorResponse
from app.services import movement_service as svc
from music_theory import movements as mv

MINUTE = 60
_common: dict[int | str, dict[str, Any]] = {
    401: {"model": ErrorResponse},
    404: {"model": ErrorResponse},
    422: {"model": ErrorResponse},
}
heavy = [Depends(rate_limited("movements_heavy", 30, MINUTE, by_session=True))]

router = APIRouter(
    prefix="/api/v1/movements",
    tags=["movements"],
    dependencies=[
        Depends(require_access),
        Depends(rate_limited("movements", 300, MINUTE, by_session=True)),
    ],
    responses=_common,
)
admin = APIRouter(
    prefix="/api/v1/admin/movements",
    tags=["movements-admin"],
    dependencies=[
        Depends(require_roles(Role.EDUCATOR, Role.ADMIN)),
        Depends(rate_limited("movements_admin", 300, MINUTE, by_session=True)),
    ],
    responses={**_common, 403: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
)


# learners -----------------------------------------------------------------------------------


@router.get("", response_model=s.MovementListOut)
def list_movements(
    session: SessionDep,
    q: Annotated[str | None, Query(max_length=60)] = None,
    level: Annotated[s.Level | None, Query()] = None,
    tag: Annotated[str | None, Query(max_length=32)] = None,
    mode: Annotated[Literal["major", "minor"] | None, Query()] = None,
) -> s.MovementListOut:
    """Published movements, optionally filtered. Learners never see drafts."""
    items = svc.published_list(session, q=q, level=level, tag=tag, mode=mode)
    return s.MovementListOut(items=[s.MovementSummaryOut(**i) for i in items], total=len(items))


@router.get("/{slug}", response_model=s.MovementDetailOut, dependencies=heavy)
def read_movement(
    slug: str,
    session: SessionDep,
    key: Annotated[str | None, Query(max_length=3, description="Transpose to this tonic.")] = None,
) -> s.MovementDetailOut:
    """A published movement with all its levels. Without `key` this is the frozen snapshot that
    was reviewed; with `key` it is built now in that key (`live: true`)."""
    return s.MovementDetailOut(**svc.published_detail(session, slug[:80], key))


# content admin ------------------------------------------------------------------------------


def _admin_out(row: Movement) -> s.AdminMovementOut:
    return s.AdminMovementOut(
        id=str(row.id), slug=row.slug, name=row.name, status=row.status,
        revision=row.revision, mode=row.mode, definition=row.definition,
        history=[s.HistoryOut(**h) for h in row.history],
        allowed_transitions=list(mv.TRANSITIONS[row.status]),
        published_at=row.published_at.isoformat() if row.published_at else None,
        updated_at=row.updated_at.isoformat(),
    )  # fmt: skip


@admin.get("", response_model=s.AdminListOut)
def admin_list(
    session: SessionDep,
    status: Annotated[s.Status | None, Query()] = None,
    q: Annotated[str | None, Query(max_length=60)] = None,
) -> s.AdminListOut:
    rows = svc.admin_list(session, status, q)
    return s.AdminListOut(
        items=[
            s.AdminMovementSummaryOut(
                id=str(r.id), slug=r.slug, name=r.name, status=r.status,
                revision=r.revision, mode=r.mode, tags=list(r.definition.get("tags", [])),
                updated_at=r.updated_at.isoformat(),
            )
            for r in rows
        ],
        total=len(rows),
    )  # fmt: skip


@admin.post("", response_model=s.AdminMovementOut, status_code=201, dependencies=heavy)
def create_movement(
    body: s.MovementDefinitionIn, session: SessionDep, user: CurrentUser
) -> s.AdminMovementOut:
    return _admin_out(svc.create(session, body, user))


@admin.post("/preview", response_model=s.PreviewOut, dependencies=heavy)
def preview_unsaved(body: s.MovementDefinitionIn, user: CurrentUser) -> s.PreviewOut:
    """Build a definition without saving it: every level, plus what would block publication."""
    return s.PreviewOut(**svc.preview_definition(body, user))


@admin.get("/{movement_id}", response_model=s.AdminMovementOut)
def admin_read(movement_id: uuid.UUID, session: SessionDep) -> s.AdminMovementOut:
    return _admin_out(svc.admin_get(session, movement_id))


@admin.put("/{movement_id}", response_model=s.AdminMovementOut, dependencies=heavy)
def update_movement(
    movement_id: uuid.UUID, body: s.MovementUpdateIn, session: SessionDep, user: CurrentUser
) -> s.AdminMovementOut:
    return _admin_out(svc.update(session, movement_id, body, user))


@admin.get("/{movement_id}/preview", response_model=s.PreviewOut, dependencies=heavy)
def preview_stored(movement_id: uuid.UUID, session: SessionDep) -> s.PreviewOut:
    return s.PreviewOut(**svc.preview_stored(session, movement_id))


@admin.post("/{movement_id}/validate", response_model=s.ValidationOut, dependencies=heavy)
def validate_movement(movement_id: uuid.UUID, session: SessionDep) -> s.ValidationOut:
    return s.ValidationOut(**svc.validation_report(session, movement_id))


@admin.post("/{movement_id}/status", response_model=s.AdminMovementOut, dependencies=heavy)
def change_status(
    movement_id: uuid.UUID, body: s.StatusChangeIn, session: SessionDep, user: CurrentUser
) -> s.AdminMovementOut:
    """Submit, approve, publish, unpublish, archive or restore. Publishing needs `approved` and
    passes the engine's publication checks; every change is written to the history."""
    return _admin_out(svc.change_status(session, movement_id, body, user))
