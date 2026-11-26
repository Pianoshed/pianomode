"""Movement library: four derived levels, determinism, bounds, serialisation, lifecycle."""

from dataclasses import replace

import pytest

from music_theory.errors import TheoryError
from music_theory.movements import (
    LEVELS,
    RECIPES,
    TRANSITIONS,
    CustomChord,
    MovementDefinition,
    build_movement,
    check_definition,
    check_transition,
    definition_from_dict,
    definition_to_dict,
    in_key,
    make_slug,
    publication_blockers,
)
from music_theory.progressions import default_library, realize, substitute_tritone
from music_theory.validation import parse_key
from music_theory.voicings import PIANO_HI, PIANO_LO, constraints_for_skill

KEY_C = parse_key("C")


def definition(template: str = "ii_v_i", tonic: str = "C", **kw) -> MovementDefinition:
    lib = default_library()
    mode = lib.get(template).mode
    fields = dict(
        name="Test movement", key=parse_key(tonic, mode), template_id=template,
        author="Ada", theory_explanation="Why it works.", tags=("jazz",),
    )  # fmt: skip
    return MovementDefinition(**{**fields, **kw})


def symbols(built, level):
    return [s.symbol for s in built.version(level).steps]


# ------------------------------------------------------------------ known answers


def test_ii_v_i_levels_in_c():
    b = build_movement(definition())
    assert symbols(b, "beginner") == ["Dm", "G", "C"]
    assert symbols(b, "intermediate") == ["Dm7", "G7", "Cmaj7"]
    assert symbols(b, "advanced") == ["Dm7", "G7", "Cmaj7"]
    # expert: the V7 resolves down a fifth, so it becomes the tritone substitute
    assert symbols(b, "expert") == ["Dm7", "Db7", "Cmaj7"]
    assert [v.level for v in b.versions] == list(LEVELS)


def test_beginner_is_root_position_triads_with_a_bass_note():
    for step in build_movement(definition("major_i_iv_v_i")).version("beginner").steps:
        assert step.inversion == "root position"
        assert len(step.chord_tones) == 3
        assert len(step.right) == 3
        assert step.left, "beginner left hand plays a bass note"


@pytest.mark.parametrize(
    ("tonic", "sub"),
    [
        ("C", "Db7"),
        ("Db", "D7"),
        ("Eb", "E7"),
        ("F", "Gb7"),
        ("Gb", "G7"),
        ("F#", "G7"),
        ("Ab", "A7"),
    ],
)
def test_tritone_substitute_is_spelled_the_way_a_chart_writes_it(tonic, sub):
    b = build_movement(definition("ii_v_i", tonic))
    assert symbols(b, "expert")[1] == sub
    assert b.version("expert").steps[1].role == "substitution"


def test_substitution_only_where_a_dominant_resolves_down_a_fifth():
    # I-V-vi-IV: V goes to vi, not down a fifth -> expert keeps G7 and says so
    b = build_movement(definition("pop_i_v_vi_iv"))
    assert symbols(b, "expert")[1] == "G7"
    assert any("no tritone substitute" in v.lower() for v in b.version("expert").variations)


def test_minor_movement_is_built_in_minor():
    b = build_movement(definition("minor_ii_v_i", "A"))
    assert symbols(b, "intermediate")[0] == "Bm7b5"


# ------------------------------------------------------------------ every template, every level


@pytest.mark.parametrize("template_id", default_library().ids())
def test_every_template_builds_valid_voicings_at_all_levels(template_id):
    mode = default_library().get(template_id).mode
    b = build_movement(definition(template_id, "C" if mode == "major" else "A"))
    for v in b.versions:
        c = constraints_for_skill(v.level, **dict(RECIPES[v.level].constraint_overrides))
        assert v.validation_errors == (), (template_id, v.level, v.validation_errors)
        for step in v.steps:
            notes = [*step.left, *step.right]
            assert notes, (template_id, v.level, step.symbol)
            assert all(PIANO_LO <= n <= PIANO_HI for n in notes)
            assert all(c.lh_range[0] <= n <= c.lh_range[1] for n in step.left)
            assert all(c.rh_range[0] <= n <= c.rh_range[1] for n in step.right)
            assert max(step.right, default=0) - min(step.right, default=0) <= c.max_span
        assert publication_blockers(b) == []


def test_playback_events_match_steps():
    v = build_movement(definition()).version("intermediate")
    for step in v.steps:
        ev = [e for e in v.playback if e.chord_index == step.index]
        assert sorted(e.midi for e in ev if e.hand == "L") == sorted(step.left)
        assert sorted(e.midi for e in ev if e.hand == "R") == sorted(step.right)
        assert all(e.start_beat == step.beat and e.duration_beats == step.duration for e in ev)


# ------------------------------------------------------------------ determinism and keys


def test_same_definition_gives_identical_result():
    a = build_movement(definition("ii_v_i_vi"))
    b = build_movement(definition("ii_v_i_vi"))
    for va, vb in zip(a.versions, b.versions, strict=True):
        assert [(s.left, s.right) for s in va.steps] == [(s.left, s.right) for s in vb.steps]
        assert va.total_cost == vb.total_cost


def test_transposing_a_template_movement_keeps_numerals_and_quality():
    d = definition()
    reference = build_movement(d).version("intermediate")
    ref_numerals = [s.roman for s in reference.steps]
    ref_quality = [s.symbol.lstrip("ABCDEFG#b") for s in reference.steps]
    assert ref_quality == ["m7", "7", "maj7"]
    for tonic in ("C", "Db", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B"):
        v = build_movement(in_key(d, tonic)).version("intermediate")
        assert [s.roman for s in v.steps] == ref_numerals, tonic
        assert [s.symbol.lstrip("ABCDEFG#b") for s in v.steps] == ref_quality, tonic


def test_transposing_custom_chords_respells_for_the_new_key():
    d = MovementDefinition(
        name="Custom", key=KEY_C,
        custom_chords=(CustomChord("Dm7"), CustomChord("G7"), CustomChord("Cmaj7", 8)),
        author="Ada", theory_explanation="x", tags=("jazz",),
    )  # fmt: skip
    moved = in_key(d, "Eb")
    assert [c.symbol for c in moved.custom_chords] == ["Fm7", "Bb7", "Ebmaj7"]
    assert [c.beats for c in moved.custom_chords] == [4.0, 4.0, 8.0]


def test_transposition_options_are_twelve_distinct_keys():
    b = build_movement(definition())
    assert len(set(b.transposition_options)) == 12


# ------------------------------------------------------------------ validation


@pytest.mark.parametrize(
    ("change", "code"),
    [
        ({"name": "  "}, "invalid_name"),
        ({"tempo": 5}, "invalid_tempo"),
        ({"time_signature": (4, 3)}, "invalid_time_signature"),
        ({"tags": ("x",) * 13}, "invalid_tags"),
        ({"levels": ("beginner", "beginner")}, "unknown_level"),
        ({"levels": ("wizard",)}, "unknown_level"),
        ({"practice": {"beginner": "x" * 5000}}, "text_too_long"),
        ({"practice": {"wizard": "hi"}}, "unknown_level"),
        ({"custom_chords": (CustomChord("C"),)}, "invalid_source"),  # template AND custom
        ({"template_id": None}, "invalid_source"),  # neither
    ],
)
def test_bad_definitions_are_rejected_with_stable_codes(change, code):
    with pytest.raises(TheoryError) as exc:
        check_definition(replace(definition(), **change))
    assert exc.value.code == code


def test_unknown_template_is_rejected():
    with pytest.raises(TheoryError):
        build_movement(definition(template_id="nope"))


def test_malformed_chord_symbol_is_never_reinterpreted():
    d = MovementDefinition(
        name="Bad", key=KEY_C, custom_chords=(CustomChord("Cmaj"), CustomChord("G7")),
        author="a", theory_explanation="x", tags=("x",),
    )  # fmt: skip
    with pytest.raises(TheoryError):
        build_movement(d)


def test_publication_blockers_name_what_is_missing():
    b = build_movement(definition(author=None, theory_explanation="", tags=()))
    text = " ".join(publication_blockers(b))
    assert "author" in text and "theory explanation" in text and "tag" in text


# ------------------------------------------------------------------ serialisation


def test_definition_round_trips():
    d = definition(practice={"beginner": "Slowly."}, variations=("Try swing.",), source="Book")
    assert definition_from_dict(definition_to_dict(d)) == d


@pytest.mark.parametrize(
    ("patch", "code"),
    [
        ({"schema_version": 99}, "unsupported_movement_version"),
        ({"name": 5}, "invalid_movement_data"),
        ({"tempo": True}, "invalid_movement_data"),
        ({"time_signature": [4]}, "invalid_time_signature"),
        ({"practice": {"beginner": 3}}, "invalid_movement_data"),
        ({"custom_chords": [{"beats": 4}]}, "invalid_movement_data"),
    ],
)
def test_corrupt_stored_data_is_refused_not_guessed(patch, code):
    data = {**definition_to_dict(definition()), **patch}
    with pytest.raises(TheoryError) as exc:
        definition_from_dict(data)
    assert exc.value.code == code


def test_slug():
    assert make_slug("I–IV–V–I in C!") == "i-iv-v-i-in-c"
    assert make_slug("???") == "movement"


# ------------------------------------------------------------------ lifecycle


def test_every_allowed_transition_has_an_action_and_every_other_is_refused():
    statuses = list(TRANSITIONS)
    for a in statuses:
        for b in statuses:
            if b in TRANSITIONS[a]:
                assert check_transition(a, b)
            else:
                with pytest.raises(TheoryError) as exc:
                    check_transition(a, b)
                assert exc.value.code == "invalid_transition"


def test_publishing_requires_approval_first():
    with pytest.raises(TheoryError):
        check_transition("draft", "published")
    assert check_transition("approved", "published") == "publish"
    assert check_transition("published", "approved") == "unpublish"
    assert check_transition("archived", "draft") == "restore"


def test_unknown_status_is_an_error():
    with pytest.raises(TheoryError) as exc:
        check_transition("draft", "live")
    assert exc.value.code == "unknown_status"


def test_tritone_helper_on_engine_matches_expert_version():
    p = realize(default_library().get("ii_v_i"), KEY_C, "sevenths")
    assert str(substitute_tritone(p, 1).chords[1].chord) == "Db7"
