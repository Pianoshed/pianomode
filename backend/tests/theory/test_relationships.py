import pytest

from music_theory.chord_symbols import parse_chord
from music_theory.keys import Key
from music_theory.relationships import analyze_relationships, chord_relationship, minimal_motion
from music_theory.roman import analyze_progression


def rel(a: str, b: str):  # type: ignore[no-untyped-def]
    return chord_relationship(parse_chord(a), parse_chord(b))


@pytest.mark.parametrize(
    ("a", "b", "transform"),
    [("C", "Am", "R"), ("Am", "C", "R"), ("C", "Em", "L"), ("Em", "C", "L"),
     ("C", "Cm", "P"), ("Cm", "C", "P")],
)  # fmt: skip
def test_neo_riemannian_transforms(a: str, b: str, transform: str) -> None:
    r = rel(a, b)
    assert r.transform == transform
    assert len(r.common_tones) == 2
    assert f"transform_{transform}" in r.kinds


@pytest.mark.parametrize(
    ("a", "b"), [("C", "E"), ("C", "Eb"), ("C", "Ab"), ("C", "A"), ("Am", "Cm")]
)
def test_chromatic_mediants(a: str, b: str) -> None:
    r = rel(a, b)
    assert "chromatic_mediant" in r.kinds
    assert len(r.common_tones) == 1
    assert r.transform is None


@pytest.mark.parametrize(("a", "b"), [("C", "F"), ("C", "G"), ("C", "Dm"), ("C", "Em")])
def test_diatonic_neighbours_are_not_chromatic_mediants(a: str, b: str) -> None:
    assert "chromatic_mediant" not in rel(a, b).kinds


def test_tritone_substitution() -> None:
    r = rel("G7", "Db7")
    assert "tritone_substitution" in r.kinds
    assert [str(t) for t in r.common_tones] == ["B", "F"]
    assert rel("G7", "C#7").root_semitones == 6  # enharmonic spelling, same relationship
    assert "tritone_substitution" not in rel("G7", "Dbmaj7").kinds


def test_root_motion_and_common_tones() -> None:
    r = rel("Dm7", "G7")
    assert r.root_motion == "root up a fourth (down a fifth)"
    assert "falling_fifth" in r.kinds
    assert [str(t) for t in r.common_tones] == ["D", "F"]
    assert rel("G", "C").root_semitones == 5
    assert "rising_fifth" in rel("C", "G").kinds


def test_no_common_tones() -> None:
    r = rel("C", "F#")
    assert r.common_tones == ()
    assert "no_common_tones" in r.kinds and "tritone_motion" in r.kinds
    assert r.voice_leading_distance == 6


def test_minimal_motion_known_values() -> None:
    assert minimal_motion((0, 4, 7), (0, 3, 7)) == (1, 0)  # C to Cm
    assert minimal_motion((7, 11, 2, 5), (0, 4, 7)) == (2, 1)  # G7 to C
    assert minimal_motion((0, 4, 7), (0, 4, 7)) == (0, 0)


def test_non_diatonic_flag_needs_numerals() -> None:
    chords = [parse_chord(s) for s in ("C", "A7", "Dm")]
    assert all(r.non_diatonic is None for r in analyze_relationships(chords))
    flags = [
        r.non_diatonic
        for r in analyze_relationships(
            chords, analyze_progression(chords, Key(chords[0].root, "major"))
        )
    ]
    assert flags == [True, True]


def test_length_mismatch_is_refused() -> None:
    chords = [parse_chord("C"), parse_chord("G")]
    with pytest.raises(ValueError):
        analyze_relationships(chords, [])


def test_single_chord_has_no_pairs() -> None:
    assert analyze_relationships([parse_chord("C")]) == []
