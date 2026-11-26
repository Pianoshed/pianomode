"""Exercise attempts: what is recorded, what is not, and whose progress is whose."""

from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.models.user import User
from music_theory.exercises import generate_exercise, reference_answer

T = "/api/v1/theory/exercises"


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


def answer(c: TestClient, exercise_id: str, value: Any) -> dict[str, Any]:
    r = c.post(f"{T}/validate", json={"exercise_id": exercise_id, "answer": value})
    assert r.status_code == 200, r.text
    data: dict[str, Any] = r.json()
    return data


def progress(c: TestClient) -> list[dict[str, Any]]:
    r = c.get(f"{T}/progress")
    assert r.status_code == 200, r.text
    items: list[dict[str, Any]] = r.json()["items"]
    return items


def test_requires_sign_in(client: TestClient) -> None:
    assert client.get(f"{T}/progress").status_code == 401


def test_empty_at_first(api: TestClient) -> None:
    assert progress(api) == []


def test_correct_and_incorrect_answers_are_counted(api: TestClient) -> None:
    ex = generate_exercise("note_name", "beginner", 1)
    good = answer(api, ex.id, right_answer(ex.id))
    assert good["correct"] is True
    bad = answer(api, ex.id, "H")  # not a note, but readable as an (incorrect) text answer
    items = progress(api)
    assert len(items) == 1
    row = items[0]
    assert (row["kind"], row["difficulty"]) == ("note_name", "beginner")
    assert row["attempts"] == 1 + (0 if bad["status"] == "unreadable" else 1)
    assert row["correct"] == 1


def test_unreadable_answers_are_not_attempts(api: TestClient) -> None:
    ex = generate_exercise("triad_identify", "beginner", 3)
    g = answer(api, ex.id, "this is not a chord at all !!!")
    assert g["status"] == "unreadable"
    assert progress(api) == []


def test_unreadable_status_is_never_stored(api: TestClient, session_factory: Any) -> None:
    from app.services import exercise_service

    ex = generate_exercise("note_name", "beginner", 5)
    with session_factory() as s:
        user = s.query(User).one()
        exercise_service.record_attempt(s, user, ex.id, "unreadable", False)
        assert exercise_service.progress(s, user) == []
        exercise_service.record_attempt(s, user, ex.id, "incorrect", False)
        assert exercise_service.progress(s, user)[0].attempts == 1


def test_a_bad_exercise_id_is_an_error_and_records_nothing(api: TestClient) -> None:
    r = api.post(f"{T}/validate", json={"exercise_id": "nonsense", "answer": "C"})
    assert r.status_code == 422
    assert progress(api) == []


def test_recent_window_and_grouping(api: TestClient) -> None:
    for seed in range(1, 13):  # 12 attempts, all correct
        ex = generate_exercise("note_name", "beginner", seed)
        answer(api, ex.id, right_answer(ex.id))
    hard = generate_exercise("note_name", "advanced", 1)
    answer(api, hard.id, right_answer(hard.id))
    rows = {(r["kind"], r["difficulty"]): r for r in progress(api)}
    assert set(rows) == {("note_name", "beginner"), ("note_name", "advanced")}
    b = rows[("note_name", "beginner")]
    assert b["attempts"] == 12 and b["correct"] == 12
    assert b["recent_attempts"] == 10 and b["recent_correct"] == 10


def test_progress_is_private_to_each_learner(
    client: TestClient, make_user: Callable[..., User], sign_in: Callable[..., None]
) -> None:
    make_user("a@example.com")
    make_user("b@example.com")
    sign_in("a@example.com")
    ex = generate_exercise("note_name", "beginner", 2)
    answer(client, ex.id, right_answer(ex.id))
    assert len(progress(client)) == 1
    client.post("/api/v1/auth/logout")
    sign_in("b@example.com")
    assert progress(client) == []


def test_ear_training_answers_are_recorded_too(api: TestClient) -> None:
    ex = generate_exercise("ear_interval", "beginner", 4)
    answer(api, ex.id, right_answer(ex.id))
    assert progress(api)[0]["kind"] == "ear_interval"
