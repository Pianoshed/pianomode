"""Practice scoring API: explicit notes, published movements, hands, loops and validation."""

from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.models.user import User
from app.services import movement_service

URL = "/api/v1/practice/score"
MV = "/api/v1/movements"


@pytest.fixture
def api(
    client: TestClient, make_user: Callable[..., User], sign_in: Callable[..., None]
) -> TestClient:
    make_user()
    sign_in()
    return client


@pytest.fixture
def seeded(session_factory: sessionmaker[Session]) -> None:
    with session_factory() as s:
        movement_service.seed_default_movements(s, only=("ii_v_i",))


def explicit(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "expected": [
            {"midi": 60, "start_beat": 0, "hand": "R", "chord_index": 0},
            {"midi": 64, "start_beat": 0, "hand": "R", "chord_index": 0},
            {"midi": 48, "start_beat": 0, "hand": "L", "chord_index": 0},
            {"midi": 62, "start_beat": 1, "hand": "R", "chord_index": 1},
        ],
        "played": [
            {"midi": 60, "time_s": 0.0},
            {"midi": 64, "time_s": 0.03},
            {"midi": 48, "time_s": 0.0},
            {"midi": 63, "time_s": 0.52},
        ],
        "tempo_bpm": 120,
        "level": "intermediate",
    }
    return {**base, **over}


def post(c: TestClient, body: dict[str, Any], status: int = 200) -> dict[str, Any]:
    r = c.post(URL, json=body)
    assert r.status_code == status, r.text
    data: dict[str, Any] = r.json()
    return data


def test_requires_sign_in(client: TestClient) -> None:
    assert client.post(URL, json=explicit()).status_code == 401


def test_scores_explicit_notes(api: TestClient) -> None:
    d = post(api, explicit())
    assert d["source"] == "explicit" and d["tempo_bpm"] == 120 and d["window_ms"] == 150
    assert (d["expected"], d["hits"], d["near_miss"], d["missed"], d["extra"]) == (4, 3, 1, 0, 0)
    assert d["notes"][3]["status"] == "near_miss" and d["notes"][3]["played_midi"] == 63
    assert any("D#4 instead of D4" in f for f in d["feedback"])
    assert d["chords"][0]["complete"] is True and d["chords"][1]["complete"] is False
    assert {h["hand"] for h in d["hands"]} == {"L", "R"}
    assert any("Touch" in x for x in d["limits"])


def test_level_and_explicit_window(api: TestClient) -> None:
    assert post(api, explicit(level="beginner"))["window_ms"] == 250
    body = explicit()
    del body["level"]
    assert post(api, {**body, "window_ms": 80})["window_ms"] == 80
    assert post(api, body)["window_ms"] == 150  # default is intermediate


def test_timing_window_changes_the_result(api: TestClient) -> None:
    body = explicit(played=[{"midi": 60, "time_s": 0.2}], expected=[{"midi": 60, "start_beat": 0}])
    assert post(api, {**body, "level": "beginner"})["hits"] == 1
    assert post(api, {**body, "level": "advanced"})["hits"] == 0


def test_scores_against_a_published_movement(api: TestClient, seeded: None) -> None:
    movements = api.get(MV).json()["items"]
    slug = next(m["slug"] for m in movements if "intermediate" in m["levels"])
    detail = api.get(f"{MV}/{slug}").json()["movement"]
    version = next(v for v in detail["versions"] if v["level"] == "intermediate")
    beat_s = 60.0 / detail["tempo"]
    perfect = [
        {"midi": e["midi"], "time_s": 2.0 + e["start_beat"] * beat_s} for e in version["playback"]
    ]
    d = post(
        api,
        {
            "movement": {"slug": slug, "level": "intermediate"},
            "played": perfect,
            "offset_s": 2.0,
        },
    )
    assert d["source"] == "movement" and d["tempo_bpm"] == detail["tempo"]
    assert d["accuracy"] == 1.0 and d["extra"] == 0 and d["expected"] == len(version["playback"])
    assert d["chords"] and all(c["complete"] for c in d["chords"])


def test_movement_hand_selection_and_tempo_override(api: TestClient, seeded: None) -> None:
    slug = api.get(MV).json()["items"][0]["slug"]
    detail = api.get(f"{MV}/{slug}").json()["movement"]
    level = detail["versions"][0]["level"]
    version = detail["versions"][0]
    right = [e for e in version["playback"] if e["hand"] == "R"]
    beat_s = 60.0 / 60.0  # practised at half speed or so: 60 BPM
    played = [{"midi": e["midi"], "time_s": e["start_beat"] * beat_s} for e in right]
    d = post(
        api,
        {
            "movement": {"slug": slug, "level": level, "hands": "R"},
            "played": played,
            "tempo_bpm": 60,
        },
    )
    assert d["tempo_bpm"] == 60 and d["expected"] == len(right) and d["accuracy"] == 1.0
    assert {h["hand"] for h in d["hands"]} == {"R"}


def test_movement_in_another_key(api: TestClient, seeded: None) -> None:
    slug = api.get(MV).json()["items"][0]["slug"]
    detail = api.get(f"{MV}/{slug}?key=D").json()["movement"]
    version = detail["versions"][0]
    beat_s = 60.0 / detail["tempo"]
    played = [{"midi": e["midi"], "time_s": e["start_beat"] * beat_s} for e in version["playback"]]
    d = post(
        api,
        {
            "movement": {"slug": slug, "level": version["level"], "key": "D"},
            "played": played,
        },
    )
    assert d["accuracy"] == 1.0


def test_beat_range_scores_only_the_loop(api: TestClient) -> None:
    expected = [{"midi": 60 + i, "start_beat": i} for i in range(8)]
    played = [{"midi": 60 + i, "time_s": i * 0.5} for i in range(2, 5)]  # only beats 2-4 played
    whole = post(api, {"expected": expected, "played": played, "tempo_bpm": 120})
    assert whole["hits"] == 3 and whole["missed"] == 5
    loop = post(
        api, {"expected": expected, "played": played, "tempo_bpm": 120, "beat_range": [2, 5]}
    )
    assert loop["expected"] == 3 and loop["accuracy"] == 1.0 and loop["extra"] == 0


def test_latency_is_removed_when_given(api: TestClient) -> None:
    body = explicit(
        expected=[{"midi": 60, "start_beat": 0}],
        played=[{"midi": 60, "time_s": 0.09}],
    )
    assert post(api, body)["timing"]["mean_error_ms"] == 90.0
    assert post(api, {**body, "latency_ms": 90})["timing"]["mean_error_ms"] == 0.0


def test_octave_equivalence_is_opt_in(api: TestClient) -> None:
    body = explicit(expected=[{"midi": 60, "start_beat": 0}], played=[{"midi": 72, "time_s": 0.0}])
    assert post(api, body)["hits"] == 0
    assert post(api, {**body, "octave_equivalent": True})["hits"] == 1


@pytest.mark.parametrize(
    "bad",
    [
        {"expected": None},  # neither source
        {"movement": {"slug": "x", "level": "beginner"}},  # both sources
        {"tempo_bpm": None},  # explicit notes need a tempo
        {"level": "beginner", "window_ms": 100},  # both window settings
        {"level": "godlike"},
        {"tempo_bpm": 5},
        {"window_ms": 5},
        {"offset_s": -1},
        {"latency_ms": 900},
        {"beat_range": [1]},
        {"played": [{"midi": 200, "time_s": 0}]},
        {"played": [{"midi": 60, "time_s": -1}]},
        {"expected": [{"midi": 60, "start_beat": -1}]},
        {"surprise": True},
    ],
)
def test_bad_requests_are_422(api: TestClient, bad: dict[str, Any]) -> None:
    body = explicit()
    for k, v in bad.items():
        if v is None:
            body.pop(k, None)
        else:
            body[k] = v
    post(api, body, 422)


def test_engine_errors_have_stable_codes(api: TestClient) -> None:
    dup = explicit(
        expected=[{"midi": 60, "start_beat": 0}, {"midi": 60, "start_beat": 0}], played=[]
    )
    r = api.post(URL, json=dup)
    assert r.status_code == 422 and r.json()["error"]["code"] == "duplicate_expected_note"
    empty = api.post(
        URL, json=explicit(expected=[{"midi": 60, "start_beat": 0}], beat_range=[5, 9])
    )
    assert empty.status_code == 422 and empty.json()["error"]["code"] == "no_expected"
    backwards = api.post(URL, json=explicit(beat_range=[4, 2]))
    assert backwards.status_code == 422 and backwards.json()["error"]["code"] == "invalid_range"


def test_unknown_movement_and_version(api: TestClient, seeded: None) -> None:
    r = api.post(URL, json={"movement": {"slug": "no-such", "level": "beginner"}, "played": []})
    assert r.status_code == 404
    slug = api.get(MV).json()["items"][0]["slug"]
    levels = api.get(MV).json()["items"][0]["levels"]
    missing = next(
        (x for x in ("beginner", "intermediate", "advanced", "expert") if x not in levels), None
    )
    if missing:
        r = api.post(URL, json={"movement": {"slug": slug, "level": missing}, "played": []})
        assert r.status_code == 404 and r.json()["error"]["code"] == "version_not_found"


def test_scoring_is_repeatable(api: TestClient) -> None:
    assert post(api, explicit()) == post(api, explicit())
