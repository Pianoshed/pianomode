"""The live catalogue must survive bad stored rows and keep built-ins first."""

from typing import Any

from sqlalchemy.orm import Session

from app.models.base import utcnow
from app.models.custom_lesson import CustomLesson
from app.services.lesson_catalog import catalog
from music_theory import lessons as lx


def definition(lid: str, prereqs: list[str] | None = None, **over: Any) -> dict[str, Any]:
    return {
        "schema_version": 1, "id": lid, "title": lid, "level": "beginner", "summary": "s",
        "objectives": ["o"], "prerequisites": prereqs or [],
        "sections": [{"heading": "h", "body": ["b"], "examples": [{"type": "chord", "symbol": "C", "caption": "c"}]}],
        "practice": [{"kind": "note_name", "difficulty": "beginner", "goal": 2}], "tags": [], **over,
    }  # fmt: skip


def row(lid: str, d: dict[str, Any], status: str = "published") -> CustomLesson:
    return CustomLesson(
        lesson_id=lid,
        title=lid,
        level="beginner",
        status=status,
        revision=3,
        definition=d,
        history=[],
        published_at=utcnow(),
    )


def ids(session: Session) -> list[str]:
    return [x.id for x in catalog(session)]


def test_builtins_come_first_and_alone_when_nothing_published(session: Session) -> None:
    assert ids(session) == [x.id for x in lx.all_lessons()]


def test_published_rows_join_after_builtins_with_their_revision(session: Session) -> None:
    session.add(row("mine", definition("mine")))
    session.commit()
    got = catalog(session)
    assert got[-1].id == "mine" and got[-1].revision == 3
    assert [x.id for x in got[:-1]] == [x.id for x in lx.all_lessons()]


def test_unpublished_rows_stay_out(session: Session) -> None:
    session.add(row("draft-one", definition("draft-one"), status="draft"))
    session.commit()
    assert "draft-one" not in ids(session)


def test_corrupt_or_orphaned_rows_are_skipped(session: Session) -> None:
    session.add_all(
        [
            row("broken", {"id": "broken"}),
            row("orphan", definition("orphan", ["no-such-lesson"])),
            row("fine", definition("fine")),
        ]
    )
    session.commit()
    got = ids(session)
    assert "fine" in got and "broken" not in got and "orphan" not in got


def test_a_row_cannot_shadow_a_builtin(session: Session) -> None:
    session.add(row("shadow", definition("notes-and-keyboard", title="Evil twin")))
    session.commit()
    got = catalog(session)
    assert [x.id for x in got].count("notes-and-keyboard") == 1
    assert next(x for x in got if x.id == "notes-and-keyboard").title != "Evil twin"
