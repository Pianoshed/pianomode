import time

import pytest

from music_theory import validation as v
from music_theory.errors import TheoryError
from music_theory.midi_analysis import MidiEvent, TempoMap, analyze_notes, notes_from_events
from music_theory.notes import Note, NoteName


def test_count_limits_have_stable_codes() -> None:
    v.check_count("notes", 3, 5)
    with pytest.raises(TheoryError) as err:
        v.check_count("notes", 6, 5)
    assert err.value.code == "too_many_items" and "at most 5" in err.value.message
    with pytest.raises(TheoryError) as err:
        v.check_count("notes", 0, 5)
    assert err.value.code == "too_few_items"
    v.check_count("notes", 0, 5, minimum=0)


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), True, "1", None])
def test_check_finite_rejects_non_numbers(bad: object) -> None:
    with pytest.raises(TheoryError) as err:
        v.check_finite("tempo", bad)  # type: ignore[arg-type]
    assert err.value.code == "invalid_number"


def test_parse_key_and_notes() -> None:
    assert str(v.parse_key("Eb", "minor")) == "Eb minor"
    for bad in ("", "  ", "H"):
        with pytest.raises(TheoryError):
            v.parse_key(bad)
    with pytest.raises(TheoryError):
        v.parse_key("C", "dorian")
    assert isinstance(v.parse_note_or_name("C#4"), Note)
    assert isinstance(v.parse_note_or_name("Db"), NoteName)
    assert v.parse_note_or_name("C3", middle_c_octave=3).midi == 60  # type: ignore[union-attr]


def test_midi_range_check() -> None:
    assert v.check_midi_range([0, 60, 127]) == [0, 60, 127]
    for bad in ([128], [-1], [True], ["60"]):
        with pytest.raises(TheoryError) as err:
            v.check_midi_range(bad)  # type: ignore[arg-type]
        assert err.value.code == "invalid_midi_note"


def _events(spec: list[tuple[int, int, int]]) -> list[MidiEvent]:
    out = []
    for note, start, end in spec:
        out += [
            MidiEvent(start, "note_on", note, 80, 0, 0),
            MidiEvent(end, "note_off", note, 0, 0, 0),
        ]
    return out


def test_a_sustained_note_is_counted_in_every_cell_it_spans() -> None:
    # A low C is held for 16 beats while the harmony above it changes every 4 beats.
    spec = [(36, 0, 480 * 16)]
    spec += [(n, 0, 480 * 4) for n in (64, 67)]  # C/E G over the held C: C major
    spec += [(n, 480 * 4, 480 * 8) for n in (65, 69)]  # F A over C: F/C
    spec += [(n, 480 * 8, 480 * 12) for n in (67, 71, 74)]  # G B D over C: G/C
    spec += [(n, 480 * 12, 480 * 16) for n in (64, 67)]
    notes = notes_from_events(_events(spec), TempoMap(480, [])).notes
    result = analyze_notes(notes, grid="bar", ppq=480)
    assert len(result.segments) == 4
    for seg in result.segments:
        assert 36 in seg.pitches, "the held note was dropped from a later cell"
    assert [s.best.symbol for s in result.segments if s.best][0] == "C"


def test_long_files_scale_roughly_linearly() -> None:
    spec = []
    for beat in range(0, 4000):
        base = 480 * beat
        spec += [
            (60 + (beat % 3) * 2, base, base + 480),
            (64, base, base + 480),
            (67, base, base + 480),
        ]
    notes = notes_from_events(_events(spec), TempoMap(480, [])).notes
    start = time.perf_counter()
    result = analyze_notes(notes, grid="beat", ppq=480)
    elapsed = time.perf_counter() - start
    assert result.note_count == 12000
    assert elapsed < 20, f"12,000 notes took {elapsed:.1f}s; the per-cell scan may be back"
