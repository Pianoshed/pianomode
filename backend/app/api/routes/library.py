"""My Library. Reading, downloading and deleting only need sign-in, so someone whose plan has
ended can still get at (and tidy) their own work. Saving needs access, like the tools that make
the work."""

import re
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Response

from app.api.deps import CurrentUser, SessionDep, SettingsDep, require_access
from app.core.rate_limit import rate_limited
from app.models.library import LibraryItem
from app.models.user import User
from app.schemas import library as s
from app.schemas.errors import ErrorResponse
from app.services import library_service
from app.services.file_store import FileStore, get_file_store

StoreDep = Annotated[FileStore, Depends(get_file_store)]
AccessUser = Annotated[User, Depends(require_access)]

router = APIRouter(
    prefix="/api/v1/library",
    tags=["library"],
    dependencies=[Depends(rate_limited("library", 240, 60, by_session=True))],
    responses={401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)


def _out(i: LibraryItem) -> s.ItemOut:
    return s.ItemOut(
        id=i.id,
        kind=i.kind,
        title=i.title,
        file_name=i.file_name,
        file_size=i.file_size,
        created_at=i.created_at,
        updated_at=i.updated_at,
        last_opened_at=i.last_opened_at,
    )


def _detail(i: LibraryItem) -> s.ItemDetail:
    return s.ItemDetail(**_out(i).model_dump(), data=i.data)


@router.get("", response_model=s.ListOut)
def list_items(
    user: CurrentUser,
    session: SessionDep,
    settings: SettingsDep,
    kind: s.Kind | None = None,
    q: str | None = None,
) -> s.ListOut:
    count, size = library_service.usage(session, user)
    return s.ListOut(
        items=[_out(i) for i in library_service.list_items(session, user, kind, q=q)],
        usage=s.UsageOut(
            items=count,
            max_items=settings.library_max_items,
            bytes=size,
            max_bytes=settings.library_max_total_bytes,
        ),
    )


@router.post(
    "",
    response_model=s.ItemDetail,
    status_code=201,
    responses={
        402: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
    },
)
def create_item(
    body: s.CreateItemIn,
    user: AccessUser,
    session: SessionDep,
    settings: SettingsDep,
    store: StoreDep,
) -> s.ItemDetail:
    item = library_service.create_item(
        session,
        store,
        settings,
        user,
        kind=body.kind,
        title=body.title,
        data=body.data,
        file_name=body.file_name,
        file_base64=body.file_base64,
    )
    return _detail(item)


@router.get("/{item_id}", response_model=s.ItemDetail)
def open_item(item_id: uuid.UUID, user: CurrentUser, session: SessionDep) -> s.ItemDetail:
    """The item with its saved settings. Opening it also counts as "recently opened"."""
    return _detail(library_service.open_item(session, user, item_id))


@router.patch(
    "/{item_id}",
    response_model=s.ItemDetail,
    responses={402: {"model": ErrorResponse}, 422: {"model": ErrorResponse}},
)
def update_item(
    item_id: uuid.UUID,
    body: s.UpdateItemIn,
    user: AccessUser,
    session: SessionDep,
    settings: SettingsDep,
) -> s.ItemDetail:
    item = library_service.update_item(
        session, settings, user, item_id, title=body.title, data=body.data
    )
    return _detail(item)


@router.delete("/{item_id}", status_code=204)
def delete_item(
    item_id: uuid.UUID, user: CurrentUser, session: SessionDep, store: StoreDep
) -> None:
    library_service.delete_item(session, store, user, item_id)


@router.get("/{item_id}/file")
def download_file(
    item_id: uuid.UUID, user: CurrentUser, session: SessionDep, store: StoreDep
) -> Response:
    item, payload = library_service.read_file(session, store, user, item_id)
    name = re.sub(r"[^A-Za-z0-9._ -]", "_", item.file_name or "project.mid") or "project.mid"
    return Response(
        content=payload,
        media_type="audio/midi",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )
