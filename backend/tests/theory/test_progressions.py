import json
import math
from dataclasses import replace

import pytest

from music_theory import progressions as prog_module
from music_theory.chord_symbols import parse_chord as P
from music_theory.errors import TheoryError
from music_theory.key_analysis import ALL_KEYS
from music_theory.keys import Key
from music_theory.notes import parse_note_name as N
from music_theory.progressions import (
    Progression,
    PublicationMeta,
    TemplateError,
    default_library,
    generate_progression,
    insert_passing_diminished,
    insert_secondary_dominant,
    load_templates,
    make_progression,
    migrate_progression_data,
    progression_from_dict,
    progression_to_dict,
    realize,
    substitute_tritone,
    transpose_progression,
    transpose_to_all_keys,
    validate_progression,
    voice_progression,
    walking_bass,
    with_analysis,
)
from music_theory.voicings import Voicing, constraints_for_skill

C = Key(N("C"))
A_MINOR = Key(N("A"), "minor")
LIB = default_library()
KEYS = {
    "major": [k for k in ALL_KEYS if k.mode == "major"],
    "minor": [k for k in ALL_KEYS if k.mode == "minor"],
}


def symbols(p: Progression) -> list[str]:
    return [str(c.chord) for c in p.chords]


def codes(report, severity=None):  # type: ignore[no-untyped-def]
    return [i.code for i in report.issues if severity is None or i.severity == severity]


# ------------------------------------------------------------ templates


def test_library_has_the_required_progressions() -> None:
    ids = set(LIB.ids())
    assert len(ids) == len(LIB.ids()) >= 15
    assert {
        "major_i_iv_v_i", "pop_i_v_vi_iv", "ii_v_i", "ii_v_i_vi", "i_vi_ii_v", "iii_vi_ii_v",
        "twelve_bar_blues", "minor_ii_v_i", "gospel_walkup", "jazz_turnaround_secondary",
    } <= ids  # fmt: skip
    assert LIB.search(style="gospel") and LIB.search(style="jazz") and LIB.search(style="blues")
    assert all(t.mode == "minor" for t in LIB.search(mode="minor"))
    assert {"beginner", "intermediate", "advanced"} <= {LIB.get(i).difficulty for i in LIB.ids()}


@pytest.mark.parametrize(
    ("template", "key", "vocabulary", "expected"),
    [
        ("ii_v_i", C, "sevenths", "Dm7 G7 Cmaj7"),
        ("ii_v_i", C, "triads", "Dm G C"),
        ("major_i_iv_v_i", C, "triads", "C F G C"),
        ("pop_i_v_vi_iv", Key(N("G")), "triads", "G D Em C"),
        ("ii_v_i_vi", C, "sevenths", "Dm7 G7 Cmaj7 Am7"),
        ("i_vi_ii_v", C, "sevenths", "Cmaj7 Am7 Dm7 G7"),
        ("iii_vi_ii_v", C, "sevenths", "Em7 Am7 Dm7 G7"),
        ("minor_ii_v_i", A_MINOR, "sevenths", "Bm7b5 E7 Am7"),
        ("minor_ii_v_i", A_MINOR, "triads", "Bdim E Am"),
        ("minor_andalusian", A_MINOR, "triads", "Am G F E"),
        ("twelve_bar_blues", C, "sevenths", "C7 C7 C7 C7 F7 F7 C7 C7 G7 F7 C7 G7"),
        ("twelve_bar_blues", Key(N("Bb")), "triads", "Bb Bb Bb Bb Eb Eb Bb Bb F Eb Bb F"),
        ("jazz_turnaround_secondary", C, "sevenths", "Cmaj7 A7 Dm7 G7"),
        ("jazz_turnaround_diminished", C, "sevenths", "Cmaj7 C#dim7 Dm7 G7"),
        ("jazz_backdoor", C, "sevenths", "Fm7 Bb7 Cmaj7"),
        ("gospel_walkup", C, "triads", "C C/E F F#dim C/G G C"),
    ],
)  # fmt: skip
def test_known_progressions(template: str, key: Key, vocabulary: str, expected: str) -> None:
    assert " ".join(symbols(generate_progression(template, key, vocabulary))) == expected  # type: ignore[arg-type]


def test_realised_progressions_carry_timing_and_metadata() -> None:
    p = generate_progression("ii_v_i", C, "sevenths", tempo=96)
    assert [(c.beat, c.duration) for c in p.chords] == [(0, 4), (4, 4), (8, 8)]
    assert p.total_beats == 16 and p.beats_per_bar == 4 and p.tempo == 96
    assert [c.roman for c in p.chords] == ["ii7", "V7", "Imaj7"]
    assert p.template_id == "ii_v_i" and p.styles == ("jazz",) and p.scale == "major"
    assert generate_progression("minor_ii_v_i", A_MINOR, "triads").scale == "natural_minor"
    assert generate_progression("twelve_bar_blues", C).total_beats == 48


@pytest.mark.parametrize("template", LIB.ids())
@pytest.mark.parametrize("vocabulary", ["triads", "sevenths"])
def test_every_template_realises_validly_in_every_standard_key(
    template: str, vocabulary: str
) -> None:
    t = LIB.get(template)
    for key in KEYS[t.mode]:
        p = realize(t, key, vocabulary)  # type: ignore[arg-type]
        report = validate_progression(p)
        assert report.ok, (template, key, report.issues)
        assert report.issues == (), (template, vocabulary, str(key), report.issues)


def test_realising_checks_mode_and_vocabulary() -> None:
    with pytest.raises(TheoryError) as err:
        generate_progression("ii_v_i", A_MINOR)
    assert err.value.code == "key_mode_mismatch"
    with pytest.raises(TheoryError):
        generate_progression("ii_v_i", C, "ninths")  # type: ignore[arg-type]
    with pytest.raises(TheoryError) as err2:
        generate_progression("nope", C)
    assert err2.value.code == "unknown_progression"


def test_administrators_can_add_templates_with_validation() -> None:
    lib = LIB.copy()
    good = {
        "progressions": [{
            "id": "custom_vi_ii_v_i", "name": "vi–ii–V–I", "mode": "major", "difficulty": "intermediate",
            "styles": ["jazz"], "explanation": "x", "practice": "y",
            "chords": [{"triads": n, "sevenths": s, "beats": 4} for n, s in
                       [("vi", "vi7"), ("ii", "ii7"), ("V", "V7"), ("I", "Imaj7")]],
        }]
    }  # fmt: skip
    for t in load_templates(json.dumps(good)):
        lib.register(t)
    assert (
        " ".join(symbols(generate_progression("custom_vi_ii_v_i", C, "sevenths", library=lib)))
        == "Am7 Dm7 G7 Cmaj7"
    )
    assert "custom_vi_ii_v_i" not in LIB.ids()
    with pytest.raises(TemplateError):
        lib.register(lib.get("ii_v_i"))


@pytest.mark.parametrize(
    "mutate",
    [
        lambda t: t.update(mode="dorian"), lambda t: t.update(difficulty="godlike"),
        lambda t: t.update(chords=[]), lambda t: t["chords"][0].update(triads="Xyz"),
        lambda t: t["chords"][0].update(beats=0), lambda t: t["chords"][0].update(sevenths="V7/"),
        lambda t: t.pop("id"), lambda t: t["chords"][0].pop("beats"),
    ],
)  # fmt: skip
def test_invalid_templates_are_rejected(mutate) -> None:  # type: ignore[no-untyped-def]
    t = {"id": "x", "name": "X", "mode": "major", "difficulty": "beginner",
         "chords": [{"triads": "I", "sevenths": "Imaj7", "beats": 4}]}  # fmt: skip
    mutate(t)
    with pytest.raises(TemplateError):
        load_templates(json.dumps({"progressions": [t]}))
    with pytest.raises(TemplateError):
        load_templates("{bad")


def test_custom_progressions_get_numerals_from_analysis() -> None:
    p = make_progression("My tune", C, ["Cmaj7", "A7", "Dm7", "G7"], beats=[4, 2, 2, 4])
    assert [c.roman for c in p.chords] == ["Imaj7", "V7/ii", "ii7", "V7"]
    assert [c.beat for c in p.chords] == [0, 4, 6, 8]
    bare = replace(p, chords=tuple(replace(c, roman=None) for c in p.chords))
    assert [c.roman for c in with_analysis(bare).chords] == ["Imaj7", "V7/ii", "ii7", "V7"]
    with pytest.raises(TheoryError):
        make_progression("x", C, ["C", "G"], beats=[4])


# ------------------------------------------------------------ transposition


@pytest.mark.parametrize(
    "template",
    ["ii_v_i", "pop_i_v_vi_iv", "twelve_bar_blues", "gospel_walkup", "jazz_turnaround_diminished"],
)
@pytest.mark.parametrize("vocabulary", ["triads", "sevenths"])
def test_transposition_into_all_keys_preserves_everything_that_matters(
    template: str, vocabulary: str
) -> None:
    original = generate_progression(template, C, vocabulary)  # type: ignore[arg-type]
    results = transpose_to_all_keys(original)
    assert len(results) == 12
    for tonic, res in results.items():
        moved = res.progression
        shift = (moved.key.tonic.pitch_class - C.tonic.pitch_class) % 12
        assert str(moved.key.tonic) == tonic
        for a, b in zip(original.chords, moved.chords, strict=True):
            assert b.chord.type == a.chord.type
            assert [t.pitch_class for t in b.chord.tones()] == [
                (t.pitch_class + shift) % 12 for t in a.chord.tones()
            ]
            assert (b.roman, b.beat, b.duration, b.role) == (a.roman, a.beat, a.duration, a.role)
            if a.chord.bass is not None and b.chord.bass is not None:
                assert b.chord.bass.pitch_class == (a.chord.bass.pitch_class + shift) % 12
        assert validate_progression(moved).ok


def test_transposition_spells_for_the_new_key_and_round_trips() -> None:
    p = generate_progression("ii_v_i", C, "sevenths")
    assert symbols(transpose_progression(p, "Db").progression) == ["Ebm7", "Ab7", "Dbmaj7"]
    assert symbols(transpose_progression(p, "F#").progression) == ["G#m7", "C#7", "F#maj7"]
    assert symbols(transpose_progression(p, N("Bb")).progression) == ["Cm7", "F7", "Bbmaj7"]
    for key in KEYS["major"]:
        there = transpose_progression(p, key.tonic).progression
        back = transpose_progression(there, C.tonic).progression
        assert symbols(back) == symbols(p)
    walk = generate_progression("gospel_walkup", C, "triads")
    assert symbols(transpose_progression(walk, "Eb").progression) == [
        "Eb",
        "Eb/G",
        "Ab",
        "Adim",
        "Eb/Bb",
        "Bb",
        "Eb",
    ]


def test_minor_key_transposition_and_errors() -> None:
    p = generate_progression("minor_ii_v_i", A_MINOR, "sevenths")
    assert symbols(transpose_progression(p, "C").progression) == ["Dm7b5", "G7", "Cm7"]
    with pytest.raises(TheoryError) as err:
        transpose_progression(p, Key(N("C"), "major"))
    assert err.value.code == "mode_change"
    with pytest.raises(TheoryError):
        transpose_progression(p, "H")


def test_transposition_uses_numerals_but_survives_missing_or_wrong_ones() -> None:
    p = make_progression("x", C, ["C", "Am7", "D7/F#", "G"])
    no_numerals = replace(p, chords=tuple(replace(c, roman=None) for c in p.chords))
    wrong = replace(p, chords=tuple(replace(c, roman="bVII") for c in p.chords))
    expected = ["D", "Bm7", "E7/G#", "A"]
    for variant in (p, no_numerals, wrong):
        assert symbols(transpose_progression(variant, "D").progression) == expected


def test_voicings_move_with_the_key_when_they_still_fit() -> None:
    p, _ = voice_progression(
        generate_progression("major_i_iv_v_i", C), constraints_for_skill("expert")
    )
    res = transpose_progression(p, "D", constraints=constraints_for_skill("expert"))
    assert not res.revoiced and res.shift_semitones == 2
    for a, b in zip(p.chords, res.progression.chords, strict=True):
        assert a.voicing is not None and b.voicing is not None
        assert b.voicing.notes == tuple(n + 2 for n in a.voicing.notes)


def test_unplayable_shifted_voicings_are_revoiced_dropped_or_reported() -> None:
    narrow = constraints_for_skill("beginner", lh_range=(40, 52), rh_range=(60, 72))
    p, _ = voice_progression(generate_progression("major_i_iv_v_i", C), narrow)
    revoiced = transpose_progression(p, "F#", constraints=narrow)  # shift of -6 leaves the ranges
    assert revoiced.revoiced and any("regenerated" in w for w in revoiced.warnings)
    assert all(c.voicing is not None for c in revoiced.progression.chords)
    assert validate_progression(revoiced.progression, constraints=narrow).ok
    dropped = transpose_progression(p, "F#", constraints=narrow, on_unplayable="drop")
    assert not dropped.revoiced and any(c.voicing is None for c in dropped.progression.chords)
    with pytest.raises(TheoryError) as err:
        transpose_progression(p, "F#", constraints=narrow, on_unplayable="error")
    assert err.value.code == "unplayable_voicing"


# ------------------------------------------------------------ substitutions and passing chords


def test_tritone_substitution() -> None:
    p = generate_progression("ii_v_i", C, "sevenths")
    s = substitute_tritone(p, 1)
    assert symbols(s) == ["Dm7", "Db7", "Cmaj7"]
    sub = s.chords[1]
    assert (sub.role, sub.substitution_for, sub.roman) == ("substitution", "G7", "bII7")
    assert (sub.beat, sub.duration) == (4, 4) and sub.voicing is None
    assert validate_progression(s).ok and not validate_progression(s).warnings
    moved = transpose_progression(s, "D").progression
    assert symbols(moved) == ["Em7", "Eb7", "Dmaj7"] and moved.chords[1].substitution_for == "A7"
    for bad in (0, 2):
        with pytest.raises(TheoryError) as err:
            substitute_tritone(p, bad)
        assert err.value.code == "invalid_substitution"
    with pytest.raises(TheoryError) as err2:
        substitute_tritone(p, 9)
    assert err2.value.code == "invalid_index"


def test_secondary_dominant_is_inserted_without_changing_the_length() -> None:
    p = generate_progression("ii_v_i", C, "sevenths")
    s = insert_secondary_dominant(p, 1)
    assert symbols(s) == ["Dm7", "D7", "G7", "Cmaj7"]
    assert [(c.beat, c.duration) for c in s.chords] == [(0, 4), (4, 2), (6, 2), (8, 8)]
    assert s.chords[1].role == "passing" and s.chords[1].roman == "V7/V" and s.total_beats == 16
    assert validate_progression(s).ok
    short = make_progression("x", C, ["C", "G"], beats=[0.5, 4])
    with pytest.raises(TheoryError) as err:
        insert_secondary_dominant(short, 0)
    assert err.value.code == "chord_too_short"
    with pytest.raises(TheoryError) as err2:
        insert_secondary_dominant(make_progression("x", C, ["C", "Bdim"]), 1)
    assert err2.value.code == "invalid_target"


def test_passing_diminished_chord() -> None:
    p = make_progression("x", C, ["C", "Dm7", "G7", "C"], beats=[4, 4, 4, 4])
    s = insert_passing_diminished(p, 0)
    assert symbols(s) == ["C", "C#dim7", "Dm7", "G7", "C"]
    assert [(c.beat, c.duration) for c in s.chords[:3]] == [(0, 2), (2, 2), (4, 4)]
    assert s.chords[1].roman == "vii°7/ii" and s.chords[1].role == "passing"
    assert validate_progression(s).ok
    with pytest.raises(TheoryError):
        insert_passing_diminished(p, 3)


def test_passing_diminished_is_spelled_from_the_next_root() -> None:
    p = make_progression("x", C, ["Dm7", "G7", "Cmaj7"], beats=[4, 4, 4])
    assert str(insert_passing_diminished(p, 0).chords[1].chord) == "F#dim7"  # a half step below G
    assert str(insert_passing_diminished(p, 1).chords[2].chord) == "Bdim7"  # a half step below C


# ------------------------------------------------------------ voicing a progression


def test_voice_progression_assigns_playable_voicings_to_every_chord() -> None:
    p = generate_progression("ii_v_i_vi", C, "sevenths")
    voiced, detail = voice_progression(p)
    assert all(c.voicing is not None for c in voiced.chords)
    assert len(detail.items) == 4 and detail.method == "dp"
    report = validate_progression(voiced)
    assert report.ok, report.issues
    again, _ = voice_progression(p)
    assert again == voiced  # deterministic
    pinned = voiced.chords[1].voicing
    repinned, _ = voice_progression(p, fixed={1: pinned})  # type: ignore[arg-type]
    assert repinned.chords[1].voicing == pinned
    assert p.chords[0].voicing is None  # the original is untouched


# ------------------------------------------------------------ validation


def base() -> Progression:
    return generate_progression("ii_v_i", C, "sevenths", tempo=100)


def with_chord(p: Progression, i: int, **changes) -> Progression:  # type: ignore[no-untyped-def]
    cs = list(p.chords)
    cs[i] = replace(cs[i], **changes)
    return replace(p, chords=tuple(cs))


@pytest.mark.parametrize(
    ("make", "code"),
    [
        (lambda p: replace(p, name="  "), "missing_name"),
        (lambda p: replace(p, chords=()), "no_chords"),
        (lambda p: replace(p, difficulty="godlike"), "invalid_difficulty"),
        (lambda p: replace(p, time_signature=(4, 3)), "invalid_time_signature"),
        (lambda p: replace(p, time_signature=(0, 4)), "invalid_time_signature"),
        (lambda p: replace(p, tempo=5), "invalid_tempo"),
        (lambda p: replace(p, tempo=900), "invalid_tempo"),
        (lambda p: replace(p, meta=PublicationMeta(status="live")), "invalid_status"),
        (lambda p: replace(p, meta=PublicationMeta(revision=0)), "invalid_revision"),
        (lambda p: replace(p, schema_version=9), "unsupported_schema"),
        (lambda p: with_chord(p, 1, beat=-1), "negative_beat"),
        (lambda p: with_chord(p, 1, duration=0), "invalid_duration"),
        (lambda p: with_chord(p, 1, beat=3), "timing_overlap"),
        (lambda p: with_chord(p, 2, beat=2), "out_of_order"),
        (lambda p: with_chord(p, 1, role="dancing"), "invalid_role"),
        (lambda p: with_chord(p, 1, beat=math.inf), "invalid_timing"),
    ],
)  # fmt: skip
def test_structural_problems_are_errors(make, code: str) -> None:  # type: ignore[no-untyped-def]
    report = validate_progression(make(base()))
    assert code in codes(report, "error") and not report.ok


def test_timing_oddities_are_warnings_not_errors() -> None:
    gap = validate_progression(with_chord(base(), 2, beat=9, duration=7))
    assert "timing_gap" in codes(gap, "warning") and gap.ok
    late = validate_progression(replace(base(), chords=tuple(
        replace(c, beat=c.beat + 1) for c in base().chords)))  # fmt: skip
    assert "late_start" in codes(late, "warning")
    odd = validate_progression(with_chord(base(), 2, duration=5))
    assert "incomplete_bar" in codes(odd, "warning") and odd.ok


def test_harmony_issues_are_warnings_unless_the_lesson_is_strict() -> None:
    p = make_progression("x", C, ["C", "F#m7", "G"])  # F#m7 is not diatonic, borrowed or applied
    loose = validate_progression(p)
    assert loose.ok and "chromatic_chord" in codes(loose, "warning")
    strict = validate_progression(p, strict_harmony=True)
    assert not strict.ok and "chromatic_chord" in codes(strict, "error")
    mismatch = with_chord(base(), 1, roman="IV")
    assert "roman_mismatch" in codes(validate_progression(mismatch), "warning")
    assert "roman_mismatch" in codes(validate_progression(mismatch, strict_harmony=True), "error")
    junk = with_chord(base(), 1, roman="Xyz")
    assert "invalid_roman" in codes(validate_progression(junk), "warning")
    assert "chromatic_chord" not in codes(validate_progression(substitute_tritone(base(), 1)))
    # dominant sevenths on IV are blues idiom, but an error-prone surprise elsewhere
    blues = generate_progression("twelve_bar_blues", C, "sevenths")
    assert validate_progression(blues).issues == ()
    untagged = replace(blues, styles=("jazz",))
    assert "chromatic_chord" in codes(validate_progression(untagged), "warning")


def test_voicing_problems_are_found() -> None:
    p, _ = voice_progression(base())
    good = p.chords[1].voicing
    assert good is not None

    def bad(v: Voicing) -> list[str]:
        return codes(validate_progression(with_chord(p, 1, voicing=v)), "error")

    assert "voicing_not_in_chord" in bad(replace(good, right=(61, 65, 68)))  # C# F G# over G7
    assert "voicing_unplayable" in bad(replace(good, left=(10,)))
    assert "voicing_unplayable" in bad(replace(good, right=(*good.right, 100)))
    assert "hand_crossing" in bad(replace(good, left=(70,), right=good.right))
    slash = with_chord(p, 1, chord=P("G7/B"))
    assert "bass_mismatch" in codes(validate_progression(replace(slash, key=C)), "error")
    rooted = replace(
        good, lh_style="bass", rh_style="seventh_close", left=(41,)
    )  # F in the bass of G7
    assert "bass_not_root" in codes(
        validate_progression(with_chord(p, 1, voicing=rooted)), "warning"
    )
    no_third = replace(good, right=(53, 55))
    assert "missing_third" in codes(
        validate_progression(with_chord(p, 1, voicing=no_third)), "warning"
    )


def test_publication_requirements() -> None:
    p = replace(
        base(),
        explanation="",
        styles=(),
        chords=tuple(replace(c, roman=None) for c in base().chords),
    )
    report = validate_progression(p, publication=True)
    assert {"missing_explanation", "missing_author", "no_styles", "missing_roman"} <= set(
        codes(report, "error")
    )
    ready = replace(base(), meta=PublicationMeta(author="A. Teacher", status="approved"))
    assert validate_progression(ready, publication=True).ok
    assert validate_progression(base()).ok  # drafts do not need these


def test_deep_validation_checks_transposition_into_every_key() -> None:
    assert validate_progression(base(), deep=True).issues == ()
    awkward = make_progression("x", Key(N("F#")), ["F#", "A#dim7", "B", "C#7"])
    report = validate_progression(awkward, deep=True)
    assert report.ok


# ------------------------------------------------------------ serialisation


def full() -> Progression:
    p, _ = voice_progression(insert_secondary_dominant(base(), 1))
    p = substitute_tritone(p, 2)
    return replace(p, meta=PublicationMeta("A. Teacher", "own work", "approved", 3), tempo=88)


def test_progressions_round_trip_through_json() -> None:
    p = full()
    data = progression_to_dict(p)
    assert data["schema_version"] == 1 and data["chords"][1]["voicing"] is not None
    assert progression_from_dict(json.loads(json.dumps(data))) == p
    assert progression_to_dict(progression_from_dict(data)) == data


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: d.pop("name"), lambda d: d.update(name=5), lambda d: d.update(chords="x"),
        lambda d: d["chords"][0].update(type="nonsense"), lambda d: d["chords"][0].update(root="H"),
        lambda d: d["chords"][0].update(symbol="Cmaj7"), lambda d: d["chords"][0].pop("beat"),
        lambda d: d["chords"][0].update(beat="soon"), lambda d: d["chords"][0].update(beat=True),
        lambda d: d["chords"][0].update(voicing={"left": "x"}), lambda d: d.update(key={"tonic": "C"}),
        lambda d: d.update(key={"tonic": "C", "mode": "dorian"}), lambda d: d["chords"].append(5),
        lambda d: d.update(schema_version="one"), lambda d: d.update(schema_version=-1),
        lambda d: d.update(schema_version=99), lambda d: d.update(time_signature=[4]),
    ],
)  # fmt: skip
def test_bad_stored_data_gives_clear_errors(mutate) -> None:  # type: ignore[no-untyped-def]
    data = progression_to_dict(full())
    mutate(data)
    with pytest.raises(TheoryError) as err:
        progression_from_dict(data)
    assert err.value.code in {
        "invalid_progression_data",
        "unsupported_schema_version",
        "unknown_chord_type",
        "invalid_voicing",
    }


def test_older_data_is_migrated_step_by_step(monkeypatch: pytest.MonkeyPatch) -> None:
    data = progression_to_dict(base())
    legacy = {**data, "schema_version": 0}
    for c in legacy["chords"]:
        c["start"] = c.pop("beat")  # imagine version 0 called it "start"

    def v0_to_v1(d):  # type: ignore[no-untyped-def]
        d = dict(d)
        d["chords"] = [{**c, "beat": c["start"]} for c in d["chords"]]
        return d

    with pytest.raises(TheoryError) as err:
        migrate_progression_data(legacy)
    assert err.value.code == "no_migration"
    monkeypatch.setitem(prog_module._MIGRATIONS, 0, v0_to_v1)
    migrated = progression_from_dict(legacy)
    assert migrated == base() and migrated.schema_version == 1


# ------------------------------------------------------------ walking bass


def test_walking_bass_follows_the_chords() -> None:
    p = generate_progression("ii_v_i", C, "sevenths")
    line = walking_bass(p)
    assert [n.beat for n in line] == [float(i) for i in range(16)]
    assert all(28 <= n.midi <= 55 for n in line)
    assert line == walking_bass(p)
    starts = {c.beat: c.chord.root.pitch_class for c in p.chords}
    for n in line:
        if n.beat in starts:
            assert n.midi % 12 == starts[n.beat] and n.role == "root"
    approaches = [n for n in line if n.role == "approach"]
    assert len(approaches) == 2  # into G7 and into Cmaj7
    for n in approaches:
        target = starts[n.beat + 1]
        assert min((n.midi - target) % 12, (target - n.midi) % 12) == 1
    assert max(abs(a.midi - b.midi) for a, b in zip(line, line[1:], strict=False)) <= 9


def test_walking_bass_respects_slash_chords_and_range() -> None:
    p = make_progression("x", C, ["C/E", "F", "G7"], beats=[4, 4, 4])
    line = walking_bass(p, low=30, high=50)
    assert line[0].midi % 12 == 4  # the stated bass note
    assert all(30 <= n.midi <= 50 for n in line)
    assert walking_bass(make_progression("x", C, ["C"], beats=[1]))[0].role == "root"


def test_walking_bass_errors() -> None:
    odd = make_progression("x", C, ["C", "G"], beats=[2.5, 1.5])
    with pytest.raises(TheoryError) as err:
        walking_bass(odd)
    assert err.value.code == "walking_bass_unsupported"
    with pytest.raises(TheoryError):
        walking_bass(base(), low=50, high=40)
