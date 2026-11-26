"""Lessons written in the admin screen: storage, review workflow and publication.

Rules enforced here (not in the UI):
- Only educators and admins reach these functions (see routes).
- The engine validates a lesson before it is saved: structure, every example built, exercise
  kinds, and the linked progression template. A lesson that cannot be built is refused.
- Built-in lesson ids are protected. A written lesson can neither replace nor shadow them.
- Same workflow as movements: draft -> in review -> approved -> published. Editing a lesson that
  is in review or approved returns it to draft; a published or archived lesson cannot be edited.
- Publishing needs `approved`, an example, and every prerequisite already live (built-in or
  published). A lesson other live lessons depend on cannot be unpublished or archived.
- Edits carry the revision they started from; a stale revision is a conflict, not an overwrite.
"""

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import ConflictError, NotFoundError
from app.models.base import utcnow
from app.models.custom_lesson import CustomLesson
from app.models.user import User
from app.schemas import lesson_admin as s
from app.services import lesson_catalog, lesson_service
from music_theory import lessons as lx
from music_theory import movements as mv
from music_theory.errors import TheoryError

MAX_ROWS = 500
MAX_HISTORY = 50
_LIVE = ("published",)


def _actor(user: User) -> str:
    return user.display_name or "unknown"


def _raw(data: s.LessonDefinitionIn) -> dict[str, Any]:
    raw = data.model_dump(mode="json", exclude={"revision"})
    raw["title"] = raw["title"].strip()
    raw["summary"] = raw["summary"].strip()
    raw["schema_version"] = lx.LESSON_SCHEMA_VERSION
    return raw


def _entry(row: CustomLesson, user: User, action: str, note: str = "", **st: str | None) -> None:
    entry = {
        "revision": row.revision, "at": utcnow().isoformat(), "actor": _actor(user),
        "action": action, "note": note,
        "from_status": st.get("from_status"), "to_status": st.get("to_status"),
    }  # fmt: skip
    row.history = [*row.history, entry][-MAX_HISTORY:]  # reassign: JSON is not change-tracked


def _get(session: Session, row_id: uuid.UUID) -> CustomLesson:
    row = session.get(CustomLesson, row_id)
    if row is None:
        raise NotFoundError("Lesson not found.", code="lesson_not_found")
    return row


def _builtin_ids() -> set[str]:
    return {x.id for x in lx.all_lessons()}


def _check_id_free(session: Session, lesson_id: str, exclude: uuid.UUID | None = None) -> None:
    if lesson_id in _builtin_ids():
        raise ConflictError(
            f"{lesson_id!r} is a built-in lesson and cannot be redefined.", code="lesson_id_builtin"
        )
    found = session.scalar(select(CustomLesson.id).where(CustomLesson.lesson_id == lesson_id))
    if found is not None and found != exclude:
        raise ConflictError(
            f"A lesson with id {lesson_id!r} already exists.", code="lesson_id_taken"
        )


def _lesson(raw: dict[str, Any]) -> lx.Lesson:
    return lx.validate_lesson(raw)  # LessonError (422) with a stable code when invalid


# ------------------------------------------------------------------ checks


def _live_others(session: Session, exclude: uuid.UUID | None) -> tuple[lx.Lesson, ...]:
    """The live catalogue without the row being checked."""
    lessons = list(lx.all_lessons())
    rows = session.scalars(
        select(CustomLesson)
        .where(CustomLesson.status == "published")
        .order_by(CustomLesson.published_at)
    ).all()
    for row in rows:
        if row.id == exclude:
            continue
        try:
            lessons.append(lesson_catalog.parse_row(row))
        except TheoryError:
            continue
    return tuple(lessons)


def _blockers(session: Session, lesson: lx.Lesson, exclude: uuid.UUID | None) -> list[str]:
    blockers = lx.lesson_publication_blockers(lesson)
    live = {x.id for x in _live_others(session, exclude)}
    for p in lesson.prerequisites:
        if p == lesson.id:
            blockers.append("A lesson cannot be its own prerequisite.")
        elif p not in live:
            blockers.append(f"Prerequisite {p!r} is not a live lesson. Publish it first.")
    return blockers


def _dependents(session: Session, row: CustomLesson) -> list[str]:
    return [
        x.id
        for x in _live_others(session, row.id)
        if row.lesson_id in x.prerequisites and x.id != row.lesson_id
    ]


def _preview(session: Session, lesson: lx.Lesson, row: CustomLesson | None) -> dict[str, Any]:
    exclude = row.id if row else None
    others = _live_others(session, exclude)
    levels = {x.id: x.level for x in others}
    blockers = _blockers(session, lesson, exclude)
    # prerequisites that do not exist yet are shown as such rather than crashing the preview
    shown = tuple(x for x in others if x.id != lesson.id)
    known = {x.id for x in shown}
    view = lx.Lesson(
        **{**lesson.__dict__, "prerequisites": tuple(p for p in lesson.prerequisites if p in known)}
    )
    detail = lesson_service.build_detail(
        view, lesson_service.Counts({}, set()), None, (*shown, view)
    )
    return {
        "lesson": detail,
        "publishable": not blockers,
        "blockers": blockers,
        "warnings": lx.lesson_publication_warnings(lesson, levels),
        "can_publish_now": (not blockers) and row is not None and row.status == "approved",
    }


def preview_definition(session: Session, data: s.LessonDefinitionIn) -> dict[str, Any]:
    return _preview(session, _lesson(_raw(data)), None)


def preview_stored(session: Session, row_id: uuid.UUID) -> dict[str, Any]:
    row = _get(session, row_id)
    return _preview(session, _lesson(row.definition), row)


# ------------------------------------------------------------------ lifecycle


def create(session: Session, data: s.LessonDefinitionIn, user: User) -> CustomLesson:
    raw = _raw(data)
    lesson = _lesson(raw)
    _check_id_free(session, lesson.id)
    row = CustomLesson(
        lesson_id=lesson.id, title=lesson.title, level=lesson.level, status="draft",
        revision=1, definition=raw, history=[], created_by=user.id,
    )  # fmt: skip
    _entry(row, user, "create", to_status="draft")
    session.add(row)
    session.commit()
    return row


def update(session: Session, row_id: uuid.UUID, data: s.LessonUpdateIn, user: User) -> CustomLesson:
    row = _get(session, row_id)
    if row.status == "published":
        raise ConflictError(
            "A published lesson cannot be edited. Unpublish it first, edit, then publish again.",
            code="lesson_published",
        )
    if row.status == "archived":
        raise ConflictError("Restore an archived lesson before editing it.", code="lesson_archived")
    if data.revision != row.revision:
        raise ConflictError(
            "Someone else changed this lesson. Reload it and apply your edit again.",
            code="revision_conflict",
            details={"current_revision": row.revision},
        )
    raw = _raw(s.LessonDefinitionIn(**data.model_dump(exclude={"revision"})))
    lesson = _lesson(raw)
    _check_id_free(session, lesson.id, exclude=row.id)
    previous = row.status
    row.revision += 1
    row.lesson_id, row.title, row.level, row.definition = lesson.id, lesson.title, lesson.level, raw
    note = ""
    if previous in ("under_review", "approved"):
        row.status = "draft"
        note = f"Edited after being {previous.replace('_', ' ')}; returned to draft."
    _entry(row, user, "edit", note, from_status=previous, to_status=row.status)
    session.commit()
    return row


def change_status(
    session: Session, row_id: uuid.UUID, data: s.LessonStatusIn, user: User
) -> CustomLesson:
    row = _get(session, row_id)
    if data.to not in mv.TRANSITIONS.get(row.status, ()):
        allowed = list(mv.TRANSITIONS.get(row.status, ()))
        raise ConflictError(
            f"A {row.status.replace('_', ' ')} lesson cannot become {data.to.replace('_', ' ')}.",
            code="invalid_transition",
            details={"allowed": allowed},
        )
    previous = row.status
    if data.to == "published":
        blockers = _blockers(session, _lesson(row.definition), row.id)
        if blockers:
            raise ConflictError(
                "This lesson is not ready to publish: " + " ".join(blockers[:3]),
                code="publication_blocked",
                details={"blockers": blockers},
            )
        row.published_at = utcnow()
    elif previous == "published":
        needed_by = _dependents(session, row)
        if needed_by:
            raise ConflictError(
                "Other live lessons list this one as a prerequisite: "
                + ", ".join(needed_by)
                + ". Unpublish those first.",
                code="lesson_in_use",
                details={"dependents": needed_by},
            )
        row.published_at = None
    row.status = data.to
    action = mv.ACTION_FOR_MOVE.get(
        (previous, data.to), "archive" if data.to == "archived" else data.to
    )
    _entry(row, user, action, data.note, from_status=previous, to_status=data.to)
    session.commit()
    return row


def admin_get(session: Session, row_id: uuid.UUID) -> CustomLesson:
    return _get(session, row_id)


def admin_list(session: Session, status: str | None, q: str | None) -> list[CustomLesson]:
    stmt = select(CustomLesson).order_by(CustomLesson.updated_at.desc()).limit(MAX_ROWS)
    if status:
        stmt = stmt.where(CustomLesson.status == status)
    if q:
        needle = q.strip().lower()
        stmt = stmt.where(
            CustomLesson.title.ilike(f"%{needle}%") | CustomLesson.lesson_id.contains(needle)
        )
    return list(session.scalars(stmt))
