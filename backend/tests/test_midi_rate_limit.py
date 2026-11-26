"""MIDI and audio analysis each have their own rate limit bucket, separate from the other heavy
theory routes (which share 30 a minute)."""

from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient

from app.models.user import User

P = "/api/v1/theory"
MIDI = {
    "ppq": 480,
    "events": [
        {"tick": 0, "kind": "note_on", "note": 60, "velocity": 80, "channel": 0, "track": 0},
        {"tick": 480, "kind": "note_off", "note": 60, "velocity": 0, "channel": 0, "track": 0},
    ],
}
AUDIO = {"regions": [{"start": 0, "end": 1, "label": "C:maj"}]}
HEAVY = {"chord": "C", "limit": 1}  # /voicings/generate, which shares the 30-a-minute bucket


@pytest.fixture
def api(
    client: TestClient, make_user: Callable[..., User], sign_in: Callable[..., None]
) -> TestClient:
    make_user()
    sign_in()
    return client


def test_midi_analysis_allows_sixty_a_minute_then_says_so(api: TestClient) -> None:
    codes = [api.post(f"{P}/midi/analyze", json=MIDI).status_code for _ in range(62)]
    assert codes[:60] == [200] * 60
    assert 429 in codes[60:]
    r = api.post(f"{P}/midi/analyze", json=MIDI)
    assert r.json()["error"]["code"] == "rate_limited" and r.headers["Retry-After"]


def test_using_up_midi_does_not_use_up_the_other_heavy_routes(api: TestClient) -> None:
    for _ in range(45):
        assert api.post(f"{P}/midi/analyze", json=MIDI).status_code == 200
    codes = [api.post(f"{P}/voicings/generate", json=HEAVY).status_code for _ in range(30)]
    assert codes == [200] * 30  # the shared bucket of 30 is untouched


def test_other_heavy_routes_still_stop_at_thirty(api: TestClient) -> None:
    codes = [api.post(f"{P}/voicings/generate", json=HEAVY).status_code for _ in range(32)]
    assert codes[:30] == [200] * 30 and 429 in codes[30:]
    # and midi and audio analysis are unaffected by that
    assert api.post(f"{P}/audio/interpret", json=AUDIO).status_code == 200
    assert api.post(f"{P}/midi/analyze", json=MIDI).status_code == 200


def test_audio_interpretation_allows_sixty_a_minute_then_says_so(api: TestClient) -> None:
    codes = [api.post(f"{P}/audio/interpret", json=AUDIO).status_code for _ in range(62)]
    assert codes[:60] == [200] * 60
    assert 429 in codes[60:]
    assert api.post(f"{P}/audio/interpret", json=AUDIO).json()["error"]["code"] == "rate_limited"


def test_audio_and_midi_buckets_are_independent_of_each_other(api: TestClient) -> None:
    for _ in range(50):
        assert api.post(f"{P}/audio/interpret", json=AUDIO).status_code == 200
    codes = [api.post(f"{P}/midi/analyze", json=MIDI).status_code for _ in range(55)]
    assert codes == [200] * 55
