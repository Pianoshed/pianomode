import json

import pytest

from music_theory.errors import TheoryError
from music_theory.scales import (
    CHURCH_MODES,
    ScaleDefinitionError,
    default_registry,
    load_definitions,
    make_scale,
    parse_definition,
)

ROOTS = ["C", "Db", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B"]


def names(root: str, scale: str, direction: str = "ascending") -> str:
    return " ".join(str(n) for n in make_scale(root, scale).notes(direction))  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("root", "expected"),
    [
        ("C", "C D E F G A B"), ("G", "G A B C D E F#"), ("D", "D E F# G A B C#"),
        ("A", "A B C# D E F# G#"), ("E", "E F# G# A B C# D#"), ("B", "B C# D# E F# G# A#"),
        ("F#", "F# G# A# B C# D# E#"), ("Db", "Db Eb F Gb Ab Bb C"), ("Ab", "Ab Bb C Db Eb F G"),
        ("Eb", "Eb F G Ab Bb C D"), ("Bb", "Bb C D Eb F G A"), ("F", "F G A Bb C D E"),
    ],
)  # fmt: skip
def test_major_scale_spelling_in_all_keys(root: str, expected: str) -> None:
    assert names(root, "major") == expected


def test_minor_forms() -> None:
    assert names("A", "natural_minor") == "A B C D E F G"
    assert names("A", "harmonic_minor") == "A B C D E F G#"
    assert names("A", "melodic_minor") == "A B C D E F# G#"
    assert names("A", "melodic_minor", "descending") == "A G F E D C B"
    assert names("C", "harmonic_minor") == "C D Eb F G Ab B"


def test_modes_of_c() -> None:
    expected = {
        "ionian": "C D E F G A B", "dorian": "C D Eb F G A Bb", "phrygian": "C Db Eb F G Ab Bb",
        "lydian": "C D E F# G A B", "mixolydian": "C D E F G A Bb", "aeolian": "C D Eb F G Ab Bb",
        "locrian": "C Db Eb F Gb Ab Bb",
    }  # fmt: skip
    assert set(expected) == set(CHURCH_MODES)
    for mode, notes in expected.items():
        assert names("C", mode) == notes


def test_other_scales() -> None:
    assert names("C", "major_pentatonic") == "C D E G A"
    assert names("A", "minor_pentatonic") == "A C D E G"
    assert names("A", "blues") == "A C D Eb E G"
    assert names("C", "whole_tone") == "C D E F# G# Bb"
    assert names("C", "diminished_whole_half") == "C D Eb F Gb Ab A B"
    assert names("C", "diminished_half_whole") == "C Db Eb E F# G A Bb"
    assert names("C", "harmonic_major") == "C D E F G Ab B"
    assert len(make_scale("C", "chromatic").notes()) == 12


@pytest.mark.parametrize("scale_id", default_registry().ids())
@pytest.mark.parametrize("root", ROOTS)
def test_every_scale_in_every_key(scale_id: str, root: str) -> None:
    scale = make_scale(root, scale_id)
    pcs = [n.pitch_class for n in scale.notes()]
    root_pc = scale.root.pitch_class
    assert pcs == [(root_pc + i.semitones) % 12 for i in scale.definition.formula]
    assert len(set(pcs)) == len(pcs)
    if scale.definition.size == 7:
        assert len({n.letter for n in scale.notes()}) == 7  # one letter per degree


def test_degrees_and_membership() -> None:
    scale = make_scale("G", "major")
    assert str(scale.note_at_degree(7)) == "F#"
    assert scale.degrees()[2].interval.short == "M3"
    assert scale.contains(6) and not scale.contains(5)
    with pytest.raises(TheoryError):
        scale.note_at_degree(8)


def test_keyboard_notes() -> None:
    notes = make_scale("C", "major").keyboard_notes(4, include_octave=True)
    assert [n.midi for n in notes] == [60, 62, 64, 65, 67, 69, 71, 72]
    assert [str(n) for n in make_scale("B", "major").keyboard_notes(3)][:2] == ["B3", "C#4"]


def test_aliases_and_unknown_scale() -> None:
    assert default_registry().get("Minor") is default_registry().get("natural-minor")
    with pytest.raises(TheoryError) as err:
        make_scale("C", "lochrian")
    assert err.value.code == "unknown_scale"


def test_impossible_spelling_asks_for_the_enharmonic_root() -> None:
    with pytest.raises(TheoryError) as err:
        make_scale("G#", "major").notes()  # would need F## and more fine; use a harder one
        make_scale("D##", "major").notes()
    assert err.value.code == "spelling_overflow"


def test_administrators_can_add_a_scale_without_code_changes() -> None:
    registry = default_registry().copy()
    text = json.dumps(
        {
            "scales": [
                {"id": "insen", "name": "In (Insen)", "formula": ["P1", "m2", "P4", "P5", "m7"]}
            ]
        }
    )
    for definition in load_definitions(text):
        registry.register(definition)
    assert " ".join(str(n) for n in make_scale("D", "insen", registry).notes()) == "D Eb G A C"
    assert "insen" not in default_registry().ids()  # shared defaults untouched


def test_updating_and_duplicate_registration() -> None:
    registry = default_registry().copy()
    existing = registry.get("major")
    with pytest.raises(ScaleDefinitionError):
        registry.register(existing)
    registry.register(existing, replace=True)
    clash = parse_definition(
        {"id": "other", "name": "X", "formula": ["P1", "M2"], "aliases": ["ionian"]}
    )
    with pytest.raises(ScaleDefinitionError):
        registry.register(clash)


@pytest.mark.parametrize(
    "bad",
    [
        {"id": "x", "name": "X", "formula": ["M2", "M3"]},  # must start on P1
        {"id": "x", "name": "X", "formula": ["P1", "M3", "M2"]},  # must rise
        {"id": "x", "name": "X", "formula": ["P1", "P8"]},  # must stay inside the octave
        {"id": "X Y", "name": "X", "formula": ["P1", "M2"]},  # bad id
        {"id": "x", "name": " ", "formula": ["P1", "M2"]},  # no name
        {"id": "x", "name": "X", "formula": ["P1", "P3"]},  # not an interval
        {"id": "x", "name": "X"},  # missing formula
        {"id": "x", "name": "X", "formula": ["P1", "M2"], "descending": ["P1"]},  # length mismatch
    ],
)
def test_invalid_definitions_are_rejected(bad: dict[str, object]) -> None:
    with pytest.raises(ScaleDefinitionError):
        parse_definition(bad)


def test_bad_json_is_reported() -> None:
    with pytest.raises(ScaleDefinitionError):
        load_definitions("{nope")
    with pytest.raises(ScaleDefinitionError):
        load_definitions('{"other": []}')
