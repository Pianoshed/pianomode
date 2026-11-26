"""My Library: what people save (MIDI projects, audio analyses, chord progressions).

Everything is private to its owner; asking for someone else's item looks exactly like asking for
one that does not exist. Limits per person are in Settings (items, bytes per file, bytes in all,
size of the saved settings).
"""

import base64
import binascii
import json
import re
import uuid
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import AppError, ConflictError, NotFoundError, ServiceUnavailableError
from app.models.base import utcnow
from app.models.library import KINDS, LibraryItem
from app.models.user import User
from app.services.file_store import FileStore

MIDI_MAGIC = b"MThd"


class InvalidItemError(AppError):
    status_code = 422
    code = "invalid_item"


def clean_title(title: str) -> str:
    cleaned = " ".join(title.split())[:120]
    if not cleaned:
        raise InvalidItemError("Give it a name.", code="title_required")
    return cleaned


def clean_file_name(name: str | None) -> str | None:
    if not name:
        return None
    base = re.split(r"[\\/]", name)[-1]
    base = "".join(c for c in base if c.isprintable()).strip()[:200]
    return base or None


def _check_data(data: dict[str, object], settings: Settings) -> None:
    if len(json.dumps(data, separators=(",", ":")).encode()) > settings.library_max_data_bytes:
        raise InvalidItemError("This is too large to save.", code="data_too_large")


def usage(session: Session, user: User) -> tuple[int, int]:
    """(items saved, bytes of files saved)."""
    count, size = session.execute(
        select(func.count(LibraryItem.id), func.coalesce(func.sum(LibraryItem.file_size), 0)).where(
            LibraryItem.user_id == user.id
        )
    ).one()
    return int(count), int(size)


def create_item(
    session: Session,
    store: FileStore,
    settings: Settings,
    user: User,
    *,
    kind: str,
    title: str,
    data: dict[str, object],
    file_name: str | None,
    file_base64: str | None,
) -> LibraryItem:
    if kind not in KINDS:
        raise InvalidItemError("Unknown kind of item.", code="invalid_kind")
    title = clean_title(title)
    _check_data(data, settings)

    payload: bytes | None = None
    if kind == "midi":
        if not file_base64:
            raise InvalidItemError("A MIDI project needs its file.", code="file_required")
        try:
            payload = base64.b64decode(file_base64, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise InvalidItemError("The file could not be read.", code="bad_file") from exc
        if not payload.startswith(MIDI_MAGIC):
            raise InvalidItemError("That is not a MIDI file.", code="not_midi")
        if len(payload) > settings.library_max_file_bytes:
            mb = settings.library_max_file_bytes // (1024 * 1024)
            raise InvalidItemError(f"MIDI files up to {mb} MB can be saved.", code="file_too_large")
    elif file_base64:
        raise InvalidItemError("Only MIDI projects keep a file.", code="file_not_allowed")

    count, size = usage(session, user)
    if count >= settings.library_max_items:
        raise ConflictError(
            f"My Library holds up to {settings.library_max_items} items. Delete some to make room.",
            code="library_full",
        )
    if payload is not None and size + len(payload) > settings.library_max_total_bytes:
        mb = settings.library_max_total_bytes // (1024 * 1024)
        raise ConflictError(
            f"Your saved files would go over {mb} MB. Delete some to make room.",
            code="library_storage_full",
        )

    item = LibraryItem(
        user_id=user.id,
        kind=kind,
        title=title,
        data=data,
        file_name=clean_file_name(file_name) if payload is not None else None,
        file_size=len(payload) if payload is not None else 0,
    )
    session.add(item)
    session.flush()
    if payload is not None:
        try:
            store.write(store.key(user.id, item.id), payload)
        except OSError as exc:
            session.rollback()
            raise ServiceUnavailableError(
                "Could not save the file. Try again in a moment.", code="storage_unavailable"
            ) from exc
    session.commit()
    return item


def list_items(
    session: Session,
    user: User,
    kind: str | None = None,
    limit: int = 200,
    q: str | None = None,
) -> list[LibraryItem]:
    stmt = select(LibraryItem).where(LibraryItem.user_id == user.id)
    if kind:
        stmt = stmt.where(LibraryItem.kind == kind)
    if q and q.strip():
        escaped = q.strip().lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        stmt = stmt.where(func.lower(LibraryItem.title).like(f"%{escaped}%", escape="\\"))
    return list(
        session.scalars(stmt.order_by(LibraryItem.updated_at.desc()).limit(max(1, min(limit, 500))))
    )


def get_item(session: Session, user: User, item_id: uuid.UUID) -> LibraryItem:
    item = session.get(LibraryItem, item_id)
    if item is None or item.user_id != user.id:
        raise NotFoundError("That item is not in your library.", code="item_not_found")
    return item


def open_item(
    session: Session, user: User, item_id: uuid.UUID, now: datetime | None = None
) -> LibraryItem:
    item = get_item(session, user, item_id)
    item.last_opened_at = now or utcnow()
    session.commit()
    return item


def update_item(
    session: Session,
    settings: Settings,
    user: User,
    item_id: uuid.UUID,
    *,
    title: str | None,
    data: dict[str, object] | None,
) -> LibraryItem:
    item = get_item(session, user, item_id)
    if title is not None:
        item.title = clean_title(title)
    if data is not None:
        _check_data(data, settings)
        item.data = data
    item.updated_at = utcnow()
    session.commit()
    return item


def delete_item(session: Session, store: FileStore, user: User, item_id: uuid.UUID) -> None:
    item = get_item(session, user, item_id)
    key = store.key(user.id, item.id)
    session.delete(item)
    session.commit()
    store.delete(key)  # after the row is gone: a leftover file is harmless, a dangling row is not


def read_file(
    session: Session, store: FileStore, user: User, item_id: uuid.UUID
) -> tuple[LibraryItem, bytes]:
    item = get_item(session, user, item_id)
    payload = store.read(store.key(user.id, item.id)) if item.file_size > 0 else None
    if payload is None:
        raise NotFoundError("This item has no file.", code="file_not_found")
    return item, payload
