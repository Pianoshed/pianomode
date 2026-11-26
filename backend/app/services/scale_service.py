"""Administrator-defined scales: storage, validation, lifecycle and the live registry.

Rules enforced here:
- Only admins reach these functions (see routes).
- A definition is validated by the engine (`music_theory.scales`) before it is saved; a definition
  that cannot be built is refused, not stored.
- Built-in scale ids and aliases are protected: a custom scale can neither replace nor shadow
  them, and two published scales cannot share an id or alias.
- Only `published` scales reach the theory endpoints. A published scale cannot be edited;
  unpublish it first. Edits carry their starting revision, and a stale one is a conflict.
- Custom scales extend the scale list and generator only. Key detection, generated exercises and
  lessons keep using the built-in major/minor/mode definitions.
"""

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import ConflictError, NotFoundError
from app.models.base import utcnow
from app.models.custom_scale import CustomScale
from app.models.user import User
from app.schemas import scale_admin as s
from music_theory.errors import TheoryError
from music_theory.scales import (
    ScaleDefinition,
    ScaleRegistry,
    default_registry,
    make_scale,
    parse_definition,
)

TRANSITIONS: dict[str, tuple[str, ...]] = {
    "draft": ("published", "archived"),
    "published": ("draft", "archived"),
    "archived": ("draft",),
}
MAX_HISTORY = 50
MAX_ROWS = 500
_PREVIEW_ROOTS = ("C", "Db", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B")


def _actor(user: User) -> str:
    return user.display_name or "unknown"


def _raw(data: s.ScaleDefinitionIn) -> dict[str, Any]:
    return {
        "id": data.id,
        "name": data.name.strip(),
        "family": data.family.strip(),
        "formula": list(data.formula),
        "descending": None if data.descending is None else list(data.descending),
        "aliases": [a.strip() for a in data.aliases],
        "description": data.description.strip(),
    }


def _build(raw: dict[str, Any]) -> ScaleDefinition:
    return parse_definition(raw)  # raises ScaleDefinitionError (422) when invalid


def _entry(row: CustomScale, user: User, action: str, note: str = "", **st: str | None) -> None:
    entry = {
        "revision": row.revision, "at": utcnow().isoformat(), "actor": _actor(user),
        "action": action, "note": note,
        "from_status": st.get("from_status"), "to_status": st.get("to_status"),
    }  # fmt: skip
    row.history = [*row.history, entry][-MAX_HISTORY:]  # reassign: JSON is not change-tracked


def _get(session: Session, scale_row_id: uuid.UUID) -> CustomScale:
    row = session.get(CustomScale, scale_row_id)
    if row is None:
        raise NotFoundError("Scale not found.", code="scale_not_found")
    return row


def _published_definitions(
    session: Session, *, exclude: uuid.UUID | None = None
) -> list[ScaleDefinition]:
    out: list[ScaleDefinition] = []
    rows = session.scalars(
        select(CustomScale).where(CustomScale.status == "published").order_by(CustomScale.scale_id)
    ).all()
    for row in rows:
        if row.id == exclude:
            continue
        try:
            out.append(_build(row.definition))
        except TheoryError:  # a bad row must never break the theory endpoints
            continue
    return out


def live_registry(session: Session) -> ScaleRegistry:
    """Built-in scales plus every published custom scale. Built-ins win any clash."""
    registry = default_registry().copy()
    for d in _published_definitions(session):
        try:
            registry.register(d)
        except TheoryError:
            continue
    return registry


def builtin_ids() -> set[str]:
    return set(default_registry().ids())


# ------------------------------------------------------------------ checks


def _clashes(session: Session, d: ScaleDefinition, exclude: uuid.UUID | None) -> list[str]:
    """Why `d` cannot be published right now: reuse of a built-in or published id or alias."""
    registry = default_registry().copy()
    for other in _published_definitions(session, exclude=exclude):
        try:
            registry.register(other)
        except TheoryError:
            continue
    try:
        registry.register(d)
    except TheoryError as exc:
        return [exc.message]
    return []


def _same_pattern(d: ScaleDefinition) -> list[str]:
    pattern = tuple(i.semitones for i in d.formula)
    return [
        b.id for b in default_registry().all() if tuple(i.semitones for i in b.formula) == pattern
    ]


def preview_definition(
    session: Session, data: s.ScaleDefinitionIn, *, exclude: uuid.UUID | None = None
) -> s.ScalePreviewOut:
    d = _build(_raw(data))
    roots: list[s.RootSpellingOut] = []
    for r in _PREVIEW_ROOTS:
        try:
            roots.append(
                s.RootSpellingOut(
                    root=r,
                    notes=[str(n) for n in make_scale(r, d.id, _single(d)).notes()],
                    problem=None,
                )
            )
        except TheoryError as exc:
            roots.append(s.RootSpellingOut(root=r, notes=None, problem=exc.message))
    blockers = _clashes(session, d, exclude)
    warnings: list[str] = []
    same = _same_pattern(d)
    if same:
        warnings.append(
            "This has the same pitch pattern as " + ", ".join(same) + ". Is a second name needed?"
        )
    failed = [r.root for r in roots if r.notes is None]
    if failed:
        warnings.append(
            "Cannot be spelled on " + ", ".join(failed) + " without double accidentals; "
            "those roots will report an error."
        )
    if d.size >= 9:
        warnings.append("Large scales are hard to teach; check the formula is intended.")
    return s.ScalePreviewOut(
        scale_id=d.id, name=d.name, size=d.size, semitones=[i.semitones for i in d.formula],
        roots=roots, same_pattern_as=same, blockers=blockers, warnings=warnings,
    )  # fmt: skip


def _single(d: ScaleDefinition) -> ScaleRegistry:
    return ScaleRegistry([d])


# ------------------------------------------------------------------ lifecycle


def _out_taken(session: Session, scale_id: str, exclude: uuid.UUID | None = None) -> None:
    if scale_id in builtin_ids():
        raise ConflictError(
            f"{scale_id!r} is a built-in scale and cannot be redefined.", code="scale_id_builtin"
        )
    stmt = select(CustomScale.id).where(CustomScale.scale_id == scale_id)
    found = session.scalar(stmt)
    if found is not None and found != exclude:
        raise ConflictError(f"A scale with id {scale_id!r} already exists.", code="scale_id_taken")


def create(session: Session, data: s.ScaleDefinitionIn, user: User) -> CustomScale:
    raw = _raw(data)
    d = _build(raw)
    _out_taken(session, d.id)
    row = CustomScale(
        scale_id=d.id, name=d.name, status="draft", revision=1, definition=raw, history=[],
        created_by=user.id,
    )  # fmt: skip
    _entry(row, user, "create", to_status="draft")
    session.add(row)
    session.commit()
    return row


def update(
    session: Session, scale_row_id: uuid.UUID, data: s.ScaleUpdateIn, user: User
) -> CustomScale:
    row = _get(session, scale_row_id)
    if row.status == "published":
        raise ConflictError(
            "A published scale cannot be edited. Unpublish it first, edit, then publish again.",
            code="scale_published",
        )
    if row.status == "archived":
        raise ConflictError("Restore an archived scale before editing it.", code="scale_archived")
    if data.revision != row.revision:
        raise ConflictError(
            "Someone else changed this scale. Reload it and apply your edit again.",
            code="revision_conflict",
            details={"current_revision": row.revision},
        )
    raw = _raw(s.ScaleDefinitionIn(**data.model_dump(exclude={"revision"})))
    d = _build(raw)
    _out_taken(session, d.id, exclude=row.id)
    row.revision += 1
    row.scale_id, row.name, row.definition = d.id, d.name, raw
    _entry(row, user, "edit")
    session.commit()
    return row


def change_status(
    session: Session, scale_row_id: uuid.UUID, data: s.ScaleStatusIn, user: User
) -> CustomScale:
    row = _get(session, scale_row_id)
    if data.to not in TRANSITIONS[row.status]:
        raise ConflictError(
            f"A {row.status} scale cannot become {data.to}.",
            code="invalid_transition",
            details={"allowed": list(TRANSITIONS[row.status])},
        )
    if data.to == "published":
        blockers = _clashes(session, _build(row.definition), row.id)
        if blockers:
            raise ConflictError(
                "This scale is not ready to publish: " + " ".join(blockers[:3]),
                code="publication_blocked",
                details={"blockers": blockers},
            )
        row.published_at = utcnow()
    previous = row.status
    row.status = data.to
    _entry(row, user, "status", data.note, from_status=previous, to_status=data.to)
    session.commit()
    return row


def admin_get(session: Session, scale_row_id: uuid.UUID) -> CustomScale:
    return _get(session, scale_row_id)


def admin_list(session: Session, status: str | None) -> list[CustomScale]:
    stmt = select(CustomScale).order_by(CustomScale.scale_id).limit(MAX_ROWS)
    if status:
        stmt = stmt.where(CustomScale.status == status)
    return list(session.scalars(stmt))
