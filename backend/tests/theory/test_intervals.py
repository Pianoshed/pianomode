import pytest
from hypothesis import given
from hypothesis import strategies as st

from music_theory.errors import TheoryError
from music_theory.intervals import (
    SIMPLE_INTERVALS,
    Interval,
    interval_between_names,
    interval_between_notes,
    interval_class,
    parse_interval,
    transpose_name,
    transpose_note,
)
from music_theory.notes import NoteName, parse_note, parse_note_name

FROM_C = [
    ("P1", "C"), ("m2", "Db"), ("M2", "D"), ("m3", "Eb"), ("M3", "E"), ("P4", "F"), ("A4", "F#"),
    ("d5", "Gb"), ("P5", "G"), ("m6", "Ab"), ("M6", "A"), ("m7", "Bb"), ("M7", "B"), ("P8", "C"),
]  # fmt: skip


@pytest.mark.parametrize(("symbol", "expected"), FROM_C)
def test_construct_from_c(symbol: str, expected: str) -> None:
    assert str(transpose_name(parse_note_name("C"), parse_interval(symbol))) == expected


@pytest.mark.parametrize(
    ("symbol", "semitones", "long"),
    [
        ("M3", 4, "major third"), ("m3", 3, "minor third"), ("P5", 7, "perfect fifth"),
        ("A4", 6, "augmented fourth"), ("d5", 6, "diminished fifth"), ("d7", 9, "diminished seventh"),
        ("M9", 14, "major ninth"), ("m10", 15, "minor tenth"), ("P11", 17, "perfect eleventh"),
        ("M13", 21, "major thirteenth"), ("AA4", 7, "doubly augmented fourth"), ("P15", 24, "perfect fifteenth"),
    ],
)  # fmt: skip
def test_names_and_sizes(symbol: str, semitones: int, long: str) -> None:
    iv = parse_interval(symbol)
    assert iv.semitones == semitones and iv.long == long and iv.short == symbol
    assert iv.whole_tones == semitones / 2


def test_compound_flags_and_reduction() -> None:
    assert parse_interval("M9").is_compound and not parse_interval("P8").is_compound
    assert parse_interval("M10").simple() == parse_interval("M3")


@pytest.mark.parametrize("bad", ["P3", "M5", "m4", "M1", "d1", "X3", "5", "P", "m0", "AAAA4"])
def test_invalid_intervals_are_rejected(bad: str) -> None:
    with pytest.raises(TheoryError):
        parse_interval(bad)


@pytest.mark.parametrize(
    ("a", "b"),
    [
        ("M3", "m6"),
        ("P5", "P4"),
        ("A4", "d5"),
        ("m7", "M2"),
        ("P1", "P8"),
        ("P8", "P1"),
        ("m2", "M7"),
    ],
)
def test_inversion(a: str, b: str) -> None:
    assert parse_interval(a).inverted() == parse_interval(b)


@given(st.sampled_from(SIMPLE_INTERVALS))
def test_inversion_is_an_involution_and_sums_to_an_octave(iv: Interval) -> None:
    inv = iv.inverted()
    assert inv.inverted() == iv
    assert iv.semitones + inv.semitones == 12


@given(
    st.sampled_from("CDEFGAB"),
    st.integers(-1, 1),
    st.sampled_from(SIMPLE_INTERVALS[:-1]),
)
def test_transpose_up_down_and_measure_round_trip(letter: str, acc: int, iv: Interval) -> None:
    start = NoteName(letter, acc)
    try:
        up = transpose_name(start, iv)
    except TheoryError:
        return  # needs triple accidentals; correctly refused
    assert transpose_name(up, iv, down=True) == start
    assert interval_between_names(start, up) == iv
    assert up.pitch_class == (start.pitch_class + iv.semitones) % 12


def test_between_notes_counts_octaves_and_spelling() -> None:
    assert interval_between_notes(parse_note("C4"), parse_note("E5")).short == "M10"
    assert interval_between_notes(parse_note("E5"), parse_note("C4")).short == "M10"  # order-free
    assert interval_between_notes(parse_note("B#3"), parse_note("C4")).short == "d2"
    assert interval_between_notes(parse_note("C4"), parse_note("C#4")).short == "A1"
    assert interval_between_notes(parse_note("C4"), parse_note("C4")).short == "P1"
    assert interval_between_notes(parse_note("C4"), parse_note("C6")).short == "P15"


def test_between_names_edge_cases() -> None:
    assert interval_between_names(parse_note_name("C"), parse_note_name("B#")).short == "A7"
    assert interval_between_names(parse_note_name("C"), parse_note_name("Cb")).short == "d8"
    assert interval_between_names(parse_note_name("E"), parse_note_name("C")).short == "m6"


def test_transpose_note_keeps_octave_and_spelling() -> None:
    assert str(transpose_note(parse_note("A4"), parse_interval("M3"))) == "C#5"
    assert str(transpose_note(parse_note("C4"), parse_interval("m2"), down=True)) == "B3"
    assert str(transpose_note(parse_note("C4"), parse_interval("d4"))) == "Fb4"


def test_transposition_needing_triple_accidentals_is_refused() -> None:
    with pytest.raises(TheoryError) as err:
        transpose_name(parse_note_name("D##"), parse_interval("A4"))  # would be G###
    assert err.value.code == "spelling_overflow"


def test_interval_class_is_octave_and_direction_free() -> None:
    assert interval_class(0, 7) == 5 and interval_class(7, 0) == 5 and interval_class(0, 6) == 6
