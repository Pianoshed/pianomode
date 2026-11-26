import pytest
from hypothesis import given
from hypothesis import strategies as st

from music_theory.chords import (
    CHORD_TYPES,
    Chord,
    find_chord_type,
    inversion_name,
    make_chord,
)
from music_theory.errors import TheoryError
from music_theory.harmony import diatonic_chords
from music_theory.intervals import intervals, parse_interval
from music_theory.scales import make_scale

ROOTS = ["C", "Db", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B"]


def spelled(root: str, type_id: str) -> str:
    return " ".join(str(t) for t in make_chord(root, type_id).tones())


@pytest.mark.parametrize(
    ("type_id", "expected"),
    [
        ("major", "C E G"), ("minor", "C Eb G"), ("diminished", "C Eb Gb"), ("augmented", "C E G#"),
        ("sus2", "C D G"), ("sus4", "C F G"), ("power", "C G"),
        ("major7", "C E G B"), ("minor7", "C Eb G Bb"), ("dominant7", "C E G Bb"),
        ("minor_major7", "C Eb G B"), ("half_diminished7", "C Eb Gb Bb"),
        ("diminished7", "C Eb Gb Bbb"), ("major6", "C E G A"), ("minor6", "C Eb G A"),
        ("dominant7_flat5", "C E Gb Bb"), ("dominant7_sharp5", "C E G# Bb"),
        ("add9", "C E G D"), ("dominant9", "C E G Bb D"), ("major9", "C E G B D"),
        ("minor9", "C Eb G Bb D"), ("minor_major9", "C Eb G B D"),
        ("dominant11", "C E G Bb D F"), ("dominant13", "C E G Bb D A"),
        ("dominant7_flat9", "C E G Bb Db"), ("dominant7_sharp9", "C E G Bb D#"),
        ("dominant7_sharp11", "C E G Bb F#"), ("altered", "C E Gb Bb Db D# Ab"),
        ("quartal3", "C F Bb"), ("quartal4", "C F Bb Eb"),
    ],
)  # fmt: skip
def test_known_answers_on_c(type_id: str, expected: str) -> None:
    assert spelled("C", type_id) == expected


def test_half_diminished_is_not_minor_triad_or_fully_diminished() -> None:
    half = CHORD_TYPES["half_diminished7"].formula
    assert half == intervals("P1", "m3", "d5", "m7")
    assert half != CHORD_TYPES["diminished7"].formula
    assert half[:3] != CHORD_TYPES["minor"].formula
    assert find_chord_type(half) is CHORD_TYPES["half_diminished7"]


def test_formulas_are_well_formed() -> None:
    assert len(CHORD_TYPES) >= 40
    for t in CHORD_TYPES.values():
        assert t.formula[0] == parse_interval("P1"), t.id
        semis = [i.semitones for i in t.formula]
        assert semis == sorted(set(semis)), t.id
        assert set(t.omissible) <= set(t.formula) - {t.formula[0]}, t.id
        assert find_chord_type(t.formula) is t, t.id  # no two types share a formula


@pytest.mark.parametrize("type_id", list(CHORD_TYPES))
@pytest.mark.parametrize("root", ROOTS)
def test_every_chord_in_every_key(type_id: str, root: str) -> None:
    chord = make_chord(root, type_id)
    tones = chord.tones()
    root_pc = chord.root.pitch_class
    assert [t.pitch_class for t in tones] == [
        (root_pc + i.semitones) % 12 for i in chord.type.formula
    ]


def test_diatonic_chords_in_c_major() -> None:
    triads = [str(d.chord) for d in diatonic_chords(make_scale("C", "major"))]
    assert triads == ["C", "Dm", "Em", "F", "G", "Am", "Bdim"]
    sevenths = [str(d.chord) for d in diatonic_chords(make_scale("C", "major"), 4)]
    assert sevenths == ["Cmaj7", "Dm7", "Em7", "Fmaj7", "G7", "Am7", "Bm7b5"]
    d = diatonic_chords(make_scale("C", "major"), 4)
    assert [str(t) for t in d[1].tones] == ["D", "F", "A", "C"]  # Dm7 in C major
    assert [str(t) for t in d[4].tones] == ["G", "B", "D", "F"]  # G7 in C major


def test_diatonic_chords_in_other_scales() -> None:
    hm = [str(d.chord) for d in diatonic_chords(make_scale("A", "harmonic_minor"), 4)]
    assert hm == ["AmMaj7", "Bm7b5", "Cmaj7#5", "Dm7", "E7", "Fmaj7", "G#dim7"]
    mm = [str(d.chord) for d in diatonic_chords(make_scale("C", "melodic_minor"), 4)]
    assert mm == ["CmMaj7", "Dm7", "Ebmaj7#5", "F7", "G7", "Am7b5", "Bm7b5"]
    minor = [str(d.chord) for d in diatonic_chords(make_scale("A", "natural_minor"))]
    assert minor == ["Am", "Bdim", "C", "Dm", "Em", "F", "G"]
    with pytest.raises(TheoryError):
        diatonic_chords(make_scale("C", "major_pentatonic"))


def test_inversions_and_voicing() -> None:
    c = make_chord("C", "major")
    assert c.inversion() == 0 and c.with_inversion(1).inversion() == 1
    assert [str(n) for n in c.with_inversion(1).notes()] == ["E4", "G4", "C5"]
    assert c.with_inversion(2).midi_notes() == [67, 72, 76]
    assert make_chord("C", "major7").midi_notes() == [60, 64, 67, 71]
    assert make_chord("C", "dominant9").midi_notes() == [60, 64, 67, 70, 74]
    assert make_chord("C", "diminished7").midi_notes() == [60, 63, 66, 69]
    assert [inversion_name(i) for i in range(5)][1:3] == ["first inversion", "second inversion"]
    with pytest.raises(TheoryError):
        c.with_inversion(3)


def test_slash_chords() -> None:
    dm7_c = make_chord("D", "minor7", "C")
    assert dm7_c.inversion() == 3 and str(dm7_c) == "Dm7/C"
    c_d = make_chord("C", "major", "D")  # bass is not a chord tone
    assert c_d.inversion() is None
    assert [str(n) for n in c_d.notes()] == ["D3", "C4", "E4", "G4"]
    assert make_chord("C", "major", "E").inversion() == 1


def test_transposition_preserves_quality_and_bass_relationship() -> None:
    dm7_c = make_chord("D", "minor7", "C")
    up = dm7_c.transposed(parse_interval("M2"))
    assert str(up) == "Em7/D"
    assert str(up.transposed(parse_interval("M2"), down=True)) == "Dm7/C"
    assert str(make_chord("Bb", "major7").transposed(parse_interval("M3"))) == "Dmaj7"


@given(st.sampled_from(sorted(CHORD_TYPES)), st.sampled_from(ROOTS), st.integers(0, 11))
def test_transposing_by_semitones_moves_every_pitch_class(
    type_id: str, root: str, semis: int
) -> None:
    chord = make_chord(root, type_id)
    iv = parse_interval(
        ["P1", "m2", "M2", "m3", "M3", "P4", "A4", "P5", "m6", "M6", "m7", "M7"][semis]
    )
    try:
        moved = chord.transposed(iv)
        moved_pcs = [t.pitch_class for t in moved.tones()]
    except TheoryError as exc:  # e.g. Db half-diminished up a semitone needs triple accidentals
        assert exc.code == "spelling_overflow"
        return
    assert moved_pcs == [(p + semis) % 12 for p in chord.pitch_classes()]


def test_chord_equality_distinguishes_spelling() -> None:
    assert Chord is type(make_chord("C#", "major"))
    assert make_chord("C#", "major") != make_chord("Db", "major")
    assert make_chord("C#", "major").pitch_classes() == make_chord("Db", "major").pitch_classes()


def test_unknown_chord_type() -> None:
    with pytest.raises(TheoryError) as err:
        make_chord("C", "nonsense")
    assert err.value.code == "unknown_chord_type"
