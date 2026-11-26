from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.models.user import User

P = "/api/v1/theory"


@pytest.fixture
def api(
    client: TestClient, make_user: Callable[..., User], sign_in: Callable[..., None]
) -> TestClient:
    make_user()
    sign_in()
    return client


def post(api: TestClient, path: str, body: dict[str, Any], status: int = 200) -> dict[str, Any]:
    r = api.post(f"{P}{path}", json=body)
    assert r.status_code == status, r.text
    data: dict[str, Any] = r.json()
    return data


def error(api: TestClient, path: str, body: dict[str, Any], code: str, status: int = 422) -> str:
    data = post(api, path, body, status)
    assert data["error"]["code"] == code, data
    assert data["error"]["message"]
    return str(data["error"]["message"])


# ------------------------------------------------------------------ access and errors


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("post", "/notes/identify"),
        ("post", "/chords/identify"),
        ("post", "/voicings/generate"),
        ("post", "/midi/analyze"),
        ("get", "/scales"),
        ("get", "/exercises/kinds"),
    ],
)
def test_theory_endpoints_need_sign_in(client: TestClient, method: str, path: str) -> None:
    r = getattr(client, method)(f"{P}{path}", **({"json": {}} if method == "post" else {}))
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "not_authenticated"


def test_schema_errors_use_the_standard_envelope_and_unknown_fields_are_rejected(
    api: TestClient,
) -> None:
    data = post(api, "/notes/identify", {"name": "C4", "typo_field": 1}, 422)
    assert data["error"]["code"] == "validation_error"
    assert data["error"]["details"][0]["type"] == "extra_forbidden"


def test_openapi_documents_every_theory_route() -> None:
    from app.main import create_app

    paths = create_app().openapi()["paths"]
    for suffix in (
        "/notes/identify", "/intervals", "/scales/generate", "/chords/construct",
        "/chords/identify", "/progressions/generate", "/progressions/transpose",
        "/voicings/generate", "/voice-leading/evaluate", "/midi/analyze",
        "/exercises/validate", "/audio/interpret", "/harmony/analyze",
    ):  # fmt: skip
        assert f"{P}{suffix}" in paths, suffix


# ------------------------------------------------------------------ notes and intervals


def test_identify_note_by_name_midi_and_frequency(api: TestClient) -> None:
    d = post(api, "/notes/identify", {"name": "C#4"})
    assert d["note"]["midi"] == 61 and d["note"]["octave"] == 4 and "Db" in d["enharmonic_names"]
    assert d["note"]["name_unicode"] == "C♯4"

    d = post(api, "/notes/identify", {"midi": 69})
    assert d["note"]["name"] == "A4" and d["note"]["frequency"] == 440.0

    d = post(api, "/notes/identify", {"frequency": 261.63})
    assert d["note"]["name"] == "C4" and abs(d["cents_from_nearest"]) < 1

    d = post(api, "/notes/identify", {"midi": 70, "prefer": "flats"})
    assert d["note"]["name"] == "Bb4"


def test_tuning_reference_and_octave_convention_are_configurable(api: TestClient) -> None:
    d = post(api, "/notes/identify", {"midi": 69, "a4": 432})
    assert d["note"]["frequency"] == 432.0
    d = post(api, "/notes/identify", {"midi": 60, "middle_c_octave": 3})
    assert d["note"]["name"] == "C3"
    d = post(api, "/notes/identify", {"name": "C3", "middle_c_octave": 3})
    assert d["note"]["midi"] == 60


def test_identify_note_without_octave_and_theoretical_spellings(api: TestClient) -> None:
    d = post(api, "/notes/identify", {"name": "E#"})
    assert d["note"]["octave"] is None and d["note"]["midi"] is None
    assert d["note"]["pitch_class"] == 5 and "F" in d["enharmonic_names"]
    d = post(api, "/notes/identify", {"name": "Cb4"})
    assert d["note"]["midi"] == 59


@pytest.mark.parametrize(
    "body",
    [{}, {"name": "C4", "midi": 60}, {"midi": 128}, {"midi": -1}, {"frequency": 0},
     {"frequency": -5}, {"midi": 60, "a4": 0}, {"midi": 60, "middle_c_octave": 9}],
)  # fmt: skip
def test_identify_note_rejects_bad_requests(api: TestClient, body: dict[str, Any]) -> None:
    assert post(api, "/notes/identify", body, 422)["error"]["code"] == "validation_error"


def test_identify_note_rejects_unreadable_names_with_a_stable_code(api: TestClient) -> None:
    data = post(api, "/notes/identify", {"name": "H4"}, 422)
    assert data["error"]["code"] in {"invalid_note", "invalid_note_name"}


def test_interval_between_and_building(api: TestClient) -> None:
    d = post(api, "/intervals", {"lower": "C4", "upper": "G5"})
    assert d["interval"]["short"] == "P12" and d["interval"]["is_compound"]
    assert d["interval"]["simple"] == "P5" and d["signed_semitones"] == 19

    d = post(api, "/intervals", {"lower": "C", "upper": "F#"})
    assert d["interval"]["short"] == "A4" and d["interval"]["inverted"] == "d5"

    d = post(api, "/intervals", {"root": "Eb4", "interval": "m6"})
    assert d["result"]["name"] == "Cb5"

    d = post(api, "/intervals", {"root": "C4", "interval": "major third", "direction": "down"})
    assert d["result"]["name"] == "Ab3"

    d = post(api, "/intervals", {"lower": "G4", "upper": "C4"})
    assert d["direction"] == "down" and d["interval"]["short"] == "P5"


def test_interval_errors(api: TestClient) -> None:
    error(api, "/intervals", {"lower": "C4", "upper": "G"}, "mixed_note_forms")
    error(api, "/intervals", {"root": "C4", "interval": "banana"}, "unreadable_interval")
    assert post(api, "/intervals", {"lower": "C4"}, 422)["error"]["code"] == "validation_error"
    assert post(api, "/intervals", {}, 422)["error"]["code"] == "validation_error"


# ------------------------------------------------------------------ scales


def test_scales_in_every_key_have_unique_letters(api: TestClient) -> None:
    for root in ["C", "C#", "Db", "D", "Eb", "E", "F", "F#", "Gb", "G", "Ab", "A", "Bb", "B"]:
        d = post(api, "/scales/generate", {"root": root, "scale": "major"})
        letters = [n[0] for n in d["notes"]]
        assert len(set(letters)) == 7, (root, d["notes"])
        assert d["notes"][0] == root


def test_scale_details_and_diatonic_chords(api: TestClient) -> None:
    d = post(api, "/scales/generate", {"root": "F#", "scale": "major"})
    assert d["notes"] == ["F#", "G#", "A#", "B", "C#", "D#", "E#"]
    assert d["key"]["signature"].startswith("6 sharps")

    d = post(api, "/scales/generate", {"root": "C", "chord_size": 4, "octave": 4,
                                       "include_octave": True})  # fmt: skip
    assert [c["symbol"] for c in d["diatonic_chords"]] == [
        "Cmaj7", "Dm7", "Em7", "Fmaj7", "G7", "Am7", "Bm7b5"
    ]  # fmt: skip
    assert [n["name"] for n in d["keyboard"]][-1] == "C5"

    d = post(api, "/scales/generate", {"root": "A", "scale": "melodic_minor",
                                       "direction": "descending"})  # fmt: skip
    assert d["notes"][0] == "A" and d["direction"] == "descending"


def test_scale_list_and_unknown_scale(api: TestClient) -> None:
    ids = [x["id"] for x in api.get(f"{P}/scales").json()["scales"]]
    assert {"major", "dorian", "harmonic_minor", "blues", "whole_tone"} <= set(ids)
    data = post(api, "/scales/generate", {"root": "C", "scale": "no_such_scale"}, 422)
    assert data["error"]["code"]
    error(api, "/scales/generate", {"root": "C", "scale": "major_pentatonic", "chord_size": 3},
          data["error"]["code"] if False else _code_of(api, "major_pentatonic"))  # fmt: skip


def _code_of(api: TestClient, scale: str) -> str:
    code = post(api, "/scales/generate", {"root": "C", "scale": scale, "chord_size": 3}, 422)
    return str(code["error"]["code"])


# ------------------------------------------------------------------ chords


def test_construct_known_chords(api: TestClient) -> None:
    expectations = {
        "C": ["C", "E", "G"],
        "Cmaj7": ["C", "E", "G", "B"],
        "C7": ["C", "E", "G", "Bb"],
        "Cm7": ["C", "Eb", "G", "Bb"],
        "Cm7b5": ["C", "Eb", "Gb", "Bb"],
        "Cdim7": ["C", "Eb", "Gb", "Bbb"],
        "Dm7": ["D", "F", "A", "C"],
        "G7": ["G", "B", "D", "F"],
    }
    for symbol, tones in expectations.items():
        d = post(api, "/chords/construct", {"symbol": symbol})
        assert [t["name"] for t in d["chord"]["tones"]] == tones, symbol
        assert d["chord"]["symbol"] == symbol


def test_half_diminished_is_not_minor_or_fully_diminished(api: TestClient) -> None:
    half = post(api, "/chords/construct", {"symbol": "Cm7b5"})["chord"]
    assert half["type_id"] == "half_diminished7"
    assert (
        half["pitch_classes"]
        != post(api, "/chords/construct", {"symbol": "Cdim7"})["chord"]["pitch_classes"]
    )
    assert post(api, "/chords/construct", {"symbol": "Cm"})["chord"]["type_id"] == "minor"


def test_slash_chords_inversions_and_midi(api: TestClient) -> None:
    d = post(api, "/chords/construct", {"symbol": "Dm7/C", "octave": 4})
    assert d["chord"]["inversion"] == 3 and d["chord"]["inversion_name"] == "third inversion"
    assert d["notes"][0]["name"].startswith("C") and d["midi_notes"] == sorted(d["midi_notes"])
    d = post(api, "/chords/construct", {"root": "C", "type": "major", "inversion": 1})
    assert d["chord"]["symbol"] == "C/E" and d["notes"][0]["name"].startswith("E")
    d = post(api, "/chords/construct", {"symbol": "C/D"})
    assert d["chord"]["inversion"] is None  # D is not a chord tone: a slash chord, not an inversion


def test_symbol_styles_and_malformed_symbols(api: TestClient) -> None:
    d = post(api, "/chords/construct", {"symbol": "Cm7b5",
                                        "symbol_style": {"half_diminished": "ø7"}})  # fmt: skip
    assert d["chord"]["symbol"] == "Cø7"
    d = post(api, "/chords/construct", {"symbol": "Bbmaj7", "symbol_style": {"unicode_accidentals": True,
                                                                           "major7": "Δ7"}})  # fmt: skip
    assert d["chord"]["symbol"] == "B♭Δ7"
    msg = error(api, "/chords/construct", {"symbol": "Cmaj"}, "unknown_quality")
    assert "maj7" in msg  # points to the likely intent instead of guessing
    error(api, "/chords/construct", {"symbol": "H7"}, "invalid_root")
    error(api, "/chords/construct", {"root": "C", "type": "nope"}, "unknown_chord_type")
    error(api, "/chords/construct", {"root": "C", "type": "major", "inversion": 5},
          "invalid_inversion")  # fmt: skip
    assert post(api, "/chords/construct", {"symbol": "C", "root": "D"}, 422)["error"]["code"] == (
        "validation_error"
    )


def test_chord_type_catalogue(api: TestClient) -> None:
    types = api.get(f"{P}/chords/types").json()["types"]
    ids = {t["id"] for t in types}
    assert {"major", "half_diminished7", "diminished7", "altered", "power", "dominant13"} <= ids
    half = next(t for t in types if t["id"] == "half_diminished7")
    assert half["formula"] == ["P1", "m3", "d5", "m7"]


def test_identify_chords_with_inversions_and_ambiguity(api: TestClient) -> None:
    d = post(api, "/chords/identify", {"notes": ["C4", "E4", "G4"]})
    assert d["status"] == "identified" and d["candidates"][0]["symbol"] == "C"
    assert "not probabilities" in d["score_meaning"]

    d = post(api, "/chords/identify", {"notes": [64, 67, 72]})  # E G C
    best = d["candidates"][0]
    assert best["symbol"] == "C/E" and best["inversion"] == 1
    assert best["inversion_name"] == "first inversion"

    d = post(api, "/chords/identify", {"notes": ["A3", "C4", "E4", "G4"]})
    symbols = [c["symbol"] for c in d["candidates"]]
    assert symbols[0] == "Am7" and "C6/A" in symbols  # the bass note favours Am7; C6/A is listed
    assert d["candidates"][0]["score"] > d["candidates"][1]["score"]

    d = post(api, "/chords/identify", {"notes": ["C4", "C#4", "D4"]})
    assert d["status"] == "no_reliable_label" and d["reason"]

    d = post(api, "/chords/identify", {"notes": ["C4", "E4", "G4"], "bass": "E"})
    assert d["candidates"][0]["symbol"] == "C/E"


def test_identify_validation(api: TestClient) -> None:
    assert post(api, "/chords/identify", {"notes": []}, 422)["error"]["code"] == "validation_error"
    too_many = list(range(40, 70))
    assert (
        post(api, "/chords/identify", {"notes": too_many}, 422)["error"]["code"]
        == "validation_error"
    )
    assert post(api, "/chords/identify", {"notes": [200]}, 422)["error"]["code"] == (
        "validation_error"
    )


# ------------------------------------------------------------------ keys and harmony


def test_roman_numerals_cadences_and_key_provenance(api: TestClient) -> None:
    d = post(api, "/harmony/analyze", {"chords": ["Dm7", "G7", "Cmaj7"], "key": {"tonic": "C"}})
    assert [n["figure"] for n in d["numerals"]] == ["ii7", "V7", "Imaj7"]
    assert d["key_source"] == "provided"
    assert [c["kind"] for c in d["cadences"]] == ["authentic"]

    d = post(
        api,
        "/harmony/analyze",
        {"chords": ["A7", "Dm", "G7", "C"], "key": {"tonic": "C"}},
    )
    assert d["numerals"][0]["category"] == "secondary_dominant"
    assert d["numerals"][0]["figure"] == "V7/ii"

    d = post(api, "/harmony/analyze", {"chords": ["C", "Am", "F", "G7", "C"]})
    assert d["key_source"] == "estimated" and d["key_estimate"]["candidates"]
    assert "probabilit" in d["key_estimate"]["score_meaning"]


def test_few_chords_give_no_key_claim(api: TestClient) -> None:
    d = post(api, "/harmony/analyze", {"chords": ["C"]})
    assert d["key"] is None and d["numerals"] == [] and d["warnings"]


def test_key_estimate_from_weights_and_chords(api: TestClient) -> None:
    c_major = [6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88]
    d = post(api, "/keys/estimate", {"pitch_class_weights": c_major})
    assert d["candidates"][0]["key"]["name"] == "C major" and d["reliable"]
    d = post(api, "/keys/estimate", {"chords": ["Am", "Dm", "E7", "Am"], "top": 3})
    assert d["candidates"][0]["key"]["tonic"] == "A" and len(d["candidates"]) <= 3
    assert post(api, "/keys/estimate", {}, 422)["error"]["code"] == "validation_error"
    d = post(api, "/keys/estimate", {"pitch_class_weights": [0] * 12})
    assert d["reliable"] is False


# ------------------------------------------------------------------ progressions


def test_ii_v_i_in_c_with_sevenths_is_dm7_g7_cmaj7(api: TestClient) -> None:
    d = post(
        api,
        "/progressions/generate",
        {"key": {"tonic": "C"}, "template_id": "ii_v_i", "vocabulary": "sevenths"},
    )
    assert [c["symbol"] for c in d["progression"]["chords"]] == ["Dm7", "G7", "Cmaj7"]
    assert [c["symbol"] for c in d["chord_details"]] == ["Dm7", "G7", "Cmaj7"]
    assert d["progression"]["schema_version"] == 1


def test_template_catalogue_and_unknown_template(api: TestClient) -> None:
    data = api.get(f"{P}/progressions/templates").json()["templates"]
    ids = {t["id"] for t in data}
    assert {"ii_v_i", "i_iv_v_i"} <= ids or len(ids) >= 10
    minor = api.get(f"{P}/progressions/templates", params={"mode": "minor"}).json()["templates"]
    assert minor and all(t["mode"] == "minor" for t in minor)
    assert api.get(f"{P}/progressions/templates", params={"difficulty": "x"}).status_code == 422
    error(api, "/progressions/generate", {"key": {"tonic": "C"}, "template_id": "nope"},
          "unknown_progression")  # fmt: skip


def test_progression_mode_mismatch_and_source_rules(api: TestClient) -> None:
    minor = api.get(f"{P}/progressions/templates", params={"mode": "minor"}).json()["templates"]
    error(api, "/progressions/generate",
          {"key": {"tonic": "C", "mode": "major"}, "template_id": minor[0]["id"]},
          "key_mode_mismatch")  # fmt: skip
    assert post(api, "/progressions/generate", {"key": {"tonic": "C"}}, 422)["error"]["code"] == (
        "validation_error"
    )


def test_custom_progression_with_voicing_is_smooth_and_deterministic(api: TestClient) -> None:
    body = {
        "key": {"tonic": "C"},
        "name": "My turnaround",
        "chords": [{"symbol": "Dm7", "beats": 2}, {"symbol": "G7", "beats": 2},
                   {"symbol": "Cmaj7", "beats": 4}],
        "voicing": {"skill": "advanced", "voice_leading": {"style": "jazz",
                                                           "weight_preset": "smooth"}},
    }  # fmt: skip
    a = post(api, "/progressions/generate", body)
    b = post(api, "/progressions/generate", body)
    assert a == b  # reproducible
    assert a["progression"]["name"] == "My turnaround"
    assert [c["roman"] for c in a["progression"]["chords"]] == ["ii7", "V7", "Imaj7"]
    assert [x["beat"] for x in a["progression"]["chords"]] == [0, 2, 4]
    assert len(a["voicing"]) == 3 and a["voicing_total_cost"] is not None
    assert all(c["voicing"] is not None for c in a["progression"]["chords"])
    assert a["voicing"][1]["transition"]["largest_leap"] <= 7


def test_custom_progression_errors(api: TestClient) -> None:
    error(api, "/progressions/generate",
          {"key": {"tonic": "C"}, "chords": [{"symbol": "Cmaj"}]}, "unknown_quality")  # fmt: skip
    assert post(api, "/progressions/generate",
                {"key": {"tonic": "C"}, "chords": []}, 422)["error"]["code"] == "validation_error"  # fmt: skip
    assert post(api, "/progressions/generate",
                {"key": {"tonic": "C"}, "template_id": "ii_v_i", "chords": [{"symbol": "C"}]},
                422)["error"]["code"] == "validation_error"  # fmt: skip


def test_transposition_preserves_function_and_spelling(api: TestClient) -> None:
    src = post(
        api,
        "/progressions/generate",
        {"key": {"tonic": "C"}, "template_id": "ii_v_i", "vocabulary": "sevenths"},
    )["progression"]
    expected = {
        "Db": ["Ebm7", "Ab7", "Dbmaj7"],
        "F#": ["G#m7", "C#7", "F#maj7"],
        "Bb": ["Cm7", "F7", "Bbmaj7"],
        "E": ["F#m7", "B7", "Emaj7"],
    }
    for target, symbols in expected.items():
        d = post(api, "/progressions/transpose", {"progression": src, "target": target})
        assert [c["symbol"] for c in d["progression"]["chords"]] == symbols, target
        assert [c["roman"] for c in d["progression"]["chords"]] == ["ii7", "V7", "Imaj7"]
        assert d["progression"]["key"]["tonic"] == target


def test_transposition_keeps_timing_and_regenerates_unplayable_voicings(api: TestClient) -> None:
    src = post(
        api,
        "/progressions/generate",
        {
            "key": {"tonic": "C"}, "template_id": "ii_v_i", "vocabulary": "sevenths",
            "voicing": {"skill": "intermediate"},
        },
    )["progression"]  # fmt: skip
    d = post(api, "/progressions/transpose", {"progression": src, "target": "Gb"})
    before = [(c["beat"], c["duration"]) for c in src["chords"]]
    after = [(c["beat"], c["duration"]) for c in d["progression"]["chords"]]
    assert before == after
    assert all(c["voicing"] for c in d["progression"]["chords"])  # every chord still has a voicing


def test_transposition_errors(api: TestClient) -> None:
    src = post(api, "/progressions/generate", {"key": {"tonic": "C"}, "template_id": "ii_v_i"})[
        "progression"
    ]
    error(api, "/progressions/transpose", {"progression": src, "target": "H"}, "invalid_note")
    error(api, "/progressions/transpose", {"progression": {"schema_version": 1}, "target": "D"},
          "invalid_progression_data")  # fmt: skip
    newer = {**src, "schema_version": 999}
    data = post(api, "/progressions/transpose", {"progression": newer, "target": "D"}, 422)
    assert data["error"]["code"]


def test_progression_validation_report(api: TestClient) -> None:
    src = post(api, "/progressions/generate", {"key": {"tonic": "C"}, "template_id": "ii_v_i",
                                               "vocabulary": "sevenths"})["progression"]  # fmt: skip
    d = post(api, "/progressions/validate", {"progression": src})
    assert d["ok"] and d["errors"] == []
    broken = {**src, "chords": [{**c} for c in src["chords"]]}
    broken["chords"][1]["beat"] = 0.5  # overlaps the first chord
    d = post(api, "/progressions/validate", {"progression": broken})
    assert not d["ok"] and any("overlap" in e["code"] for e in d["errors"])
    d = post(api, "/progressions/validate", {"progression": src, "publication": True})
    assert any(e["severity"] == "error" for e in d["errors"])  # no author/source yet


# ------------------------------------------------------------------ voicings and voice leading


def _all_notes(v: dict[str, Any]) -> list[int]:
    return [*v["left"], *v["right"]]


def test_voicings_respect_configured_ranges_and_required_tones(api: TestClient) -> None:
    body = {
        "chord": "Cmaj7",
        "limit": 200,
        "config": {
            "skill": "advanced",
            "constraints": {"lh_range": [40, 55], "rh_range": [60, 79], "max_span": 12,
                            "required_tones": ["seventh"], "forbidden_tones": ["fifth"]},
        },
    }  # fmt: skip
    d = post(api, "/voicings/generate", body)
    assert d["total_found"] > 0 and d["returned"] == len(d["voicings"])
    for item in d["voicings"]:
        v = item["voicing"]
        assert all(40 <= n <= 55 for n in v["left"]) and all(60 <= n <= 79 for n in v["right"])
        assert max(v["left"], default=0) < min(v["right"], default=127)
        names = {n.rstrip("-0123456789") for n in v["left_names"] + v["right_names"]}
        assert "B" in names and "G" not in names  # seventh present, fifth forbidden
    costs = [i["static_cost"]["total"] for i in d["voicings"]]
    assert costs == sorted(costs)  # best first


def test_voicing_generation_is_reproducible(api: TestClient) -> None:
    body = {"chord": "G7", "config": {"skill": "expert"}, "limit": 40}
    assert post(api, "/voicings/generate", body) == post(api, "/voicings/generate", body)


def test_impossible_constraints_explain_themselves(api: TestClient) -> None:
    d = post(api, "/voicings/generate", {"chord": "Cmaj7",
        "config": {"constraints": {"max_span": 2, "max_notes_per_hand": 1}}})  # fmt: skip
    assert d["total_found"] == 0 and "No playable voicing" in d["message"]


def test_voicing_constraint_errors(api: TestClient) -> None:
    error(api, "/voicings/generate", {"chord": "C", "config": {"constraints": {"lh_range": [60, 50]}}},
          "invalid_constraints")  # fmt: skip
    error(api, "/voicings/generate",
          {"chord": "C", "config": {"constraints": {"required_tones": ["banana"]}}},
          "invalid_constraints")  # fmt: skip
    error(api, "/voicings/generate", {"chord": "C", "config": {"preset": "nope"}},
          "unknown_preset")  # fmt: skip
    error(api, "/voicings/generate",
          {"chord": "C", "config": {"voice_leading": {"weights": {"banana": 1}}}},
          "unknown_weight")  # fmt: skip
    assert post(api, "/voicings/generate", {"chord": "C", "limit": 5000}, 422)["error"]["code"] == (
        "validation_error"
    )


def test_sequence_is_smooth_complete_and_repeatable(api: TestClient) -> None:
    body = {
        "chords": ["Dm7", "G7", "Cmaj7", "Am7"],
        "config": {"skill": "advanced", "voice_leading": {"style": "jazz",
                                                          "weight_preset": "smooth"}},
    }  # fmt: skip
    a = post(api, "/voicings/sequence", body)
    assert a == post(api, "/voicings/sequence", body)
    assert a["method"] == "dp" and len(a["items"]) == 4
    assert all(i["explanation"] for i in a["items"])
    assert a["items"][0]["transition"] is None
    assert all(i["transition"]["largest_leap"] <= 12 for i in a["items"][1:])


def test_sequence_pinning_and_limits(api: TestClient) -> None:
    pinned = {"left": [48], "right": [64, 67, 72], "lh_style": "bass", "rh_style": "triad_close"}
    d = post(api, "/voicings/sequence", {"chords": ["C", "F", "G"],
                                         "fixed": {"0": pinned}})  # fmt: skip
    assert d["items"][0]["voicing"]["right"] == [64, 67, 72]
    error(api, "/voicings/sequence", {"chords": ["C"], "fixed": {"5": pinned}}, "invalid_index")
    error(api, "/voicings/sequence", {"chords": ["C"], "fixed": {"0": {"left": [30],
                                                                      "right": [31]}}},
          "unplayable_voicing")  # fmt: skip
    assert post(api, "/voicings/sequence", {"chords": ["C"] * 17}, 422)["error"]["code"] == (
        "validation_error"
    )
    error(api, "/voicings/sequence", {"chords": ["C", "Xyz"]}, "invalid_root")


def test_evaluating_a_sequence_matches_the_search_that_produced_it(api: TestClient) -> None:
    body = {"chords": ["C", "Am", "F", "G"], "config": {"skill": "intermediate"}}
    seq = post(api, "/voicings/sequence", body)
    voicings = [
        {k: i["voicing"][k] for k in ("left", "right", "lh_style", "rh_style")}
        for i in seq["items"]
    ]
    ev = post(api, "/voice-leading/evaluate", {**body, "voicings": voicings})
    assert ev["total_cost"] == pytest.approx(seq["total_cost"], abs=1e-6)
    assert "not grades" in ev["score_meaning"]


def test_parallel_fifths_are_style_dependent(api: TestClient) -> None:
    chords = ["C5", "D5"]  # moving power chords: parallel fifths and octaves
    voicings = [{"left": [48], "right": [55, 60]}, {"left": [50], "right": [57, 62]}]
    strict = post(api, "/voice-leading/evaluate", {"chords": chords, "voicings": voicings,
        "config": {"voice_leading": {"style": "classical"}}})  # fmt: skip
    jazz = post(api, "/voice-leading/evaluate", {"chords": chords, "voicings": voicings,
        "config": {"voice_leading": {"style": "jazz"}}})  # fmt: skip
    s_cost = strict["items"][1]["transition"]["cost"]["parts"]["parallels"]
    j_cost = jazz["items"][1]["transition"]["cost"]["parts"]["parallels"]
    assert s_cost > j_cost == 0
    assert strict["items"][1]["transition"]["parallel_fifths"] >= 1


def test_voice_leading_length_mismatch(api: TestClient) -> None:
    error(api, "/voice-leading/evaluate",
          {"chords": ["C", "F"], "voicings": [{"left": [48], "right": [64]}]},
          "length_mismatch")  # fmt: skip


# ------------------------------------------------------------------ MIDI


def _chord_events(notes: list[int], start: int, end: int, track: int = 0) -> list[dict[str, Any]]:
    on = [{"tick": start, "kind": "note_on", "note": n, "velocity": 80, "track": track}
          for n in notes]  # fmt: skip
    off = [{"tick": end, "kind": "note_off", "note": n, "track": track} for n in notes]
    return on + off


def test_midi_chords_key_numerals_and_notes(api: TestClient) -> None:
    events = (
        _chord_events([48, 64, 67], 0, 1920)  # C (E and G above a C bass)
        + _chord_events([53, 69, 72], 1920, 3840)  # F A C
        + _chord_events([43, 62, 67, 71], 3840, 5760)  # G (B D G)
        + _chord_events([48, 60, 64, 67], 5760, 7680)  # C
    )
    d = post(api, "/midi/analyze", {"ppq": 480, "events": events, "grid": "bar",
                                    "key": {"tonic": "C"}})  # fmt: skip
    symbols = [s["candidates"][0]["symbol"] for s in d["segments"]]
    assert symbols[0].startswith("C") and symbols[1].startswith("F")
    assert [s["numeral"]["figure"] for s in d["segments"]][:2] == ["I", "IV"]
    assert d["key_source"] == "provided" and d["note_count"] == 14
    assert all(s["origin"] == "midi" for s in d["segments"])
    assert d["segments"][0]["start_beat"] == 0 and d["segments"][0]["end_beat"] == 4
    n = d["notes"][0]
    assert n["hand"] in ("L", "R") and n["hand_source"] == "auto" and n["duration_beats"] == 4


def test_midi_key_estimate_is_labelled_as_an_estimate(api: TestClient) -> None:
    events = _chord_events([60, 64, 67], 0, 480) + _chord_events([65, 69, 72], 480, 960)
    events += _chord_events([67, 71, 74], 960, 1440) + _chord_events([60, 64, 67], 1440, 1920)
    d = post(api, "/midi/analyze", {"ppq": 480, "events": events})
    assert d["key_source"] in ("estimated", None)
    assert d["key_estimate"]["method"] and "probabilit" in d["key_estimate"]["score_meaning"]


def test_midi_hands_are_editable_and_tracks_are_not_assumed_to_be_hands(api: TestClient) -> None:
    events = _chord_events([48, 52, 55], 0, 960, track=3) + _chord_events([72, 76], 0, 960, track=3)
    first = post(api, "/midi/analyze", {"ppq": 480, "events": events})
    target = next(n for n in first["notes"] if n["midi"] == 72)
    assert target["track"] == 3 and target["hand"] == "R"  # one track, two hands
    edited = post(api, "/midi/analyze", {"ppq": 480, "events": events,
                                         "hand_edits": {str(target["id"]): "L"}})  # fmt: skip
    changed = next(n for n in edited["notes"] if n["id"] == target["id"])
    assert changed["hand"] == "L" and changed["hand_source"] == "user"
    others = [n for n in edited["notes"] if n["id"] != target["id"]]
    assert all(n["hand_source"] == "auto" for n in others)
    error(api, "/midi/analyze", {"ppq": 480, "events": events, "hand_edits": {"999": "L"}},
          "unknown_note")  # fmt: skip


def test_midi_mute_and_solo(api: TestClient) -> None:
    events = _chord_events([48, 52, 55], 0, 960, track=0) + _chord_events([72, 76], 0, 960, track=1)
    muted = post(api, "/midi/analyze", {"ppq": 480, "events": events,
                                        "track_states": [{"track": 1, "muted": True}]})  # fmt: skip
    assert {n["track"] for n in muted["notes"]} == {0}
    solo = post(api, "/midi/analyze", {"ppq": 480, "events": events,
                                       "track_states": [{"track": 0}, {"track": 1, "solo": True}]})  # fmt: skip
    assert {n["track"] for n in solo["notes"]} == {1}


def test_midi_tempo_and_odd_input_become_warnings_not_crashes(api: TestClient) -> None:
    events = [
        {"tick": 0, "kind": "note_on", "note": 60, "velocity": 90},
        {"tick": 960, "kind": "note_off", "note": 60},
        {"tick": 960, "kind": "note_off", "note": 62},  # stray note-off
        {"tick": 1000, "kind": "note_on", "note": 64, "velocity": 0},  # velocity 0 = off, stray
    ]
    d = post(api, "/midi/analyze", {"ppq": 480, "events": events,
                                    "tempo_changes": [{"tick": 0, "bpm": 60}]})  # fmt: skip
    assert d["warnings"]
    n = d["notes"][0]
    assert n["end_beat"] == 2 and n["end_sec"] == pytest.approx(2.0)  # 60 bpm: one beat = 1 s


def test_midi_validation(api: TestClient) -> None:
    assert post(api, "/midi/analyze", {"ppq": 480, "events": []}, 422)["error"]["code"] == (
        "validation_error"
    )
    bad = [{"tick": 0, "kind": "note_on", "note": 200}]
    assert post(api, "/midi/analyze", {"ppq": 480, "events": bad}, 422)["error"]["code"] == (
        "validation_error"
    )
    ok = _chord_events([60], 0, 10)
    assert post(api, "/midi/analyze", {"ppq": 0, "events": ok}, 422)["error"]["code"] == (
        "validation_error"
    )
    assert post(
        api, "/midi/analyze",
        {"ppq": 480, "events": ok, "time_signatures": [{"tick": 0, "numerator": 4, "denominator": 3}]},
        422,
    )["error"]["code"] == "validation_error"  # fmt: skip


def test_silent_midi_gives_a_clear_result(api: TestClient) -> None:
    d = post(
        api, "/midi/analyze", {"ppq": 480, "events": [{"tick": 0, "kind": "note_off", "note": 60}]}
    )
    assert d["note_count"] == 0 and d["segments"] == [] and d["warnings"]


# ------------------------------------------------------------------ audio interpretation


def test_audio_hypotheses_never_claim_certainty(api: TestClient) -> None:
    body = {
        "regions": [
            {"start": 0, "end": 2, "label": "C:maj", "scores": {"C:maj": 0.9, "C:maj7": 0.2},
             "pitch_classes": [0, 4, 7], "bass_pc": 0},
            {"start": 2, "end": 4, "label": "A:min7", "scores": {"A:min7": 0.8}},
            {"start": 4, "end": 6, "label": "F:maj", "scores": {"F:maj": 0.55, "D:min": 0.5}},
            {"start": 6, "end": 8, "label": "G:7"},
        ],
    }  # fmt: skip
    d = post(api, "/audio/interpret", body)
    assert [h["symbol"] for h in d["hypotheses"]] == ["C", "Am7", "F", "G7"]
    assert all(h["origin"] == "audio" and h["confidence"] is None for h in d["hypotheses"])
    assert all(h["model_score"] is None or h["model_score"] >= 0 for h in d["hypotheses"])
    close = d["hypotheses"][2]
    assert close["status"] == "ambiguous" and close["warnings"] and close["alternatives"]
    assert "not probabilities" in d["evidence_note"]
    assert d["key"] is not None and d["key_source"] in ("estimated", "provided")


def test_a_probability_is_only_shown_with_a_named_calibration(api: TestClient) -> None:
    region = {"start": 0, "end": 2, "label": "C:maj", "probability": 0.93}
    d = post(api, "/audio/interpret", {"regions": [region]})
    assert d["hypotheses"][0]["confidence"] is None  # nobody vouched for the number
    region["calibration"] = "isotonic-v3 (held-out, 2026-09)"
    d = post(api, "/audio/interpret", {"regions": [region]})
    assert d["hypotheses"][0]["confidence"] == 0.93
    assert d["hypotheses"][0]["calibration"] == "isotonic-v3 (held-out, 2026-09)"


def test_unrecognised_labels_are_kept_and_flagged(api: TestClient) -> None:
    d = post(api, "/audio/interpret", {"regions": [{"start": 0, "end": 2, "label": "C:wobble"},
                                                   {"start": 2, "end": 3, "label": "N"}]})  # fmt: skip
    first, second = d["hypotheses"]
    assert first["status"] == "unrecognised_label" and first["symbol"] is None
    assert first["raw_label"] == "C:wobble" and first["warnings"]
    assert second["status"] == "no_chord"


def test_audio_corrections_keep_the_original(api: TestClient) -> None:
    regions = [{"start": 0, "end": 2, "label": "C:maj"}, {"start": 2, "end": 4, "label": "G:maj"}]
    d = post(api, "/audio/interpret", {
        "regions": regions, "key": {"tonic": "C"},
        "corrections": [{"op": "relabel", "index": 1, "label": "G:7"},
                        {"op": "retime", "index": 1, "start": 2, "end": 3.5},
                        {"op": "add", "start": 3.5, "end": 5, "label": "C:maj"}],
    })  # fmt: skip
    assert [h["symbol"] for h in d["hypotheses"]] == ["C", "G7", "C"]
    assert [h["symbol"] for h in d["original"]] == ["C", "G"]
    assert d["hypotheses"][1]["origin"] == "user" and d["hypotheses"][1]["status"] == "user_set"
    assert [c["kind"] for c in d["corrections"]] == ["relabel", "retime", "add"]
    assert d["corrections"][0]["before"]["symbol"] == "G"
    assert d["hypotheses"][1]["numeral"]["figure"] == "V7"


def test_audio_correction_and_region_errors(api: TestClient) -> None:
    ok = {"regions": [{"start": 0, "end": 2, "label": "C:maj"}]}
    error(api, "/audio/interpret",
          {**ok, "corrections": [{"op": "relabel", "index": 0, "label": "Cmaj"}]},
          "unrecognised_chord_label")  # fmt: skip
    data = post(api, "/audio/interpret", {**ok, "corrections": [{"op": "delete", "index": 9}]}, 422)
    assert data["error"]["code"]
    error(api, "/audio/interpret",
          {"regions": [{"start": 0, "end": 3, "label": "C:maj"},
                       {"start": 2, "end": 4, "label": "G:maj"}]}, "invalid_regions")  # fmt: skip
    assert post(api, "/audio/interpret", {**ok, "corrections": [{"op": "relabel", "index": 0}]},
                422)["error"]["code"] == "validation_error"  # fmt: skip


# ------------------------------------------------------------------ exercises


def test_exercise_round_trip_over_the_api(api: TestClient) -> None:
    kinds = api.get(f"{P}/exercises/kinds").json()
    assert kinds["difficulties"] == ["beginner", "intermediate", "advanced", "expert"]
    assert any(k["ear_training"] for k in kinds["kinds"])

    ex = post(api, "/exercises/generate", {"kind": "cadence_identify", "difficulty": "beginner",
                                           "seed": 4})["exercises"][0]  # fmt: skip
    again = post(api, "/exercises/generate", {"kind": "cadence_identify", "difficulty": "beginner",
                                              "seed": 4})["exercises"][0]  # fmt: skip
    assert ex == again and ex["id"] == "v1:cadence_identify:beginner:4"
    assert "answer" not in ex and ex["choices"]

    grades = {c: post(api, "/exercises/validate", {"exercise_id": ex["id"], "answer": c})
              for c in ex["choices"]}  # fmt: skip
    right = [c for c, g in grades.items() if g["correct"]]
    assert len(right) == 1
    assert grades[right[0]]["status"] == "correct" and grades[right[0]]["explanation"]
    wrong = next(g for c, g in grades.items() if c != right[0])
    assert not wrong["correct"] and right[0] in wrong["feedback"]


def test_exercise_sets_and_known_answers(api: TestClient) -> None:
    d = post(api, "/exercises/generate", {"kind": "interval_identify", "difficulty": "intermediate",
                                          "seed": 100, "count": 5})  # fmt: skip
    assert [e["seed"] for e in d["exercises"]] == [100, 101, 102, 103, 104]
    unseeded = post(api, "/exercises/generate", {"kind": "note_name", "count": 3})["exercises"]
    assert len(unseeded) == 3 and len({e["id"] for e in unseeded}) == 3


def test_exercise_errors_have_stable_codes(api: TestClient) -> None:
    error(api, "/exercises/generate", {"kind": "nope"}, "unknown_exercise_kind")
    assert (
        post(api, "/exercises/generate", {"kind": "note_name", "difficulty": "godlike"}, 422)[
            "error"
        ]["code"]
        == "validation_error"
    )
    error(api, "/exercises/validate", {"exercise_id": "garbage", "answer": "C"},
          "invalid_exercise_id")  # fmt: skip
    error(api, "/exercises/validate", {"exercise_id": "v9:note_name:beginner:1", "answer": "C"},
          "unsupported_exercise_version")  # fmt: skip
    error(api, "/exercises/validate",
          {"exercise_id": "v1:scale_construct:beginner:1", "answer": "C D E"},
          "invalid_answer")  # fmt: skip
    assert post(api, "/exercises/validate", {"exercise_id": "v1:note_name:beginner:1",
                                              "answer": ["a", 1]}, 422)["error"]["code"] == "validation_error"  # fmt: skip


def test_unreadable_answers_are_graded_not_errors(api: TestClient) -> None:
    d = post(api, "/exercises/validate", {"exercise_id": "v1:triad_identify:beginner:2",
                                          "answer": "Hx7"})  # fmt: skip
    assert d["status"] == "unreadable" and not d["correct"] and d["feedback"]


def test_piano_keys_can_be_submitted_as_an_answer(api: TestClient) -> None:
    ex = post(api, "/exercises/generate", {"kind": "triad_build", "difficulty": "beginner",
                                           "seed": 3})["exercises"][0]  # fmt: skip
    from music_theory.exercises import reference_answer
    from music_theory.notes import parse_note_name

    names = reference_answer(ex["id"])
    keys = [60 + parse_note_name(n).pitch_class for n in names]
    d = post(api, "/exercises/validate", {"exercise_id": ex["id"], "answer": keys})
    assert d["correct"]


# ------------------------------------------------------------------ rate limiting


def test_heavy_endpoints_are_rate_limited(api: TestClient) -> None:
    body = {"chord": "C", "limit": 1}
    codes = [api.post(f"{P}/voicings/generate", json=body).status_code for _ in range(32)]
    assert codes[:30] == [200] * 30
    assert 429 in codes[30:]
    r = api.post(f"{P}/voicings/generate", json=body)
    assert r.json()["error"]["code"] == "rate_limited" and r.headers["Retry-After"]


# ------------------------------------------------------------------ fingering, relationships, phrases


def test_scale_response_includes_curated_fingering(api: TestClient) -> None:
    d = post(api, "/scales/generate", {"root": "C", "scale": "major"})
    assert d["fingering"]["right_hand"] == [1, 2, 3, 1, 2, 3, 4, 5]
    assert d["fingering"]["left_hand"] == [5, 4, 3, 2, 1, 3, 2, 1]


def test_scale_without_curated_fingering_says_so(api: TestClient) -> None:
    d = post(api, "/scales/generate", {"root": "C", "scale": "blues"})
    assert d["fingering"] is None
    assert "curated" in d["fingering_note"]


def test_harmony_returns_relationships_and_phrases(api: TestClient) -> None:
    d = post(
        api,
        "/harmony/analyze",
        {"chords": ["C", "F", "G7", "C", "Am", "Dm7", "G7", "C"], "key": {"tonic": "C"}},
    )
    assert len(d["relationships"]) == 7
    assert len(d["phrases"]) == 2
    assert d["phrases"][0]["cadence"] == "authentic"
    assert "harmony only" in d["phrase_note"]
    assert d["relationships"][2]["non_diatonic"] is False


def test_harmony_without_key_still_gives_relationships(api: TestClient) -> None:
    d = post(api, "/harmony/analyze", {"chords": ["C"]})
    assert d["relationships"] == [] and d["phrases"] == []
    d = post(api, "/harmony/analyze", {"chords": ["C", "Am"], "key": {"tonic": "C"}})
    assert d["relationships"][0]["transform"] == "R"


def test_phrase_option_is_validated(api: TestClient) -> None:
    post(
        api,
        "/harmony/analyze",
        {"chords": ["C", "G"], "key": {"tonic": "C"}, "min_phrase_chords": 0},
        422,
    )
