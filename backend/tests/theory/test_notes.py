import math

import pytest
from hypothesis import given
from hypothesis import strategies as st

from music_theory.errors import TheoryError
from music_theory.notes import (
    NoteName,
    frequency_to_midi,
    frequency_to_note,
    is_enharmonic,
    midi_to_frequency,
    note_from_midi,
    note_with_spelling,
    parse_note,
    parse_note_name,
    spell_pitch_class,
)


def test_enharmonic_equivalence() -> None:
    assert parse_note("C#4").midi == parse_note("Db4").midi == 61
    assert is_enharmonic(parse_note("F#3"), parse_note("Gb3"))
    assert is_enharmonic(parse_note_name("E#"), parse_note_name("F"))
    assert not is_enharmonic(parse_note("C4"), parse_note("C5"))
    assert parse_note_name("C#") != parse_note_name("Db")  # same sound, different spelling


@pytest.mark.parametrize(
    ("text", "midi"),
    [("C4", 60), ("A4", 69), ("A0", 21), ("C8", 108), ("C-1", 0), ("G9", 127)],
)
def test_octave_numbering(text: str, midi: int) -> None:
    assert parse_note(text).midi == midi


@pytest.mark.parametrize(
    ("text", "midi"),
    [("B#3", 60), ("Cb4", 59), ("E#4", 65), ("Fb4", 64), ("Bbb3", 57), ("Fx4", 67)],
)
def test_theoretical_spellings(text: str, midi: int) -> None:
    assert parse_note(text).midi == midi


def test_octave_convention_is_configurable() -> None:
    n = parse_note("C3", middle_c_octave=3)
    assert n.midi == 60
    assert n.format(middle_c_octave=3) == "C3"
    assert n.format() == "C4"


def test_unicode_and_ascii_display() -> None:
    assert parse_note("Bb3").format(unicode=True) == "B♭3"
    assert parse_note_name("F♯").format() == "F#"
    assert parse_note_name("E##").format(unicode=True) == "E\U0001d12a"
    assert str(parse_note_name("Dbb")) == "Dbb"


@pytest.mark.parametrize("bad", ["", "H4", "c4", "C###4", "C", "4", "C#4#", "C 4 5"])
def test_parse_note_rejects_bad_input(bad: str) -> None:
    with pytest.raises(TheoryError):
        parse_note(bad)


def test_name_without_octave_rejects_octave() -> None:
    with pytest.raises(TheoryError):
        parse_note_name("C4")


def test_spelling_preference() -> None:
    assert str(spell_pitch_class(1, "sharps")) == "C#"
    assert str(spell_pitch_class(1, "flats")) == "Db"
    assert str(note_from_midi(70, "flats")) == "Bb4"


def test_note_with_spelling_picks_the_right_octave() -> None:
    assert str(note_with_spelling(60, NoteName("B", 1))) == "B#3"
    assert str(note_with_spelling(59, NoteName("C", -1))) == "Cb4"
    with pytest.raises(TheoryError):
        note_with_spelling(60, NoteName("D"))


def test_frequencies() -> None:
    assert midi_to_frequency(69) == pytest.approx(440.0)
    assert midi_to_frequency(60) == pytest.approx(261.6255653, rel=1e-7)
    assert midi_to_frequency(69, a4=432.0) == pytest.approx(432.0)
    assert midi_to_frequency(81) == pytest.approx(880.0)
    assert parse_note("A4").frequency() == pytest.approx(440.0)


def test_frequency_to_note() -> None:
    note, cents = frequency_to_note(261.63)
    assert str(note) == "C4" and abs(cents) < 0.1
    note, cents = frequency_to_note(450.0)
    assert str(note) == "A4" and cents == pytest.approx(38.9, abs=0.1)
    note, _ = frequency_to_note(432.0, a4=432.0)
    assert str(note) == "A4"


@pytest.mark.parametrize("bad", [0, -5, math.nan, math.inf, 1e9, 0.001])
def test_frequency_rejects_unusable_values(bad: float) -> None:
    with pytest.raises(TheoryError):
        frequency_to_midi(bad)


@given(st.integers(0, 127), st.sampled_from(["sharps", "flats"]))
def test_midi_round_trip(midi: int, prefer: str) -> None:
    note = note_from_midi(midi, prefer)  # type: ignore[arg-type]
    assert note.midi == midi
    assert parse_note(str(note)).midi == midi


@given(st.integers(0, 127), st.floats(400.0, 480.0))
def test_frequency_round_trip(midi: int, a4: float) -> None:
    got, cents = frequency_to_midi(midi_to_frequency(midi, a4), a4)
    assert got == midi and abs(cents) < 1e-6
