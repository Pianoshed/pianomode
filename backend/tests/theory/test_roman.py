import pytest

from music_theory.chord_symbols import parse_chord as P
from music_theory.chords import make_chord
from music_theory.errors import TheoryError
from music_theory.harmony import diatonic_chords
from music_theory.key_analysis import MAJOR_TONICS, MINOR_TONICS
from music_theory.keys import Key
from music_theory.notes import parse_note_name as N
from music_theory.roman import (
    _SEVENTH_IDS,
    _TRIAD_IDS,
    analyze_chord,
    analyze_progression,
    chord_from_roman,
    find_cadences,
)
from music_theory.scales import make_scale

C = Key(N("C"))
A_MINOR = Key(N("A"), "minor")


def fig(symbol: str, key: Key = C) -> str:
    return analyze_chord(P(symbol), key).figure


def test_diatonic_triads_and_sevenths_in_c() -> None:
    assert [fig(s) for s in "C Dm Em F G Am Bdim".split()] == [
        "I",
        "ii",
        "iii",
        "IV",
        "V",
        "vi",
        "vii°",
    ]
    sevenths = "Cmaj7 Dm7 Em7 Fmaj7 G7 Am7 Bm7b5".split()
    assert [fig(s) for s in sevenths] == ["Imaj7", "ii7", "iii7", "IVmaj7", "V7", "vi7", "viiø7"]
    assert analyze_chord(P("G7"), C).function == "dominant"
    assert analyze_chord(P("Dm7"), C).function == "predominant"


def test_minor_key_including_harmonic_minor() -> None:
    plain = "Am Bdim C Dm Em F G".split()
    assert [fig(s, A_MINOR) for s in plain] == ["i", "ii°", "III", "iv", "v", "VI", "VII"]
    assert [fig(s, A_MINOR) for s in ["E", "E7", "G#dim", "G#dim7"]] == ["V", "V7", "vii°", "vii°7"]
    assert fig("AmMaj7", A_MINOR) == "i(maj7)"


def test_inversion_figures() -> None:
    assert [fig(s) for s in ["C/E", "C/G", "G/B"]] == ["I6", "I6/4", "V6"]
    assert [fig(s) for s in ["G7/B", "G7/D", "G7/F"]] == ["V6/5", "V4/3", "V4/2"]
    assert fig("Dm7/C") == "ii4/2" and fig("Cmaj7/E") == "Imaj6/5" and fig("Bdim/D") == "vii°6"


def test_secondary_dominants_and_leading_tone_chords() -> None:
    expected = {
        "D7": "V7/V", "A7": "V7/ii", "E7": "V7/vi", "C7": "V7/IV", "B7": "V7/iii", "D": "V/V",
        "F#dim7": "vii°7/V", "C#dim7": "vii°7/ii", "F#m7b5": "viiø7/V", "G#dim": "vii°/vi",
    }  # fmt: skip
    for symbol, figure in expected.items():
        n = analyze_chord(P(symbol), C)
        assert n.figure == figure, symbol
        assert n.category in {"secondary_dominant", "secondary_leading_tone"}
    assert analyze_chord(P("D7"), C).applied_to == "V"
    assert fig("D7/F#") == "V6/5/V"


def test_secondary_chords_in_minor() -> None:
    assert fig("B7", A_MINOR) == "V7/V"  # B D# F# A resolves to E
    assert fig("A7", A_MINOR) == "V7/iv"


def test_borrowed_chords() -> None:
    for symbol, figure in {
        "Fm": "iv",
        "Ab": "bVI",
        "Bb": "bVII",
        "Eb": "bIII",
        "Dm7b5": "iiø7",
        "Bdim7": "vii°7",
    }.items():
        n = analyze_chord(P(symbol), C)
        assert (n.figure, n.category, n.borrowed_from) == (figure, "borrowed", "parallel minor")
    mixture = analyze_chord(P("Dmaj7"), A_MINOR)  # IVmaj7: cannot be an applied dominant
    assert (mixture.figure, mixture.category, mixture.borrowed_from) == (
        "IVmaj7",
        "borrowed",
        "parallel major",
    )


def test_ambiguous_chords_report_their_other_reading() -> None:
    d = analyze_chord(P("D"), A_MINOR)  # V/VII, or IV borrowed from A major
    assert d.figure == "V/VII" and d.category == "secondary_dominant"
    assert d.alternatives == ("IV (borrowed from parallel major)",)
    assert analyze_chord(P("D7"), C).alternatives == ()  # only one sensible reading


def test_chromatic_chords_are_labelled_not_forced() -> None:
    n = analyze_chord(P("Db"), C)
    assert (n.figure, n.category, n.note) == ("bII", "chromatic", "Neapolitan chord")
    assert analyze_chord(P("Db/F"), C).note == "Neapolitan chord (Neapolitan sixth)"
    assert fig("Db/F") == "bII6"
    assert analyze_chord(P("F#"), C).category == "chromatic" and fig("F#") == "#IV"


@pytest.mark.parametrize("tonic", MAJOR_TONICS)
@pytest.mark.parametrize(("scale_id", "mode"), [("major", "major")])
def test_major_key_round_trip_with_all_inversions(tonic: str, scale_id: str, mode: str) -> None:
    key = Key(N(tonic), "major")
    for size in (3, 4):
        for d in diatonic_chords(make_scale(key.tonic, scale_id), size):  # type: ignore[arg-type]
            assert d.chord is not None
            for inv in range(size):
                chord = d.chord.with_inversion(inv)
                numeral = analyze_chord(chord, key)
                assert numeral.category == "diatonic", (chord, key)
                assert chord_from_roman(numeral.figure, key) == chord, (numeral.figure, key)


@pytest.mark.parametrize("tonic", MINOR_TONICS)
@pytest.mark.parametrize("scale_id", ["natural_minor", "harmonic_minor"])
def test_minor_key_round_trip(tonic: str, scale_id: str) -> None:
    key = Key(N(tonic), "minor")
    for size in (3, 4):
        for d in diatonic_chords(make_scale(key.tonic, scale_id), size):  # type: ignore[arg-type]
            assert d.chord is not None
            supported = d.chord.type.id in (*_TRIAD_IDS, *_SEVENTH_IDS)
            for inv in range(size if supported else 1):
                chord = d.chord.with_inversion(inv)
                numeral = analyze_chord(chord, key)
                assert numeral.category == "diatonic", (chord, key)
                assert chord_from_roman(numeral.figure, key) == chord, (numeral.figure, key)


def test_parsing_builds_the_right_chords() -> None:
    cases = {
        "I": "C", "V7": "G7", "ii7": "Dm7", "bVI": "Ab", "bVII": "Bb", "iv": "Fm", "viiø7": "Bm7b5",
        "vii°7": "Bdim7", "V7/V": "D7", "vii°7/V": "F#dim7", "V/ii": "A", "V6/5": "G7/B",
        "I6/4": "C/G", "Imaj7": "Cmaj7", "IVadd9": "Fadd9", "Isus4": "Csus4", "bII6": "Db/F",
        "III+": "E" + "aug", "V7b9": "G7b9", "V/V/V": "A", "ii7/V": "Am7", "Iadd6": "C6",
        "viio7": "Bdim7",
    }  # fmt: skip
    for text, symbol in cases.items():
        assert str(chord_from_roman(text, C)) == symbol, text
    assert str(chord_from_roman("V7", A_MINOR)) == "E7"
    assert str(chord_from_roman("vii°", A_MINOR)) == "G#dim"
    assert str(chord_from_roman("VII", A_MINOR)) == "G"
    assert str(chord_from_roman("V7/III", A_MINOR)) == "G7"


@pytest.mark.parametrize(
    "bad",
    ["", "X", "VIII", "Vfoo", "V7/", "V//V", "bbbV", "b#V", "V9sus", "ii°°", "viø5", "Ix7"],
)
def test_invalid_numerals_are_rejected(bad: str) -> None:
    with pytest.raises(TheoryError):
        chord_from_roman(bad, C)


def test_every_chord_type_has_a_parseable_figure() -> None:
    from music_theory.chords import CHORD_TYPES

    for type_id in CHORD_TYPES:
        chord = make_chord("G", type_id)  # on the dominant, root position
        numeral = analyze_chord(chord, C)
        rebuilt = chord_from_roman(numeral.figure, C)
        assert rebuilt.type.id == type_id, (type_id, numeral.figure)


def test_cadences() -> None:
    def kinds(symbols: str, key: Key = C) -> list[tuple[int, int, str]]:
        nums = analyze_progression([P(s) for s in symbols.split()], key)
        return [(c.start, c.end, c.kind) for c in find_cadences(nums)]

    assert kinds("C F G7 C") == [(2, 3, "authentic")]
    assert kinds("C G Am") == [(1, 2, "deceptive")]
    assert kinds("C F C") == [(1, 2, "plagal")]
    assert kinds("C Dm G") == [(1, 2, "half")]
    assert kinds("Am Dm/F E", A_MINOR) == [(1, 2, "phrygian half"), (1, 2, "half")]
    assert kinds("C G/B C") == [(1, 2, "authentic")]
    assert kinds("C Dm Em") == []
    nums = analyze_progression([P("G7"), P("C")], C)
    assert "perfect authentic" in find_cadences(nums)[0].note
    nums = analyze_progression([P("G7/B"), P("C")], C)
    assert "inverted" in find_cadences(nums)[0].note
