import re

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from music_theory.chord_symbols import parse_chord
from music_theory.exercises import (
    DIFFICULTIES,
    GENERATOR_VERSION,
    KINDS,
    ExerciseError,
    exercise_id,
    generate_exercise,
    generate_set,
    list_kinds,
    parse_exercise_id,
    parse_interval_answer,
    reference_answer,
    validate_answer,
)
from music_theory.identify import identify_chord
from music_theory.notes import note_from_midi

ALL = [(k, d) for k in KINDS for d in DIFFICULTIES]
SEEDS = range(25)


def find(kind: str, difficulty: str, pattern: str, limit: int = 3000):  # type: ignore[no-untyped-def]
    """First exercise whose prompt matches. Keeps known-answer tests independent of RNG details."""
    rx = re.compile(pattern)
    for seed in range(limit):
        ex = generate_exercise(kind, difficulty, seed)
        if rx.search(ex.prompt):
            return ex
    raise AssertionError(f"no {kind}/{difficulty} exercise matching {pattern!r}")


# ------------------------------------------------------------------ catalogue


def test_every_topic_in_the_specification_has_exercises() -> None:
    topics = {k.topic for k in list_kinds()}
    assert topics >= {
        "notes", "intervals", "scales", "key_signatures", "triads", "seventh_chords",
        "inversions", "diatonic_harmony", "roman_numerals", "progressions", "voice_leading",
        "cadences", "secondary_dominants", "modal_interchange", "extensions", "substitutions",
        "ear_training",
    }  # fmt: skip


def test_prerequisites_exist_and_have_no_cycles() -> None:
    for info in list_kinds():
        for p in info.prerequisites:
            assert p in KINDS
    state: dict[str, int] = {}

    def visit(kind: str) -> None:
        assert state.get(kind) != 1, f"prerequisite cycle through {kind}"
        if state.get(kind) == 2:
            return
        state[kind] = 1
        for p in KINDS[kind].prerequisites:
            visit(p)
        state[kind] = 2

    for k in KINDS:
        visit(k)


# ------------------------------------------------------------------ generation


@pytest.mark.parametrize(("kind", "difficulty"), ALL)
def test_every_kind_and_level_generates_and_its_reference_answer_is_correct(
    kind: str, difficulty: str
) -> None:
    for seed in SEEDS:
        ex = generate_exercise(kind, difficulty, seed)
        assert ex.id == exercise_id(kind, difficulty, seed)
        assert ex.prompt
        grade = validate_answer(ex.id, reference_answer(ex))
        assert grade.correct and grade.status == "correct", (ex.prompt, grade)


@pytest.mark.parametrize(("kind", "difficulty"), ALL)
def test_generation_is_deterministic(kind: str, difficulty: str) -> None:
    for seed in (0, 1, 99, 12345):
        assert generate_exercise(kind, difficulty, seed) == generate_exercise(
            kind, difficulty, seed
        )
        assert reference_answer(exercise_id(kind, difficulty, seed)) == reference_answer(
            exercise_id(kind, difficulty, seed)
        )


@pytest.mark.parametrize(("kind", "difficulty"), ALL)
def test_seeds_give_variety(kind: str, difficulty: str) -> None:
    seen = set()
    for s in range(40):
        ex = generate_exercise(kind, difficulty, s)
        seen.add((ex.prompt, ex.show, ex.choices, ex.play))
    assert len(seen) >= 5, f"{kind}/{difficulty} produced only {len(seen)} different exercises"


def test_generate_set_uses_consecutive_seeds() -> None:
    items = generate_set("interval_identify", "beginner", 4, seed=10)
    assert [e.seed for e in items] == [10, 11, 12, 13]
    with pytest.raises(ExerciseError) as err:
        generate_set("interval_identify", "beginner", 0)
    assert err.value.code == "invalid_count"


def test_unseeded_generation_returns_a_valid_reproducible_exercise() -> None:
    ex = generate_exercise("note_name", "beginner")
    assert generate_exercise("note_name", "beginner", ex.seed) == ex


def test_difficulty_increases_the_material() -> None:
    def intervals(d: str) -> set[str]:
        found = set()
        for s in range(150):
            found.add(str(reference_answer(generate_exercise("interval_identify", d, s))))
        return found

    assert "A4" not in intervals("beginner") and "m3" not in intervals("beginner")
    assert {"A4", "d5"} & intervals("advanced")
    assert any(parse_interval_answer(i).number > 8 for i in intervals("advanced"))


# ------------------------------------------------------------------ ids and input errors


@pytest.mark.parametrize(
    ("text", "code"),
    [
        ("", "invalid_exercise_id"),
        ("note_name:beginner:1", "invalid_exercise_id"),
        ("v1:note_name:beginner:-1", "invalid_exercise_id"),
        ("v1:note_name:beginner:abc", "invalid_exercise_id"),
        ("v1:Note_Name:beginner:1", "invalid_exercise_id"),
        (f"v{GENERATOR_VERSION + 1}:note_name:beginner:1", "unsupported_exercise_version"),
        ("v1:no_such_kind:beginner:1", "unknown_exercise_kind"),
        ("v1:note_name:godlike:1", "unknown_difficulty"),
        ("v1:note_name:beginner:99999999999", "invalid_exercise_id"),
        ("v1:note_name:beginner:2147483648", "invalid_seed"),
    ],
)
def test_bad_exercise_ids_have_stable_codes(text: str, code: str) -> None:
    with pytest.raises(ExerciseError) as err:
        parse_exercise_id(text)
    assert err.value.code == code


@pytest.mark.parametrize(
    ("kind", "difficulty", "seed", "code"),
    [
        ("nope", "beginner", 1, "unknown_exercise_kind"),
        ("note_name", "nope", 1, "unknown_difficulty"),
        ("note_name", "beginner", -5, "invalid_seed"),
        ("note_name", "beginner", True, "invalid_seed"),
    ],
)
def test_bad_generation_requests(kind: str, difficulty: str, seed: int, code: str) -> None:
    with pytest.raises(ExerciseError) as err:
        generate_exercise(kind, difficulty, seed)
    assert err.value.code == code


def test_answer_of_the_wrong_shape_is_an_error_not_a_grade() -> None:
    ex = find("interval_identify", "advanced", ".")  # text answer
    for bad in (["M3"], 5, None, {"a": 1}):
        with pytest.raises(ExerciseError) as err:
            validate_answer(ex.id, bad)
        assert err.value.code == "invalid_answer"
    scale = generate_exercise("scale_construct", "beginner", 1)  # list answer
    for bad in ("C D E", 5, [], [True], [["C"]], ["C"] * 40):
        with pytest.raises(ExerciseError) as err:
            validate_answer(scale.id, bad)
        assert err.value.code == "invalid_answer"
    with pytest.raises(ExerciseError):
        validate_answer(ex.id, "x" * 500)


def test_choice_answer_must_be_one_of_the_choices() -> None:
    ex = generate_exercise("cadence_identify", "beginner", 3)
    with pytest.raises(ExerciseError) as err:
        validate_answer(ex.id, "something else")
    assert err.value.code == "invalid_answer"


# ------------------------------------------------------------------ known answers


def test_interval_c4_to_fsharp4_is_an_augmented_fourth_not_a_diminished_fifth() -> None:
    ex = find("interval_identify", "advanced", r"from C4 up to F#4\?")
    assert validate_answer(ex.id, "A4").status == "correct"
    assert validate_answer(ex.id, "augmented fourth").correct
    g = validate_answer(ex.id, "d5")
    assert g.status == "enharmonic" and not g.correct  # same sound, wrong spelling
    assert "4 letters" in g.feedback or "A4" in g.feedback
    assert not validate_answer(ex.id, "P5").correct


def test_interval_build_spelling_is_strict() -> None:
    ex = find("interval_build", "intermediate", r"minor sixth above Eb\?")
    assert validate_answer(ex.id, "Cb").correct
    g = validate_answer(ex.id, "B")
    assert g.status == "enharmonic" and not g.correct
    assert validate_answer(ex.id, "C").status == "incorrect"
    assert validate_answer(ex.id, "H").status == "unreadable"


def test_scale_f_sharp_major_needs_e_sharp_and_reports_the_degree() -> None:
    ex = find("scale_construct", "advanced", r"Major scale starting on F#")
    assert validate_answer(ex.id, ["F#", "G#", "A#", "B", "C#", "D#", "E#"]).correct
    g = validate_answer(ex.id, ["F#", "G#", "A#", "B", "C#", "D#", "F"])
    assert g.status == "enharmonic" and not g.correct
    assert "degree 7" in g.feedback and "E#" in g.feedback
    g = validate_answer(ex.id, ["F#", "G#", "A", "B", "C#", "D#", "E#"])
    assert g.status == "incorrect" and g.items[2].correct is False and g.items[0].correct
    assert validate_answer(ex.id, ["F#", "G#"]).status == "incorrect"


def test_note_on_piano_accepts_either_enharmonic_name_with_octave() -> None:
    for seed in range(500):
        ex = generate_exercise("note_name", "advanced", seed)
        if ex.show == (61,):
            assert validate_answer(ex.id, "C#4").correct
            assert validate_answer(ex.id, "Db4").correct
            g = validate_answer(ex.id, "C#5")
            assert not g.correct and "octave" in g.feedback
            assert validate_answer(ex.id, "C#").status == "unreadable"
            return
    raise AssertionError("no C#4 exercise found")


def test_beginner_note_names_need_no_octave() -> None:
    ex = generate_exercise("note_name", "beginner", 1)
    name = str(note_from_midi(ex.show[0]).name)
    assert validate_answer(ex.id, name).correct
    assert validate_answer(ex.id, f"{name}{ex.show[0] // 12 - 1}").correct


def test_key_signature_answers_accept_natural_wording() -> None:
    for seed in range(300):
        ex = generate_exercise("key_signature", "intermediate", seed)
        if ex.prompt.startswith("How many") and "D major" in ex.prompt:
            for ok in ("2 sharps", "2 #", "2♯", "2 Sharps"):
                assert validate_answer(ex.id, ok).correct
            assert not validate_answer(ex.id, "2 flats").correct
            assert validate_answer(ex.id, "banana").status == "unreadable"
            assert validate_answer(ex.id, "2").status == "unreadable"
            return
    raise AssertionError("no D major exercise found")


def test_chord_building_by_piano_keys_or_names() -> None:
    ex = find("triad_build", "advanced", r"Spell F#m ")
    assert validate_answer(ex.id, ["F#", "A", "C#"]).correct
    assert validate_answer(ex.id, [54, 57, 61]).correct  # F#3 A3 C#4
    assert validate_answer(ex.id, [66, 69, 73, 78]).correct  # octave doubling is fine
    g = validate_answer(ex.id, ["Gb", "A", "C#"])
    assert g.status == "enharmonic" and not g.correct
    g = validate_answer(ex.id, ["F#", "A"])
    assert g.status == "incorrect" and "C#" in g.feedback
    assert validate_answer(ex.id, ["F#", "A", "Z"]).status == "unreadable"
    with pytest.raises(ExerciseError):
        validate_answer(ex.id, ["F#", 57])  # mixing is ambiguous


def test_half_diminished_is_not_confused_with_minor_or_fully_diminished() -> None:
    ex = find("seventh_build", "advanced", r"Spell Cdim7 ")
    assert validate_answer(ex.id, ["C", "Eb", "Gb", "Bbb"]).correct
    assert not validate_answer(ex.id, ["C", "Eb", "Gb", "Bb"]).correct  # that is Cm7b5
    assert not validate_answer(ex.id, ["C", "Eb", "G", "Bb"]).correct  # that is Cm7


def test_chord_identification_forms_and_alternate_readings() -> None:
    for seed in range(400):
        ex = generate_exercise("seventh_identify", "intermediate", seed)
        chord = parse_chord(str(reference_answer(ex)))
        if chord.type.id == "minor7" and chord.bass is None and chord.root.pitch_class == 2:
            assert validate_answer(ex.id, "Dm7").correct
            assert validate_answer(ex.id, "Dmin7").correct  # alias
            bad = validate_answer(ex.id, "Dmaj7")
            assert bad.status == "incorrect" and "Dm7" in bad.feedback
            assert validate_answer(ex.id, "D").status == "incorrect"
            assert validate_answer(ex.id, "Dmaj").status == "unreadable"
            return
    raise AssertionError("no Dm7 exercise found")


def test_missing_slash_bass_is_a_partial_not_a_pass() -> None:
    for seed in range(600):
        ex = generate_exercise("triad_identify", "intermediate", seed)
        chord = parse_chord(str(reference_answer(ex)))
        if chord.bass is not None:
            root_only = f"{chord.root}{chord.type.symbol}"
            g = validate_answer(ex.id, root_only)
            assert g.status == "partial" and not g.correct
            assert str(chord.bass) in g.feedback
            assert validate_answer(ex.id, str(chord)).correct
            return
    raise AssertionError("no slash-chord exercise found")


def test_roman_numeral_accepts_equivalent_notation_and_explains_wrong_ones() -> None:
    ex = find("roman_numeral", "advanced", r"In [A-G][#b]? major, give the Roman numeral for [A-G]")
    figure = str(reference_answer(ex))
    assert validate_answer(ex.id, figure).correct
    wrong = validate_answer(ex.id, "iii" if figure != "iii" else "ii")
    assert not wrong.correct
    assert validate_answer(ex.id, "not a numeral").status == "unreadable"


def test_secondary_dominant_v7_of_v_in_c_is_d7() -> None:
    for seed in range(2000):
        ex = generate_exercise("secondary_dominant", "advanced", seed)
        if ex.prompt == "In C major, which chord is V7/V?":
            assert validate_answer(ex.id, "D7").correct
            assert not validate_answer(ex.id, "D").correct
            assert not validate_answer(ex.id, "G7").correct
            return
    raise AssertionError("no V7/V in C exercise found")


def test_ii_v_i_progression_spells_dm7_g7_cmaj7() -> None:
    for seed in range(3000):
        ex = generate_exercise("progression_build", "intermediate", seed)
        if ex.prompt.startswith("Write ii–V–I in C major as chord symbols (ii7 V7 Imaj7)"):
            assert validate_answer(ex.id, ["Dm7", "G7", "Cmaj7"]).correct
            g = validate_answer(ex.id, ["Dm7", "G7", "C"])
            assert not g.correct and not g.items[2].correct and g.items[0].correct
            assert validate_answer(ex.id, ["Dm7", "G7"]).status == "incorrect"
            return
    raise AssertionError("no ii-V-I in C exercise found")


def test_tritone_substitute_of_g7_is_db7_and_c_sharp_7_is_accepted() -> None:
    ex = find("substitution", "beginner", r"tritone substitution for G7\?")
    assert validate_answer(ex.id, "Db7").status == "correct"
    g = validate_answer(ex.id, "C#7")
    assert g.correct and g.status == "enharmonic"  # spelling does not matter here
    assert not validate_answer(ex.id, "D7").correct


def test_related_ii_of_g7_is_dm7() -> None:
    ex = find("substitution", "beginner", r"related ii of G7")
    assert validate_answer(ex.id, "Dm7").correct
    assert not validate_answer(ex.id, "Am7").correct


def test_diatonic_chords_use_key_spelling() -> None:
    ex = find(
        "diatonic_chord",
        "advanced",
        r"In F# major, what is the diatonic seventh chord built on the third",
    )
    assert validate_answer(ex.id, "A#m7").correct
    g = validate_answer(ex.id, "Bbm7")
    assert g.status == "enharmonic" and not g.correct


# ------------------------------------------------------------------ cadences and ear training


def test_cadence_exercises_agree_with_the_engine() -> None:
    from music_theory.keys import Key
    from music_theory.notes import parse_note_name
    from music_theory.roman import analyze_progression, find_cadences

    labels = {
        "authentic": "authentic cadence (V–I)", "plagal": "plagal cadence (IV–I)",
        "half": "half cadence (ends on V)", "deceptive": "deceptive cadence (V–vi)",
    }  # fmt: skip
    seen = set()
    for d in DIFFICULTIES:
        for seed in range(60):
            ex = generate_exercise("cadence_identify", d, seed)
            m = re.match(r"In (\S+) (major|natural minor), a phrase ends (.+)\. Which", ex.prompt)
            assert m, ex.prompt
            key = Key(parse_note_name(m.group(1)), "minor" if "minor" in m.group(2) else "major")
            chords = [parse_chord(c) for c in m.group(3).split(" – ")]
            found = [
                c.kind
                for c in find_cadences(analyze_progression(chords, key))
                if c.end == len(chords) - 1
            ]
            assert len(found) == 1
            assert labels[found[0]] == reference_answer(ex)
            seen.add(found[0])
    assert seen == set(labels)


@pytest.mark.parametrize("kind", ["ear_interval", "ear_chord_quality", "ear_cadence"])
@pytest.mark.parametrize("difficulty", DIFFICULTIES)
def test_ear_exercises_have_audio_and_do_not_reveal_the_answer(kind: str, difficulty: str) -> None:
    for seed in range(30):
        ex = generate_exercise(kind, difficulty, seed)
        assert ex.show == ()  # nothing on the keyboard to give it away
        assert ex.play and all(e.notes and e.duration > 0 and e.start >= 0 for e in ex.play)
        assert all(0 <= n <= 127 for e in ex.play for n in e.notes)
        answer = str(reference_answer(ex))
        assert answer in ex.choices and len(set(ex.choices)) == len(ex.choices)
        assert answer.lower() not in ex.prompt.lower()
        assert KINDS[kind].ear_training


def test_ear_feedback_is_clear_when_wrong() -> None:
    ex = generate_exercise("ear_interval", "intermediate", 3)
    right = str(reference_answer(ex))
    wrong = next(c for c in ex.choices if c != right)
    g = validate_answer(ex.id, wrong)
    assert not g.correct and right in g.feedback and g.explanation


def test_ear_interval_semitones_match_the_played_notes() -> None:
    names = {1: "minor second", 2: "major second", 3: "minor third", 4: "major third",
             5: "perfect fourth", 6: "tritone", 7: "perfect fifth", 8: "minor sixth",
             9: "major sixth", 10: "minor seventh", 11: "major seventh", 12: "perfect octave"}  # fmt: skip
    for d in DIFFICULTIES:
        for seed in range(40):
            ex = generate_exercise("ear_interval", d, seed)
            played = sorted({n for e in ex.play for n in e.notes})
            assert names[played[-1] - played[0]] == reference_answer(ex)


def test_voice_leading_answer_really_is_the_smoothest() -> None:
    for d in DIFFICULTIES:
        for seed in range(40):
            ex = generate_exercise("voice_leading_choice", d, seed)
            assert len(ex.choices) >= 3 and len(set(ex.choices)) == len(ex.choices)
            g = validate_answer(ex.id, reference_answer(ex))
            assert g.correct and "semitones" in g.explanation


# ------------------------------------------------------------------ unambiguous chord examples


@pytest.mark.parametrize("kind", ["triad_identify", "seventh_identify", "extension_identify"])
@pytest.mark.parametrize("difficulty", DIFFICULTIES)
def test_identification_examples_have_one_clear_reading(kind: str, difficulty: str) -> None:
    for seed in range(40):
        ex = generate_exercise(kind, difficulty, seed)
        result = identify_chord([note_from_midi(m) for m in ex.show], max_candidates=4)
        assert result.status == "identified"
        assert result.best is not None
        assert validate_answer(ex.id, result.best.symbol).correct


# ------------------------------------------------------------------ interval names


@pytest.mark.parametrize(
    ("text", "short"),
    [
        ("M3", "M3"), ("major third", "M3"), ("Major Third", "M3"), ("perfect fifth", "P5"),
        ("minor seventh", "m7"), ("augmented fourth", "A4"), ("diminished fifth", "d5"),
        ("tritone", "A4"), ("aug4", "A4"), ("dim 5", "d5"), ("major ninth", "M9"),
        ("  m6  ", "m6"), ("perfect octave", "P8"),
    ],
)  # fmt: skip
def test_interval_answers_in_several_notations(text: str, short: str) -> None:
    assert parse_interval_answer(text).short == short


@pytest.mark.parametrize("bad", ["", "third", "big third", "M", "P3", "x9", "major"])
def test_bad_interval_names_are_rejected(bad: str) -> None:
    with pytest.raises(ExerciseError) as err:
        parse_interval_answer(bad)
    assert err.value.code == "unreadable_interval"


# ------------------------------------------------------------------ property-based


@settings(max_examples=60, deadline=None)
@given(
    st.sampled_from(sorted(KINDS)),
    st.sampled_from(DIFFICULTIES),
    st.integers(min_value=0, max_value=2**31 - 1),
)
def test_any_seed_generates_and_self_validates(kind: str, difficulty: str, seed: int) -> None:
    ex = generate_exercise(kind, difficulty, seed)
    assert validate_answer(ex.id, reference_answer(ex)).correct
    assert generate_exercise(kind, difficulty, seed) == ex


@settings(max_examples=80, deadline=None)
@given(
    st.sampled_from(sorted(KINDS)),
    st.integers(min_value=0, max_value=500),
    st.one_of(st.text(max_size=20), st.lists(st.text(max_size=6), min_size=1, max_size=8)),
)
def test_arbitrary_answers_never_crash(kind: str, seed: int, answer: object) -> None:
    ex = generate_exercise(kind, "intermediate", seed)
    try:
        grade = validate_answer(ex.id, answer)
    except ExerciseError as err:
        assert err.code == "invalid_answer"
    else:
        assert grade.status in {"correct", "enharmonic", "partial", "incorrect", "unreadable"}
        assert grade.feedback and grade.correct_answer
