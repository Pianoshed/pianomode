"""The live registry must survive bad stored rows and never let a custom scale shadow a built-in."""

from sqlalchemy.orm import Session

from app.models.custom_scale import CustomScale
from app.services.scale_service import live_registry
from music_theory.scales import default_registry


def row(scale_id: str, status: str, definition: dict[str, object]) -> CustomScale:
    return CustomScale(
        scale_id=scale_id,
        name=scale_id,
        status=status,
        revision=1,
        definition=definition,
        history=[],
    )


GOOD = {"id": "good_scale", "name": "Good", "formula": ["P1", "M2", "m3", "P5"], "aliases": []}


def test_only_published_rows_join_the_registry(session: Session) -> None:
    session.add_all(
        [
            row("good_scale", "published", GOOD),
            row("draft_scale", "draft", {**GOOD, "id": "draft_scale"}),
        ]
    )
    session.commit()
    ids = live_registry(session).ids()
    assert "good_scale" in ids and "draft_scale" not in ids


def test_corrupt_row_is_skipped_not_fatal(session: Session) -> None:
    session.add_all(
        [
            row(
                "broken", "published", {"id": "broken", "name": "Broken", "formula": ["P1", "ZZ9"]}
            ),
            row("empty", "published", {}),
            row("good_scale", "published", GOOD),
        ]
    )
    session.commit()
    ids = live_registry(session).ids()
    assert "good_scale" in ids and "broken" not in ids and "empty" not in ids


def test_builtin_wins_a_clash(session: Session) -> None:
    session.add(row("evil", "published", {**GOOD, "id": "evil", "aliases": ["ionian"]}))
    session.commit()
    reg = live_registry(session)
    assert reg.get("ionian").id == "major"
    assert "evil" not in reg.ids()


def test_default_registry_is_never_mutated(session: Session) -> None:
    before = list(default_registry().ids())
    session.add(row("good_scale", "published", GOOD))
    session.commit()
    live_registry(session)
    assert list(default_registry().ids()) == before
