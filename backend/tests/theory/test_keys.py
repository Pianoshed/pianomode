import pytest

from music_theory.errors import TheoryError
from music_theory.keys import Key, key_signature
from music_theory.notes import parse_note_name as n


@pytest.mark.parametrize(
    ("tonic", "mode", "fifths"),
    [
        ("C", "major", 0), ("G", "major", 1), ("D", "major", 2), ("F", "major", -1),
        ("Bb", "major", -2), ("F#", "major", 6), ("Db", "major", -5), ("C#", "major", 7),
        ("Cb", "major", -7), ("A", "minor", 0), ("E", "minor", 1), ("D", "minor", -1),
        ("C", "minor", -3), ("D", "dorian", 0), ("E", "phrygian", 0), ("F", "lydian", 0),
        ("G", "mixolydian", 0), ("B", "locrian", 0),
    ],
)  # fmt: skip
def test_key_signatures(tonic: str, mode: str, fifths: int) -> None:
    assert key_signature(n(tonic), mode).fifths == fifths


def test_accidentals_and_description() -> None:
    assert [str(a) for a in key_signature(n("D")).accidentals()] == ["F#", "C#"]
    assert [str(a) for a in key_signature(n("Bb")).accidentals()] == ["Bb", "Eb"]
    assert key_signature(n("C")).describe() == "no sharps or flats"
    assert key_signature(n("A")).describe() == "3 sharps (F# C# G#)"


def test_theoretical_keys_use_double_accidentals() -> None:
    sig = key_signature(n("G#"))
    assert sig.fifths == 8 and not sig.is_practical
    assert [str(a) for a in sig.accidentals()] == ["F##", "C#", "G#", "D#", "A#", "E#", "B#"]
    assert str(key_signature(n("Fb")).accidentals()[0]) == "Bbb"  # 8 flats


def test_spelling_in_context() -> None:
    assert str(key_signature(n("F")).spell(10)) == "Bb"  # diatonic
    assert str(key_signature(n("D")).spell(6)) == "F#"
    assert str(key_signature(n("G")).spell(3)) == "D#"  # chromatic in a sharp key
    assert str(key_signature(n("F")).spell(1)) == "Db"  # chromatic in a flat key


def test_relative_and_parallel() -> None:
    assert str(Key(n("C")).relative()) == "A minor"
    assert str(Key(n("A"), "minor").relative()) == "C major"
    assert str(Key(n("Eb")).relative()) == "C minor"
    assert str(Key(n("F#"), "minor").relative()) == "A major"
    assert str(Key(n("C")).parallel()) == "C minor"
    assert Key(n("E")).relative().signature == Key(n("E")).signature


def test_key_scale_and_bad_mode() -> None:
    assert " ".join(str(x) for x in Key(n("E"), "minor").scale().notes()) == "E F# G A B C D"
    with pytest.raises(TheoryError):
        Key(n("C"), "dorian")
    with pytest.raises(TheoryError):
        key_signature(n("C"), "weird")
