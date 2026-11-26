import pytest

from music_theory.chords import CHORD_TYPES, make_chord
from music_theory.errors import TheoryError
from music_theory.identify import altered_tones, identify_chord
from music_theory.keys import Key
from music_theory.notes import parse_note_name as n


def top(notes, **kw):  # type: ignore[no-untyped-def]
    result = identify_chord(notes, **kw)
    assert result.best is not None, result.reason
    return result.best


@pytest.mark.parametrize(
    ("midi", "symbol", "inversion"),
    [
        ([60, 64, 67], "C", 0), ([64, 67, 72], "C/E", 1), ([67, 72, 76], "C/G", 2),
        ([60, 64, 67, 71], "Cmaj7", 0), ([60, 64, 67, 70], "C7", 0), ([60, 63, 67, 70], "Cm7", 0),
        ([60, 63, 66, 70], "Cm7b5", 0), ([60, 63, 66, 69], "Cdim7", 0), ([62, 65, 69, 72], "Dm7", 0),
        ([55, 59, 62, 65], "G7", 0), ([59, 62, 65, 67], "G7/B", 1), ([53, 55, 59, 62], "G7/F", 3),
        ([60, 62, 67], "Csus2", 0), ([60, 65, 67], "Csus4", 0), ([60, 67], "C5", 0),
        ([57, 60, 64], "Am", 0), ([60, 64, 68], "Caug", 0), ([60, 64, 67, 70, 74], "C9", 0),
    ],
)  # fmt: skip
def test_known_chords_and_inversions(midi: list[int], symbol: str, inversion: int) -> None:
    best = top(midi)
    assert best.symbol == symbol and best.inversion == inversion


def test_root_not_in_bass_is_recognised() -> None:
    assert top([52, 60, 67]).symbol == "C/E"  # E3 C4 G4: root above the bass


def test_half_diminished_is_not_confused_with_related_chords() -> None:
    result = identify_chord([60, 63, 66, 70], max_candidates=10)
    assert result.best and result.best.chord.type.id == "half_diminished7"
    symbols = [c.symbol for c in result.candidates]
    assert "Ebm6/C" in symbols  # spelled with the fewest accidentals, not D#m6/B#
    assert "Cdim7" not in symbols and "Cm" not in symbols


def test_ambiguity_is_reported_not_hidden() -> None:
    # E G A C with E in the bass is Am7/E or C6/E: both fit, so the status must say so.
    result = identify_chord(["E", "G", "A", "C"])
    assert result.status == "ambiguous"
    assert {c.symbol for c in result.candidates[:2]} == {"Am7/E", "C6/E"}
    # With C in the bass the C6 reading clearly wins, but the alternative is still listed.
    r2 = identify_chord([48, 52, 55, 57])
    assert r2.best and r2.best.symbol == "C6"
    assert "Am7/C" in [c.symbol for c in r2.candidates]


@pytest.mark.parametrize(
    ("notes", "fragment"),
    [([60], "single pitch"), ([60, 64], "major third"), ([60, 61, 62], "No supported chord type"),
     ([60, 62, 64, 66, 68, 70], "No supported chord type")],  # last: a whole-tone cluster
)  # fmt: skip
def test_no_reliable_label_is_stated_clearly(notes: list[int], fragment: str) -> None:
    result = identify_chord(notes)
    assert result.status == "no_reliable_label" and not result.candidates
    assert result.reason is not None and fragment.lower() in result.reason.lower()


def test_slash_chord_with_non_chord_bass() -> None:
    result = identify_chord([50, 60, 64, 67], max_candidates=10)
    by_symbol = {c.symbol: c for c in result.candidates}
    assert result.best and result.best.symbol == "Cadd9/D"
    assert by_symbol["C/D"].inversion is None
    assert "slash chord" in by_symbol["C/D"].assumptions[0]


def test_rootless_voicings_only_when_asked() -> None:
    plain = identify_chord([65, 69, 72, 76], max_candidates=20)  # F A C E
    assert plain.best and plain.best.symbol == "Fmaj7"
    assert not any(c.rootless for c in plain.candidates)
    rootless = identify_chord([65, 69, 72, 76], allow_rootless=True, max_candidates=20)
    dm9 = next(c for c in rootless.candidates if c.chord.type.id == "minor9")
    assert dm9.rootless and str(dm9.chord.root) == "D"
    assert "rootless" in dm9.assumptions[0].lower()
    assert rootless.best and rootless.best.symbol == "Fmaj7"  # a rooted reading outranks it
    g9 = identify_chord(["B", "D", "F", "A"], allow_rootless=True, max_candidates=20)
    assert any(c.rootless and c.symbol.startswith("G9") for c in g9.candidates)


def test_extra_tones_are_never_forced_in() -> None:
    notes = [60, 64, 67, 71, 78]  # Cmaj7 plus F#
    strict = identify_chord(notes, max_candidates=20)
    assert "Cmaj7" not in [c.symbol for c in strict.candidates]
    loose = identify_chord(notes, max_extra_tones=1, max_candidates=20)
    cmaj7 = next(c for c in loose.candidates if c.symbol == "Cmaj7")
    assert [str(t) for t in cmaj7.extra_tones] == ["F#"]
    assert cmaj7.score < 6.0  # penalised relative to a clean match


def test_spelling_follows_input_then_simplest_then_preference() -> None:
    assert top(["Bb", "D", "F"]).symbol == "Bb"
    sharp = top(["A#", "C##", "E#"])  # the caller's own spelling is respected
    assert sharp.symbol == "A#" and sharp.enharmonic_symbol == "Bb"
    assert top([58, 62, 65]).symbol == "Bb"  # MIDI input: fewest accidentals wins (not A#)
    assert top([61, 65, 68]).symbol == "Db"
    assert top([66, 70, 73]).symbol == "F#"  # F# and Gb major tie: preference decides
    assert top([66, 70, 73], prefer="flats").symbol == "Gb"
    assert top([66, 70, 73], key=Key(n("Db"))).symbol == "Gb"  # key spelling decides ties too
    assert top([66, 70, 73], key=Key(n("E"))).symbol == "F#"


def test_candidate_details() -> None:
    best = top([60, 64, 67, 70, 74])  # C9 with a complete voicing
    assert [str(t) for t in best.detected_tones] == ["C", "E", "G", "Bb", "D"]
    assert not best.missing_tones
    no_fifth = top([60, 64, 70, 74])  # C9 without the fifth
    assert [str(t) for t in no_fifth.missing_tones] == ["G"] and "omitted" in no_fifth.assumptions[
        0
    ]
    add9 = top([60, 64, 67, 74])
    assert add9.symbol == "Cadd9" and add9.added_tones == ("M9",)
    c7b9 = top([60, 64, 67, 70, 61])
    assert c7b9.symbol == "C7b9" and c7b9.altered_tones == ("m9",)
    assert top([60, 64, 67, 70, 66]).altered_tones == ("A11",)


def test_altered_tone_detection() -> None:
    assert [i.short for i in altered_tones(CHORD_TYPES["dominant7_flat9"])] == ["m9"]
    assert [i.short for i in altered_tones(CHORD_TYPES["dominant7_sharp11"])] == ["A11"]
    assert [i.short for i in altered_tones(CHORD_TYPES["altered"])] == ["d5", "m9", "A9", "m13"]
    assert altered_tones(CHORD_TYPES["diminished7"]) == ()  # a diminished fifth is intrinsic
    assert altered_tones(CHORD_TYPES["dominant9"]) == ()


def test_results_are_deterministic() -> None:
    a = identify_chord([60, 63, 66, 69], allow_rootless=True, max_candidates=10)
    b = identify_chord([60, 63, 66, 69], allow_rootless=True, max_candidates=10)
    assert a == b


@pytest.mark.parametrize(
    "bad",
    [[], [128], [-1], [True], [60, "C"], ["H", "E"]],
)
def test_invalid_input(bad: list[object]) -> None:
    with pytest.raises(TheoryError):
        identify_chord(bad)  # type: ignore[arg-type]


def test_bass_must_be_among_the_notes() -> None:
    with pytest.raises(TheoryError):
        identify_chord(["C", "E", "G"], bass="D")
    assert top(["C", "E", "G"], bass="E").inversion == 1


@pytest.mark.parametrize("root", ["C", "Eb", "F#", "A"])
@pytest.mark.parametrize("type_id", list(CHORD_TYPES))
def test_every_constructed_chord_is_found_in_every_inversion(root: str, type_id: str) -> None:
    chord = make_chord(root, type_id)
    for inv in range(min(chord.type.size, 4)):
        midi = chord.midi_notes(4, inv)
        result = identify_chord(midi, max_candidates=200, ambiguity_margin=0)
        hit = [
            c for c in result.candidates
            if c.chord.root.pitch_class == chord.root.pitch_class and c.chord.type.id == type_id
        ]  # fmt: skip
        assert hit, f"{chord} inversion {inv} not found"
        assert hit[0].inversion == inv
