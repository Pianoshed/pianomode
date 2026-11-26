"""Lessons API: curriculum, engine-built examples, and progress derived from practice."""

from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.models.user import User
from music_theory.exercises import generate_exercise, reference_answer
from music_theory.lessons import all_lessons

LESSONS = "/api/v1/lessons"
EX = "/api/v1/theory/exercises"


@pytest.fixture
def api(
    client: TestClient, make_user: Callable[..., User], sign_in: Callable[..., None]
) -> TestClient:
    make_user()
    sign_in()
    return client


def right_answer(exercise_id: str) -> Any:
    """An answer the engine grades as correct (its own reference answer)."""
    return reference_answer(exercise_id)


def answer_correctly(c: TestClient, kind: str, difficulty: str, seeds: range) -> None:
    for seed in seeds:
        ex = generate_exercise(kind, difficulty, seed)  # type: ignore[arg-type]
        r = c.post(f"{EX}/validate", json={"exercise_id": ex.id, "answer": right_answer(ex.id)})
        assert r.status_code == 200 and r.json()["correct"] is True, r.text


def lesson(c: TestClient, lesson_id: str) -> dict[str, Any]:
    r = c.get(f"{LESSONS}/{lesson_id}")
    assert r.status_code == 200, r.text
    data: dict[str, Any] = r.json()
    return data


def summary(c: TestClient, lesson_id: str) -> dict[str, Any]:
    items = c.get(LESSONS).json()["items"]
    return next(i for i in items if i["id"] == lesson_id)


def test_requires_sign_in(client: TestClient) -> None:
    assert client.get(LESSONS).status_code == 401
    assert client.get(f"{LESSONS}/triads").status_code == 401


def test_list_is_in_curriculum_order_and_starts_untouched(api: TestClient) -> None:
    items = api.get(LESSONS).json()["items"]
    assert [i["id"] for i in items] == [x.id for x in all_lessons()]
    assert all(i["status"] == "not_started" and i["goals_met"] == 0 for i in items)
    first = items[0]
    assert first["prerequisites"] == [] and first["unmet_prerequisites"] == []
    later = next(i for i in items if i["id"] == "intervals")
    assert later["unmet_prerequisites"] == ["notes-and-keyboard"]


def test_lesson_detail_has_engine_built_examples(api: TestClient) -> None:
    d = lesson(api, "triads")
    assert d["title"] == "Triads" and d["objectives"] and d["revision"] == 1
    first = d["sections"][0]["examples"][0]
    assert first["type"] == "chord"
    assert first["items"][0]["notes"] == ["C", "E", "G"]
    assert first["items"][0]["midi"] == [60, 64, 67]
    assert first["play"] and first["tempo"] > 0
    kinds = [g["kind"] for g in d["practice"]]
    assert kinds == ["triad_build", "triad_identify", "ear_chord_quality"]
    assert d["practice"][2]["ear_training"] is True and d["practice"][0]["ear_training"] is False
    assert [p["id"] for p in d["prerequisites"]] == ["intervals", "major-scale"]
    assert [n["id"] for n in d["next"]] == [
        "inversions",
        "seventh-chords",
        "diatonic-harmony",
        "ear-training",
    ]


def test_roman_numerals_in_a_lesson_come_from_the_engine(api: TestClient) -> None:
    ex = lesson(api, "secondary-dominants")["sections"][0]["examples"][0]
    assert [i["detail"] for i in ex["items"]] == ["I", "V7/V", "V"]


def test_unknown_lesson_is_404_with_a_stable_code(api: TestClient) -> None:
    r = api.get(f"{LESSONS}/no-such-lesson")
    assert r.status_code == 404 and r.json()["error"]["code"] == "lesson_not_found"
    assert api.get(f"{LESSONS}/{'x' * 65}").status_code == 422


# ------------------------------------------------------------------ progress


def test_goal_progress_moves_from_not_started_to_practised(api: TestClient) -> None:
    goal = next(
        p for p in lesson(api, "notes-and-keyboard")["practice"] if p["kind"] == "note_name"
    )
    assert goal["goal"] == 5 and goal["correct"] == 0 and goal["attempted"] is False

    answer_correctly(api, "note_name", "beginner", range(1, 3))
    d = lesson(api, "notes-and-keyboard")
    assert d["status"] == "in_progress"
    assert d["practice"][0]["correct"] == 2 and d["practice"][0]["met"] is False

    answer_correctly(api, "note_name", "beginner", range(3, 6))
    d = lesson(api, "notes-and-keyboard")
    assert d["status"] == "practised" and d["practice"][0]["met"] is True
    assert summary(api, "notes-and-keyboard")["goals_met"] == 1
    assert summary(api, "intervals")["unmet_prerequisites"] == []


def test_repeating_one_exercise_cannot_inflate_progress(api: TestClient) -> None:
    for _ in range(8):
        answer_correctly(api, "note_name", "beginner", range(7, 8))
    goal = lesson(api, "notes-and-keyboard")["practice"][0]
    assert goal["correct"] == 1 and goal["met"] is False


def test_a_wrong_answer_makes_a_lesson_in_progress_but_never_counts_toward_a_goal(
    api: TestClient,
) -> None:
    ex = generate_exercise("note_name", "beginner", 9)
    api.post(f"{EX}/validate", json={"exercise_id": ex.id, "answer": "H"})  # readable? either way
    ex2 = generate_exercise("triad_identify", "beginner", 4)
    wrong = next(c for c in ("Cm", "Dm", "Em", "G") if c != right_answer(ex2.id))
    api.post(f"{EX}/validate", json={"exercise_id": ex2.id, "answer": wrong})
    d = lesson(api, "triads")
    goal = next(p for p in d["practice"] if p["kind"] == "triad_identify")
    assert goal["attempted"] is True and goal["correct"] == 0 and goal["met"] is False
    assert d["status"] == "in_progress"


def test_practice_at_another_difficulty_does_not_count(api: TestClient) -> None:
    answer_correctly(api, "note_name", "advanced", range(1, 8))
    assert lesson(api, "notes-and-keyboard")["status"] == "not_started"


def test_a_lesson_needs_every_goal_met(api: TestClient) -> None:
    answer_correctly(api, "interval_identify", "beginner", range(1, 5))  # goal 4
    d = lesson(api, "intervals")
    assert d["status"] == "in_progress"  # interval_build goal is still unmet
    answer_correctly(api, "interval_build", "beginner", range(1, 4))  # goal 3
    assert lesson(api, "intervals")["status"] == "practised"


def test_progress_is_private_to_each_learner(
    client: TestClient, make_user: Callable[..., User], sign_in: Callable[..., None]
) -> None:
    make_user("a@example.com")
    make_user("b@example.com")
    sign_in("a@example.com")
    answer_correctly(client, "note_name", "beginner", range(1, 6))
    assert lesson(client, "notes-and-keyboard")["status"] == "practised"
    client.post("/api/v1/auth/logout")
    sign_in("b@example.com")
    assert lesson(client, "notes-and-keyboard")["status"] == "not_started"


# ------------------------------------------------------------------ link to the movement library


def test_movement_link_is_only_given_when_that_movement_is_published(
    api: TestClient, session_factory: Any
) -> None:
    from app.services import movement_service

    assert lesson(api, "progressions")["movement_slug"] is None
    with session_factory() as s:
        movement_service.seed_default_movements(s)
    slug = lesson(api, "progressions")["movement_slug"]
    assert slug is not None
    assert api.get(f"/api/v1/movements/{slug}").status_code == 200
    assert lesson(api, "triads")["movement_slug"] is None  # that lesson links to none


def test_every_lesson_can_be_served(api: TestClient) -> None:
    for x in all_lessons():
        d = lesson(api, x.id)
        assert d["sections"] and d["practice"] and d["objectives"], x.id
