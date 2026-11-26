"""Administrator-defined scales. Admin only; the checks are enforced here on the server.

Published scales appear in `GET /api/v1/theory/scales` and can be generated with
`POST /api/v1/theory/scales/generate`.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.deps import CurrentUser, SessionDep, require_roles
from app.core.rate_limit import rate_limited
from app.models.custom_scale import CustomScale
from app.models.user import Role
from app.schemas import scale_admin as s
from app.schemas.errors import ErrorResponse
from app.services import scale_service as svc

MINUTE = 60
router = APIRouter(
    prefix="/api/v1/admin/scales",
    tags=["scales-admin"],
    dependencies=[
        Depends(require_roles(Role.ADMIN)),
        Depends(rate_limited("scales_admin", 120, MINUTE, by_session=True)),
    ],
    responses={
        401: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
    },
)


def _out(row: CustomScale) -> s.AdminScaleOut:
    return s.AdminScaleOut(
        id=str(row.id), scale_id=row.scale_id, name=row.name, status=row.status,
        revision=row.revision, definition=dict(row.definition),
        history=[s.ScaleHistoryOut(**h) for h in row.history],
        allowed_transitions=list(svc.TRANSITIONS[row.status]),
        published_at=row.published_at.isoformat() if row.published_at else None,
        updated_at=row.updated_at.isoformat(),
    )  # fmt: skip


@router.get("", response_model=s.AdminScaleListOut)
def list_scales(
    session: SessionDep, status: Annotated[s.ScaleStatus | None, Query()] = None
) -> s.AdminScaleListOut:
    rows = svc.admin_list(session, status)
    items: list[s.AdminScaleSummaryOut] = []
    for r in rows:
        items.append(
            s.AdminScaleSummaryOut(
                id=str(r.id), scale_id=r.scale_id, name=r.name, status=r.status,
                revision=r.revision, size=len(r.definition.get("formula", [])),
                updated_at=r.updated_at.isoformat(),
            )
        )  # fmt: skip
    return s.AdminScaleListOut(items=items, total=len(items))


@router.post("", response_model=s.AdminScaleOut, status_code=201)
def create_scale(
    body: s.ScaleDefinitionIn, session: SessionDep, user: CurrentUser
) -> s.AdminScaleOut:
    return _out(svc.create(session, body, user))


@router.post("/preview", response_model=s.ScalePreviewOut)
def preview(body: s.ScaleDefinitionIn, session: SessionDep) -> s.ScalePreviewOut:
    """Check an unsaved definition: spelling on all twelve roots, look-alike scales, and what
    would block publication."""
    return svc.preview_definition(session, body)


@router.get("/{row_id}", response_model=s.AdminScaleOut)
def read_scale(row_id: uuid.UUID, session: SessionDep) -> s.AdminScaleOut:
    return _out(svc.admin_get(session, row_id))


@router.put("/{row_id}", response_model=s.AdminScaleOut)
def update_scale(
    row_id: uuid.UUID, body: s.ScaleUpdateIn, session: SessionDep, user: CurrentUser
) -> s.AdminScaleOut:
    return _out(svc.update(session, row_id, body, user))


@router.post("/{row_id}/status", response_model=s.AdminScaleOut)
def change_status(
    row_id: uuid.UUID, body: s.ScaleStatusIn, session: SessionDep, user: CurrentUser
) -> s.AdminScaleOut:
    """Publish, unpublish, archive or restore. Publishing is refused when the id or an alias
    clashes with a built-in or already published scale."""
    return _out(svc.change_status(session, row_id, body, user))
