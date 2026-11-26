import pytest
from hypothesis import given
from hypothesis import strategies as st

from music_theory.chord_symbols import (
    ChordSymbolError,
    SymbolStyle,
    format_chord,
    parse_chord,
)
from music_theory.chords import CHORD_TYPES, make_chord
from music_theory.notes import NoteName

SPEC_EXAMPLES = {
    "C": "major", "Cm": "minor", "Cmaj7": "major7", "C7": "dominant7", "Cm7": "minor7",
    "Cm7♭5": "half_diminished7", "Cdim7": "diminished7", "Caug": "augmented", "Csus2": "sus2",
    "Csus4": "sus4", "Cadd9": "add9", "C9": "dominant9", "C13": "dominant13", "Dm7/C": "minor7",
}  # fmt: skip


@pytest.mark.parametrize(("symbol", "type_id"), SPEC_EXAMPLES.items())
def test_spec_examples_parse(symbol: str, type_id: str) -> None:
    assert parse_chord(symbol).type.id == type_id


def test_slash_chord_bass() -> None:
    chord = parse_chord("Dm7/C")
    assert str(chord.root) == "D" and str(chord.bass) == "C" and chord.inversion() == 3
    assert parse_chord("C/E").inversion() == 1
    assert str(parse_chord("F#m7b5/Bb").bass) == "Bb"


@pytest.mark.parametrize(
    ("alias", "type_id"),
    [
        ("CM7", "major7"), ("CΔ", "major7"), ("CΔ7", "major7"), ("C△7", "major7"), ("CMaj7", "major7"),
        ("C-7", "minor7"), ("Cmin7", "minor7"), ("C-", "minor"), ("Cmin", "minor"),
        ("Cø", "half_diminished7"), ("Cø7", "half_diminished7"), ("Cm7(b5)", "half_diminished7"),
        ("C°", "diminished"), ("C°7", "diminished7"), ("Co7", "diminished7"),
        ("C+", "augmented"), ("C+7", "dominant7_sharp5"), ("Caug7", "dominant7_sharp5"),
        ("CmM7", "minor_major7"), ("Cm(maj7)", "minor_major7"), ("C-Δ7", "minor_major7"),
        ("C6/9", "six_nine"), ("C7(b9)", "dominant7_flat9"), ("C7♯9", "dominant7_sharp9"),
        ("Calt", "altered"), ("Csus", "sus4"), ("C add9", "add9"), ("C5", "power"),
    ],
)  # fmt: skip
def test_aliases_normalise(alias: str, type_id: str) -> None:
    assert parse_chord(alias).type.id == type_id


@pytest.mark.parametrize(
    ("symbol", "root"),
    [
        ("Bb7", "Bb"),
        ("B♭7", "Bb"),
        ("F#m", "F#"),
        ("F♯m", "F#"),
        ("Ebmaj7", "Eb"),
        ("C##dim", "C##"),
    ],
)
def test_root_accidentals(symbol: str, root: str) -> None:
    assert str(parse_chord(symbol).root) == root


def test_flat_five_versus_flat_root() -> None:
    assert str(parse_chord("Db5").root) == "Db" and parse_chord("Db5").type.id == "power"
    assert parse_chord("Dm7b5").type.id == "half_diminished7"


@pytest.mark.parametrize(
    ("bad", "code"),
    [
        ("", "empty_symbol"), ("   ", "empty_symbol"), ("H7", "invalid_root"), ("7", "invalid_root"),
        ("c7", "invalid_root"), ("Cmaj", "unknown_quality"), ("CM", "unknown_quality"),
        ("Cxyz", "unknown_quality"), ("Cm7b", "unknown_quality"), ("Cdim9", "unknown_quality"),
        ("C7/", "invalid_bass"), ("C/H", "invalid_bass"), ("C/E4", "invalid_bass"),
        ("Cxyz/E", "unknown_quality"),
    ],
)  # fmt: skip
def test_malformed_symbols_are_rejected_with_a_code(bad: str, code: str) -> None:
    with pytest.raises(ChordSymbolError) as err:
        parse_chord(bad)
    assert err.value.code == code and err.value.symbol == bad


def test_error_explains_the_ambiguous_maj() -> None:
    with pytest.raises(ChordSymbolError) as err:
        parse_chord("Cmaj")
    assert "Cmaj7" in err.value.message and err.value.position == 1


def test_default_formatting() -> None:
    assert format_chord(make_chord("C", "half_diminished7")) == "Cm7b5"
    assert format_chord(make_chord("D", "minor7", "C")) == "Dm7/C"
    assert format_chord(make_chord("Bb", "major7")) == "Bbmaj7"
    assert format_chord(make_chord("C", "minor_major7")) == "CmMaj7"
    assert format_chord(make_chord("C", "major")) == "C"


def test_style_options() -> None:
    jazz = SymbolStyle(major7="Δ7", minor="-", half_diminished="ø7", diminished="°", augmented="+")
    assert format_chord(make_chord("C", "major7"), jazz) == "CΔ7"
    assert format_chord(make_chord("C", "minor7"), jazz) == "C-7"
    assert format_chord(make_chord("C", "half_diminished7"), jazz) == "Cø7"
    assert format_chord(make_chord("C", "diminished7"), jazz) == "C°7"
    assert format_chord(make_chord("C", "augmented"), jazz) == "C+"
    assert format_chord(make_chord("C", "minor_major7"), jazz) == "C-Δ7"
    uni = SymbolStyle(unicode_accidentals=True)
    assert format_chord(make_chord("Bb", "half_diminished7"), uni) == "B♭m7♭5"
    assert format_chord(make_chord("F#", "dominant7_sharp9"), uni) == "F♯7♯9"


def test_aliases_do_not_collide() -> None:
    from music_theory.chord_symbols import _ALIASES

    assert len(_ALIASES) > len(CHORD_TYPES) * 2


styles = st.builds(
    SymbolStyle,
    major7=st.sampled_from(["maj7", "M7", "Δ7"]),
    minor=st.sampled_from(["m", "min", "-"]),
    half_diminished=st.sampled_from(["m7b5", "ø7"]),
    diminished=st.sampled_from(["dim", "°"]),
    augmented=st.sampled_from(["aug", "+"]),
    unicode_accidentals=st.booleans(),
)


@given(
    st.sampled_from(sorted(CHORD_TYPES)),
    st.sampled_from("ABCDEFG"),
    st.integers(-2, 2),
    st.one_of(st.none(), st.tuples(st.sampled_from("ABCDEFG"), st.integers(-1, 1))),
    styles,
)
def test_format_then_parse_round_trips(type_id: str, letter: str, acc: int, bass, style) -> None:  # type: ignore[no-untyped-def]
    chord = make_chord(NoteName(letter, acc), type_id, None if bass is None else NoteName(*bass))
    assert parse_chord(format_chord(chord, style)) == chord
