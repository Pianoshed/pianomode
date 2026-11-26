"""Saved practice results: saving, progress, ownership, deletion and pruning."""

import uuid
from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.models.user import User
from app.services import movement_service, practice_service

SCORE = "/api/v1/practice/score"
WAIT = "/api/v1/practice/wait-results"
HIST = "/api/v1/practice/history"
MV = "/api/v1/movements"
OTHER = "other@example.com"


@pytest.fixture
def api(
    client: TestClient,
    make_user: Callable[..., User],
    sign_in: Callable[..., None],
    session_factory: sessionmaker[Session],
) -> TestClient:
    make_user()
    make_user(OTHER)
    with session_factory() as s:
        movement_service.seed_default_movements(s, only=("ii_v_i",))
    sign_in()
    return client


def movement(c: TestClient) -> tuple[str, dict[str, Any]]:
    slug = c.get(MV).json()["items"][0]["slug"]
    detail = c.get(f"{MV}/{slug}").json()["movement"]
    return slug, detail


def perfect_body(c: TestClient, **extra: Any) -> dict[str, Any]:
    slug, detail = movement(c)
    version = detail["versions"][0]
    spb = 60.0 / detail["tempo"]
    played = [{"midi": e["midi"], "time_s": e["start_beat"] * spb} for e in version["playback"]]
    body = {"movement": {"slug": slug, "level": version["level"]}, "played": played}
    return {**body, **extra}


def save_pass(c: TestClient, session_id: str | None = None, **extra: Any) -> dict[str, Any]:
    save = {"session_id": session_id or str(uuid.uuid4()), "pass_index": 0}
    r = c.post(SCORE, json=perfect_body(c, save=save, **extra))
    assert r.status_code == 200, r.text
    data: dict[str, Any] = r.json()
    return data


def test_scoring_without_save_stores_nothing(api: TestClient) -> None:
    assert api.post(SCORE, json=perfect_body(api)).json()["saved_id"] is None
    assert api.get(HIST).json()["total"] == 0


def test_saved_pass_appears_in_history_with_server_computed_figures(api: TestClient) -> None:
    out = save_pass(api)
    assert out["saved_id"] and out["accuracy"] == 1.0
    h = api.get(HIST).json()
    assert h["total"] == 1
    item = h["items"][0]
    assert item["id"] == out["saved_id"] and item["mode"] == "play"
    assert (
        item["accuracy"] == 1.0
        and item["hits"] == out["hits"]
        and item["tempo_bpm"] == out["tempo_bpm"]
    )
    assert item["tendency"] == out["timing"]["tendency"]


def test_progress_summarises_attempts(api: TestClient) -> None:
    save_pass(api)
    save_pass(api)
    (p,) = api.get(HIST).json()["progress"]
    assert p["attempts"] == 2 and p["best_accuracy"] == 1.0 and p["last_accuracy"] == 1.0
    assert p["mode"] == "play" and p["best_tempo_at_90"] is not None


def test_saving_needs_a_movement(api: TestClient) -> None:
    body = {
        "expected": [{"midi": 60, "start_beat": 0}],
        "played": [],
        "tempo_bpm": 120,
        "save": {"session_id": str(uuid.uuid4())},
    }
    assert api.post(SCORE, json=body).status_code == 422


def test_save_request_is_validated(api: TestClient) -> None:
    body = perfect_body(api, save={"session_id": "not-a-uuid"})
    assert api.post(SCORE, json=body).status_code == 422
    body = perfect_body(api, save={"session_id": str(uuid.uuid4()), "pass_index": 9999})
    assert api.post(SCORE, json=body).status_code == 422


def wait_body(c: TestClient, **over: Any) -> dict[str, Any]:
    slug, detail = movement(c)
    base = {
        "movement_slug": slug, "level": detail["versions"][0]["level"],
        "session_id": str(uuid.uuid4()), "steps": 4, "first_try": 3, "wrong_presses": 2,
    }  # fmt: skip
    return {**base, **over}


def test_wait_result_is_saved(api: TestClient) -> None:
    r = api.post(WAIT, json=wait_body(api))
    assert r.status_code == 201
    d = r.json()
    assert d["mode"] == "wait" and d["accuracy"] == 0.75 and d["expected"] == 4
    assert d["missed"] == 1 and d["extra"] == 2 and d["tempo_bpm"] is None
    (p,) = api.get(HIST).json()["progress"]
    assert p["mode"] == "wait" and p["best_tempo_at_90"] is None


@pytest.mark.parametrize(
    "bad",
    [
        {"first_try": 9},
        {"steps": 0},
        {"steps": 501},
        {"wrong_presses": -1},
        {"level": "godlike"},
        {"hands": "x"},
    ],
)
def test_bad_wait_results_are_422(api: TestClient, bad: dict[str, Any]) -> None:
    assert api.post(WAIT, json=wait_body(api, **bad)).status_code == 422


def test_wait_result_for_unknown_movement_is_404(api: TestClient) -> None:
    assert api.post(WAIT, json=wait_body(api, movement_slug="no-such")).status_code == 404


def test_history_is_private(api: TestClient, sign_in: Callable[..., None]) -> None:
    saved = save_pass(api)["saved_id"]
    sign_in(OTHER)
    assert api.get(HIST).json() == {"items": [], "progress": [], "total": 0}
    r = api.delete(f"/api/v1/practice/attempts/{saved}")
    assert r.status_code == 404 and r.json()["error"]["code"] == "attempt_not_found"
    assert api.delete(HIST).json() == {"deleted": 0}
    sign_in()
    assert api.get(HIST).json()["total"] == 1  # untouched by the other learner


def test_delete_one_and_delete_all(api: TestClient) -> None:
    first = save_pass(api)["saved_id"]
    save_pass(api)
    assert api.delete(f"/api/v1/practice/attempts/{first}").status_code == 204
    assert api.get(HIST).json()["total"] == 1
    assert api.delete(f"/api/v1/practice/attempts/{first}").status_code == 404
    save_pass(api)
    assert api.delete(HIST).json() == {"deleted": 2}
    assert api.get(HIST).json()["total"] == 0


def test_history_filters_by_movement(api: TestClient) -> None:
    save_pass(api)
    api.post(WAIT, json=wait_body(api))
    slug, _ = movement(api)
    assert api.get(HIST, params={"movement": slug}).json()["total"] == 2
    assert api.get(HIST, params={"movement": "other-slug"}).json()["total"] == 0


def test_requires_sign_in(client: TestClient) -> None:
    assert client.get(HIST).status_code == 401
    assert client.post(WAIT, json={}).status_code == 401
    assert client.delete(HIST).status_code == 401


def test_oldest_results_are_pruned(api: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(practice_service, "MAX_KEPT", 2)
    ids = [save_pass(api)["saved_id"] for _ in range(3)]
    kept = {i["id"] for i in api.get(HIST).json()["items"]}
    assert len(kept) == 2 and ids[2] in kept
