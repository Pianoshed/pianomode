import pytest

from music_theory.chord_symbols import parse_chord
from music_theory.errors import TheoryError
from music_theory.keys import Key
from music_theory.phrases import segment_phrases
from music_theory.roman import analyze_progression, find_cadences


def phrases(symbols: list[str], **kw):  # type: ignore[no-untyped-def]
    chords = [parse_chord(s) for s in symbols]
    nums = analyze_progression(chords, Key(chords[0].root, "major"))
    return segment_phrases(nums, find_cadences(nums), **kw)


def test_two_authentic_phrases() -> None:
    ps = phrases(["C", "F", "G7", "C", "Am", "Dm7", "G7", "C"])
    assert [(p.start, p.end) for p in ps] == [(0, 3), (4, 7)]
    assert all(p.cadence == "authentic" and p.character == "closed" for p in ps)
    assert ps[0].function_path == ("tonic", "predominant", "dominant", "tonic")


def test_half_cadence_ending_is_open() -> None:
    (p,) = phrases(["C", "Am", "F", "G"])
    assert p.cadence == "half" and p.character == "open"
    assert "half cadence" in p.text


def test_deceptive_is_interrupted() -> None:
    (p,) = phrases(["C", "F", "G7", "Am"])
    assert p.cadence == "deceptive" and p.character == "interrupted"


def test_no_cadence() -> None:
    (p,) = phrases(["C", "Am", "Dm", "F"][:3])
    assert p.cadence is None and p.character == "no cadence"


def test_short_leftover_is_marked() -> None:
    ps = phrases(["C", "F", "C", "G"])
    assert ps[0].cadence == "plagal"
    assert ps[-1].short and ps[-1].cadence is None


def test_min_chords_controls_boundaries() -> None:
    seq = ["C", "G7", "C", "F", "G7", "C"]
    assert len(phrases(seq, min_chords=2)) > len(phrases(seq, min_chords=5))


def test_durations_are_summed() -> None:
    (p,) = phrases(["C", "F", "G7", "C"], durations=[4, 4, 2, 2])
    assert p.duration_beats == 12


def test_phrases_cover_every_chord_exactly_once() -> None:
    seq = ["C", "F", "G7", "C", "F", "C", "Dm", "G", "Am", "F", "G7", "C"]
    ps = phrases(seq)
    covered = [i for p in ps for i in range(p.start, p.end + 1)]
    assert covered == list(range(len(seq)))


def test_bad_inputs() -> None:
    chords = [parse_chord("C")]
    nums = analyze_progression(chords, Key(chords[0].root, "major"))
    with pytest.raises(TheoryError):
        segment_phrases(nums, [], durations=[1, 2])
    with pytest.raises(TheoryError):
        segment_phrases(nums, [], min_chords=0)
    assert segment_phrases([], []) == []
