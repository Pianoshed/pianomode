"""Lesson authoring: permissions, validation, review workflow and the learner curriculum."""

from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.models.user import Role, User

A = "/api/v1/admin/lessons"
L = "/api/v1/lessons"
EDUCATOR = "teacher@example.com"
LEARNER = "learner@example.com"


def lesson(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": "tritone-basics",
        "title": "The tritone",
        "level": "intermediate",
        "summary": "Six semitones: the interval that splits the octave in half.",
        "objectives": ["Name the tritone.", "Hear why it sounds unstable."],
        "prerequisites": ["notes-and-keyboard"],
        "sections": [
            {
                "heading": "Half an octave",
                "body": ["A tritone is three whole tones. It can be spelled two ways."],
                "examples": [
                    {
                        "type": "interval",
                        "lower": "C4",
                        "upper": "F#4",
                        "caption": "C up to F-sharp.",
                    }
                ],
            }
        ],
        "practice": [{"kind": "interval_identify", "difficulty": "intermediate", "goal": 3}],
        "tags": ["intervals"],
    }
    return {**base, **over}


@pytest.fixture
def users(make_user: Callable[..., User]) -> None:
    make_user(LEARNER)
    make_user(EDUCATOR, roles=(Role.EDUCATOR,))


@pytest.fixture
def staff(client: TestClient, users: None, sign_in: Callable[..., None]) -> TestClient:
    sign_in(EDUCATOR)
    return client


def create(c: TestClient, **over: Any) -> dict[str, Any]:
    r = c.post(A, json=lesson(**over))
    assert r.status_code == 201, r.text
    data: dict[str, Any] = r.json()
    return data


def move(c: TestClient, rid: str, to: str, status: int = 200) -> dict[str, Any]:
    r = c.post(f"{A}/{rid}/status", json={"to": to})
    assert r.status_code == status, r.text
    data: dict[str, Any] = r.json()
    return data


def publish(c: TestClient, **over: Any) -> dict[str, Any]:
    d = create(c, **over)
    for to in ("under_review", "approved", "published"):
        d = move(c, d["id"], to)
    return d


def learner_ids(c: TestClient, sign_in: Callable[..., None]) -> list[str]:
    sign_in(LEARNER)
    ids = [i["id"] for i in c.get(L).json()["items"]]
    sign_in(EDUCATOR)
    return ids


def test_learners_cannot_author(
    client: TestClient, users: None, sign_in: Callable[..., None]
) -> None:
    assert client.get(A).status_code == 401
    sign_in(LEARNER)
    assert client.get(A).status_code == 403
    assert client.post(A, json=lesson()).status_code == 403


def test_create_is_a_draft_with_history(staff: TestClient) -> None:
    d = create(staff)
    assert d["status"] == "draft" and d["revision"] == 1
    assert d["allowed_transitions"] == ["under_review", "archived"]
    assert d["history"][0]["action"] == "create"


def test_draft_is_invisible_to_learners(staff: TestClient, sign_in: Callable[..., None]) -> None:
    d = create(staff)
    assert "tritone-basics" not in learner_ids(staff, sign_in)
    sign_in(LEARNER)
    assert staff.get(f"{L}/tritone-basics").status_code == 404
    sign_in(EDUCATOR)
    move(staff, d["id"], "under_review")
    assert "tritone-basics" not in learner_ids(staff, sign_in)


def test_publishing_needs_the_review_steps(staff: TestClient) -> None:
    d = create(staff)
    r = staff.post(f"{A}/{d['id']}/status", json={"to": "published"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "invalid_transition"


def test_published_lesson_reaches_learners_with_built_examples(
    staff: TestClient, sign_in: Callable[..., None]
) -> None:
    publish(staff)
    sign_in(LEARNER)
    ids = [i["id"] for i in staff.get(L).json()["items"]]
    assert ids[-1] == "tritone-basics" and ids[0] == "notes-and-keyboard"
    detail = staff.get(f"{L}/tritone-basics").json()
    ex = detail["sections"][0]["examples"][0]
    assert ex["items"][0]["notes"] == ["C4", "F#4"] or ex["items"][0]["midi"] == [60, 66]
    assert detail["prerequisites"][0]["id"] == "notes-and-keyboard"
    assert detail["status"] == "not_started"
    # the built-in lesson now lists the new one as what comes next
    base = staff.get(f"{L}/notes-and-keyboard").json()
    assert "tritone-basics" in [n["id"] for n in base["next"]]


def test_engine_rejects_unbuildable_examples(staff: TestClient) -> None:
    bad = lesson(
        sections=[
            {
                "heading": "x",
                "body": ["y"],
                "examples": [{"type": "chord", "symbol": "Hdim99", "caption": "nope"}],
            }
        ]
    )
    r = staff.post(A, json=bad)
    assert r.status_code == 422 and r.json()["error"]["code"] == "invalid_example"


def test_unknown_exercise_kind_is_rejected(staff: TestClient) -> None:
    r = staff.post(A, json=lesson(practice=[{"kind": "not_a_kind", "difficulty": "beginner"}]))
    assert r.status_code == 422 and r.json()["error"]["code"] == "unknown_exercise_kind"


def test_unknown_progression_template_is_rejected(staff: TestClient) -> None:
    r = staff.post(A, json=lesson(movement_template="no_such_template"))
    assert r.status_code == 422


def test_known_progression_template_is_accepted(staff: TestClient) -> None:
    assert staff.post(A, json=lesson(movement_template="ii_v_i")).status_code == 201


@pytest.mark.parametrize(
    "bad",
    [
        {"id": "Bad Id"},
        {"objectives": []},
        {"sections": []},
        {"practice": []},
        {"level": "godlike"},
        {"practice": [{"kind": "note_name", "difficulty": "beginner", "goal": 99}]},
        {"sections": [{"heading": "h", "body": [], "examples": []}]},
        {"tags": ["t"] * 9},
    ],
)
def test_malformed_lessons_are_rejected(staff: TestClient, bad: dict[str, Any]) -> None:
    assert staff.post(A, json=lesson(**bad)).status_code == 422


def test_example_extras_are_bounded(staff: TestClient) -> None:
    ex = {"type": "chord", "symbol": "C", "caption": "c", "nested": {"a": 1}}
    bad = lesson(sections=[{"heading": "h", "body": ["b"], "examples": [ex]}])
    assert staff.post(A, json=bad).status_code == 422


def test_builtin_ids_are_protected(staff: TestClient) -> None:
    r = staff.post(A, json=lesson(id="notes-and-keyboard", prerequisites=[]))
    assert r.status_code == 409 and r.json()["error"]["code"] == "lesson_id_builtin"


def test_duplicate_id_conflicts(staff: TestClient) -> None:
    create(staff)
    r = staff.post(A, json=lesson())
    assert r.status_code == 409 and r.json()["error"]["code"] == "lesson_id_taken"


def test_publication_needs_an_example(staff: TestClient) -> None:
    d = create(staff, sections=[{"heading": "Only words", "body": ["Just text."], "examples": []}])
    move(staff, d["id"], "under_review")
    move(staff, d["id"], "approved")
    r = staff.post(f"{A}/{d['id']}/status", json={"to": "published"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "publication_blocked"
    assert "example" in r.json()["error"]["details"]["blockers"][0]


def test_publication_needs_live_prerequisites(staff: TestClient) -> None:
    first = create(staff, id="first-lesson", prerequisites=[])
    second = create(staff, id="second-lesson", prerequisites=["first-lesson"])
    for to in ("under_review", "approved"):
        move(staff, second["id"], to)
    r = staff.post(f"{A}/{second['id']}/status", json={"to": "published"})
    assert r.status_code == 409
    assert "first-lesson" in r.json()["error"]["details"]["blockers"][0]
    for to in ("under_review", "approved", "published"):
        move(staff, first["id"], to)
    assert move(staff, second["id"], "published")["status"] == "published"


def test_unknown_prerequisite_blocks_publication(staff: TestClient) -> None:
    d = create(staff, prerequisites=["does-not-exist"])
    prev = staff.get(f"{A}/{d['id']}/preview").json()
    assert not prev["publishable"] and "does-not-exist" in prev["blockers"][0]


def test_cannot_unpublish_a_lesson_others_depend_on(staff: TestClient) -> None:
    first = publish(staff, id="first-lesson", prerequisites=[])
    publish(staff, id="second-lesson", prerequisites=["first-lesson"])
    for to in ("approved", "archived"):
        r = staff.post(f"{A}/{first['id']}/status", json={"to": to})
        assert r.status_code == 409 and r.json()["error"]["code"] == "lesson_in_use"
        assert r.json()["error"]["details"]["dependents"] == ["second-lesson"]


def test_unpublish_removes_it_from_learners(
    staff: TestClient, sign_in: Callable[..., None]
) -> None:
    d = publish(staff)
    assert "tritone-basics" in learner_ids(staff, sign_in)
    move(staff, d["id"], "approved")
    assert "tritone-basics" not in learner_ids(staff, sign_in)


def test_editing_after_review_returns_to_draft(staff: TestClient) -> None:
    d = create(staff)
    move(staff, d["id"], "under_review")
    r = staff.put(f"{A}/{d['id']}", json={**lesson(title="The tritone, revised"), "revision": 1})
    assert r.status_code == 200
    assert r.json()["status"] == "draft" and r.json()["revision"] == 2
    assert r.json()["title"] == "The tritone, revised"


def test_published_lesson_cannot_be_edited(staff: TestClient) -> None:
    d = publish(staff)
    r = staff.put(f"{A}/{d['id']}", json={**lesson(), "revision": 1})
    assert r.status_code == 409 and r.json()["error"]["code"] == "lesson_published"


def test_stale_revision_conflicts(staff: TestClient) -> None:
    d = create(staff)
    staff.put(f"{A}/{d['id']}", json={**lesson(), "revision": 1})
    r = staff.put(f"{A}/{d['id']}", json={**lesson(), "revision": 1})
    assert r.status_code == 409 and r.json()["error"]["code"] == "revision_conflict"
    assert r.json()["error"]["details"]["current_revision"] == 2


def test_revision_shown_to_learners_tracks_edits(
    staff: TestClient, sign_in: Callable[..., None]
) -> None:
    d = publish(staff)
    move(staff, d["id"], "approved")
    move(staff, d["id"], "draft")
    staff.put(f"{A}/{d['id']}", json={**lesson(summary="A sharper summary."), "revision": 1})
    for to in ("under_review", "approved", "published"):
        move(staff, d["id"], to)
    sign_in(LEARNER)
    detail = staff.get(f"{L}/tritone-basics").json()
    assert detail["revision"] == 2 and detail["summary"] == "A sharper summary."


def test_preview_shows_learner_view_without_saving(staff: TestClient) -> None:
    r = staff.post(f"{A}/preview", json=lesson())
    assert r.status_code == 200
    p = r.json()
    assert p["publishable"] and p["can_publish_now"] is False
    assert p["lesson"]["sections"][0]["examples"][0]["items"][0]["midi"] == [60, 66]
    assert staff.get(A).json()["total"] == 0


def test_preview_warns_without_blocking(staff: TestClient) -> None:
    sections = [
        {
            "heading": "With",
            "body": ["b"],
            "examples": [{"type": "chord", "symbol": "C", "caption": "c"}],
        },
        {"heading": "Without", "body": ["b"], "examples": []},
    ]
    p = staff.post(
        f"{A}/preview",
        json=lesson(
            sections=sections,
            objectives=["Just one."],
            level="beginner",
            prerequisites=["seventh-chords"],
        ),
    ).json()
    assert p["publishable"]
    text = " ".join(p["warnings"])
    assert "Section 2" in text and "one learning objective" in text and "harder level" in text


def test_stored_preview_can_publish_only_when_approved(staff: TestClient) -> None:
    d = create(staff)
    assert staff.get(f"{A}/{d['id']}/preview").json()["can_publish_now"] is False
    move(staff, d["id"], "under_review")
    move(staff, d["id"], "approved")
    assert staff.get(f"{A}/{d['id']}/preview").json()["can_publish_now"] is True


def test_list_filters(staff: TestClient) -> None:
    publish(staff)
    create(staff, id="other-draft", title="Another one", prerequisites=[])
    assert staff.get(A).json()["total"] == 2
    assert staff.get(A, params={"status": "published"}).json()["total"] == 1
    assert staff.get(A, params={"q": "another"}).json()["total"] == 1


def test_history_records_each_step(staff: TestClient) -> None:
    d = publish(staff)
    acts = [h["action"] for h in staff.get(f"{A}/{d['id']}").json()["history"]]
    assert acts == ["create", "submit", "approve", "publish"]


def test_unknown_lesson_is_404(staff: TestClient) -> None:
    r = staff.get(f"{A}/00000000-0000-0000-0000-000000000000")
    assert r.status_code == 404 and r.json()["error"]["code"] == "lesson_not_found"


def test_builtin_lessons_unchanged_by_authoring(
    staff: TestClient, sign_in: Callable[..., None]
) -> None:
    sign_in(LEARNER)
    before = staff.get(f"{L}/notes-and-keyboard").json()["sections"]
    sign_in(EDUCATOR)
    publish(staff)
    sign_in(LEARNER)
    assert staff.get(f"{L}/notes-and-keyboard").json()["sections"] == before
