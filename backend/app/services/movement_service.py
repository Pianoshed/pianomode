"""Chord-movement library: storage, lifecycle and learner views.

Rules enforced here (not in the UI):
- Only educators and admins reach the admin functions (see routes).
- A movement must be *approved* before it can be published, and publication runs the engine's
  publication checks over every level.
- Published content is a frozen snapshot. A published movement cannot be edited; unpublish it
  first, so learners never see unreviewed changes.
- Editing after review sends the movement back to draft.
- Edits carry the revision they started from; a stale revision is a conflict, not an overwrite.
"""

import uuid
from collections.abc import Collection
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import ConflictError, NotFoundError
from app.models.base import utcnow
from app.models.movement import Movement
from app.models.user import User
from app.schemas import movement as s
from music_theory import movements as mv
from music_theory.errors import TheoryError
from music_theory.notes import parse_note_name
from music_theory.validation import parse_key

MAX_ROWS = 500


def _actor(user: User) -> str:
    return user.display_name or "unknown"


def _definition(data: s.MovementDefinitionIn, user: User) -> mv.MovementDefinition:
    ts = data.time_signature
    d = mv.definition_from_dict(
        {
            "name": data.name.strip(),
            "key": {"tonic": data.key.tonic, "mode": data.key.mode},
            "template_id": data.template_id,
            "custom_chords": [c.model_dump() for c in data.custom_chords],
            "tempo": data.tempo,
            "time_signature": [ts[0], ts[1]],
            "tags": [t.strip() for t in data.tags],
            "theory_explanation": data.theory_explanation,
            "practice": dict(data.practice),
            "variations": data.variations,
            "levels": data.levels,
            "author": (data.author or "").strip() or _actor(user),
            "source": data.source,
        }
    )
    mv.check_definition(d)
    return d


def _search_text(d: mv.MovementDefinition) -> str:
    parts = [d.name, d.template_id or "", str(d.key), d.key.mode, *d.tags, d.author or ""]
    return " ".join(parts).lower()


def _unique_slug(session: Session, name: str) -> str:
    base = mv.make_slug(name)
    slug, n = base, 1
    while session.scalar(select(Movement.id).where(Movement.slug == slug)) is not None:
        n += 1
        slug = f"{base[: 80 - len(str(n)) - 1]}-{n}"
    return slug


def _entry(row: Movement, user: User, action: str, note: str = "", **status: str | None) -> None:
    entry = mv.HistoryEntry(
        row.revision, mv.now_iso(), _actor(user), action, note,
        status.get("from_status"), status.get("to_status"),
    )  # fmt: skip
    history = [*row.history, entry.to_dict()][-mv.MAX_HISTORY :]
    row.history = history  # reassign: SQLAlchemy does not see in-place JSON changes


def _get(session: Session, movement_id: uuid.UUID) -> Movement:
    row = session.get(Movement, movement_id)
    if row is None:
        raise NotFoundError("Movement not found.", code="movement_not_found")
    return row


# ------------------------------------------------------------------ admin


def _publication_blocked(blockers: list[str]) -> ConflictError:
    return ConflictError(
        "This movement is not ready to publish: "
        + " ".join(blockers[:3])
        + (f" (and {len(blockers) - 3} more)" if len(blockers) > 3 else ""),
        code="publication_blocked",
        details={"blockers": blockers},
    )


def create(session: Session, data: s.MovementDefinitionIn, user: User) -> Movement:
    d = _definition(data, user)
    mv.build_movement(d)  # a definition that cannot be built is refused, not saved
    row = Movement(
        slug=_unique_slug(session, d.name), name=d.name, status="draft", revision=1,
        mode=d.key.mode, definition=mv.definition_to_dict(d), snapshot=None, history=[],
        search_text=_search_text(d), created_by=user.id,
    )  # fmt: skip
    _entry(row, user, "create", to_status="draft")
    session.add(row)
    session.commit()
    return row


def update(
    session: Session, movement_id: uuid.UUID, data: s.MovementUpdateIn, user: User
) -> Movement:
    row = _get(session, movement_id)
    if row.status == "published":
        raise ConflictError(
            "A published movement cannot be edited. Unpublish it first, edit, then publish again.",
            code="movement_published",
        )
    if row.status == "archived":
        raise ConflictError(
            "Restore an archived movement before editing it.", code="movement_archived"
        )
    if data.revision != row.revision:
        raise ConflictError(
            "Someone else changed this movement. Reload it and apply your edit again.",
            code="revision_conflict",
            details={"current_revision": row.revision},
        )
    d = _definition(s.MovementDefinitionIn(**data.model_dump(exclude={"revision"})), user)
    mv.build_movement(d)
    previous = row.status
    row.revision += 1
    row.name, row.mode = d.name, d.key.mode
    row.definition = mv.definition_to_dict(d)
    row.search_text = _search_text(d)
    row.snapshot = None
    note = ""
    if previous in ("under_review", "approved"):
        row.status = "draft"
        note = f"Edited after being {previous.replace('_', ' ')}; returned to draft."
    _entry(row, user, "edit", note, from_status=previous, to_status=row.status)
    session.commit()
    return row


def preview_definition(data: s.MovementDefinitionIn, user: User) -> dict[str, Any]:
    d = _definition(data, user)
    return _preview(mv.build_movement(d))


def _preview(built: mv.BuiltMovement) -> dict[str, Any]:
    blockers = mv.publication_blockers(built)
    warnings = sorted({w for v in built.versions for w in v.validation_warnings})
    return {
        "movement": mv.built_to_dict(built),
        "validation": {
            "publishable": not blockers, "blockers": blockers, "warnings": warnings,
            "can_publish_now": False,
        },
    }  # fmt: skip


def preview_stored(session: Session, movement_id: uuid.UUID) -> dict[str, Any]:
    row = _get(session, movement_id)
    built = mv.build_movement(mv.definition_from_dict(row.definition), slug=row.slug)
    out = _preview(built)
    out["validation"]["can_publish_now"] = (
        out["validation"]["publishable"] and row.status == "approved"
    )
    return out


def change_status(
    session: Session, movement_id: uuid.UUID, body: s.StatusChangeIn, user: User
) -> Movement:
    row = _get(session, movement_id)
    action = mv.check_transition(row.status, body.to)
    previous = row.status
    if body.to == "published":
        built = mv.build_movement(mv.definition_from_dict(row.definition), slug=row.slug)
        blockers = mv.publication_blockers(built)
        if blockers:
            raise _publication_blocked(blockers)
        row.snapshot = mv.built_to_dict(built)
        row.published_at = utcnow()
    elif previous == "published":
        row.published_at = None  # no longer offered to learners
    row.status = body.to
    _entry(row, user, action, body.note, from_status=previous, to_status=body.to)
    session.commit()
    return row


def admin_list(session: Session, status: str | None = None, q: str | None = None) -> list[Movement]:
    stmt = select(Movement).order_by(Movement.updated_at.desc()).limit(MAX_ROWS)
    if status:
        stmt = stmt.where(Movement.status == status)
    if q:
        stmt = stmt.where(Movement.search_text.contains(q.strip().lower()))
    return list(session.scalars(stmt))


def admin_get(session: Session, movement_id: uuid.UUID) -> Movement:
    return _get(session, movement_id)


def validation_report(session: Session, movement_id: uuid.UUID) -> dict[str, Any]:
    return preview_stored(session, movement_id)["validation"]  # type: ignore[no-any-return]


# ------------------------------------------------------------------ learners


def _published(session: Session, slug: str) -> Movement:
    row = session.scalar(
        select(Movement).where(Movement.slug == slug, Movement.status == "published")
    )
    if row is None or row.snapshot is None:
        raise NotFoundError("Movement not found.", code="movement_not_found")
    return row


def summary(row: Movement) -> dict[str, Any]:
    snap = row.snapshot or {}
    versions = snap.get("versions", [])
    pick = next(
        (v for v in versions if v["level"] == "intermediate"), versions[0] if versions else None
    )
    steps = pick["steps"] if pick else []
    key = snap.get("key", {"tonic": "?", "mode": row.mode})
    return {
        "slug": row.slug, "name": row.name, "mode": row.mode,
        "key": f"{key['tonic']} {key['mode']}",
        "tags": snap.get("tags", []), "levels": [v["level"] for v in versions],
        "chords": [x["symbol"] for x in steps], "romans": [x["roman"] for x in steps],
        "tempo": snap.get("tempo", 80), "time_signature": snap.get("time_signature", [4, 4]),
        "author": snap.get("author"),
        "published_at": row.published_at.isoformat() if row.published_at else None,
    }  # fmt: skip


def published_list(
    session: Session, *, q: str | None, level: str | None, tag: str | None, mode: str | None
) -> list[dict[str, Any]]:
    stmt = (
        select(Movement)
        .where(Movement.status == "published")
        .order_by(Movement.name)
        .limit(MAX_ROWS)
    )
    if mode:
        stmt = stmt.where(Movement.mode == mode)
    if q:
        stmt = stmt.where(Movement.search_text.contains(q.strip().lower()))
    out = [summary(r) for r in session.scalars(stmt) if r.snapshot]
    if level:
        out = [m for m in out if level in m["levels"]]
    if tag:
        want = tag.strip().lower()
        out = [m for m in out if want in (t.lower() for t in m["tags"])]
    return out


def published_detail(session: Session, slug: str, key: str | None) -> dict[str, Any]:
    row = _published(session, slug)
    assert row.snapshot is not None
    if key is None:
        return {"movement": row.snapshot, "live": False}
    d = mv.definition_from_dict(row.definition)
    options = mv.transposition_options(d)
    pc = parse_note_name(key.strip()).pitch_class
    chosen = next((o for o in options if parse_note_name(o).pitch_class == pc), None)
    if chosen is None:
        raise TheoryError(f"{key!r} is not one of this movement's keys.", code="invalid_key")
    if chosen == str(d.key.tonic):
        return {"movement": row.snapshot, "live": False}
    built = mv.build_movement(mv.in_key(d, chosen), slug=row.slug)
    return {"movement": mv.built_to_dict(built), "live": True}


def count_published(session: Session) -> int:
    return int(
        session.scalar(
            select(func.count()).select_from(Movement).where(Movement.status == "published")
        )
        or 0
    )


# ------------------------------------------------------------------ seeding


SEED_AUTHOR = "Keystudy"


def seed_default_movements(
    session: Session, only: Collection[str] | None = None
) -> dict[str, list[str]]:
    """Create and publish a movement for every built-in progression template that does not have
    one yet (C major / A minor). Safe to run repeatedly. Each goes through the same build and
    publication checks as authored content; a template that fails them is reported, not forced.
    `only` limits this to some template ids (used by tests to stay fast)."""
    from music_theory.progressions import default_library

    lib = default_library()
    have = {
        (r.definition or {}).get("template_id") for r in session.scalars(select(Movement)).all()
    }
    out: dict[str, list[str]] = {"created": [], "skipped": [], "failed": []}
    for tid in lib.ids():
        if only is not None and tid not in only:
            continue
        if tid in have:
            out["skipped"].append(tid)
            continue
        tpl = lib.get(tid)
        d = mv.MovementDefinition(
            name=tpl.name,
            key=parse_key("C" if tpl.mode == "major" else "A", tpl.mode),
            template_id=tid,
            tags=tuple(dict.fromkeys((*tpl.styles, tpl.difficulty))),
            theory_explanation=tpl.explanation,
            practice={"beginner": tpl.practice},
            time_signature=tpl.time_signature,
            author=SEED_AUTHOR,
            source="Keystudy built-in templates",
        )
        built = mv.build_movement(d)
        blockers = mv.publication_blockers(built)
        if blockers:
            out["failed"].append(f"{tid}: {blockers[0]}")
            continue
        row = Movement(
            slug=_unique_slug(session, f"{d.name} {d.key}"),
            name=d.name,
            status="published",
            revision=1,
            mode=d.key.mode,
            definition=mv.definition_to_dict(d),
            snapshot=mv.built_to_dict(built),
            history=[],
            search_text=_search_text(d),
            published_at=utcnow(),
        )
        for action, a, b in (
            ("create", None, "draft"),
            ("submit", "draft", "under_review"),
            ("approve", "under_review", "approved"),
            ("publish", "approved", "published"),
        ):
            hist = mv.HistoryEntry(1, mv.now_iso(), SEED_AUTHOR, action, "seeded", a, b)
            row.history = [*row.history, hist.to_dict()]
        session.add(row)
        out["created"].append(tid)
    session.commit()
    return out
