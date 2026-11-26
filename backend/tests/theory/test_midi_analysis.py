import math

import pytest
from hypothesis import given
from hypothesis import strategies as st

from music_theory.errors import TheoryError
from music_theory.keys import Key
from music_theory.midi_analysis import (
    HandAssignment,
    MidiDataError,
    MidiEvent,
    NoteEvent,
    TempoChange,
    TempoMap,
    TimeSignatureChange,
    TrackState,
    active_notes_at,
    analyze_midi_events,
    analyze_notes,
    assign_hands,
    audible_tracks,
    chord_at,
    filter_audible,
    merge_tracks,
    note_at,
    notes_from_events,
    split_track_by_pitch,
)
from music_theory.notes import parse_note_name as N

C = Key(N("C"))


def chord_notes(blocks: list[tuple[float, float, list[int]]]) -> list[NoteEvent]:
    notes, i = [], 0
    for start, end, midis in blocks:
        for m in midis:
            notes.append(note_at(i, m, start, end))
            i += 1
    return notes


def symbols(a) -> list[str]:  # type: ignore[no-untyped-def]
    return [s.best.symbol if s.best else s.status for s in a.segments]


# ------------------------------------------------------------ timing and note extraction


def test_tempo_map_converts_ticks_through_tempo_changes() -> None:
    tm = TempoMap(480)
    assert tm.beats(960) == 2.0 and tm.seconds(480) == pytest.approx(0.5)
    changed = TempoMap(480, [TempoChange(960, 60)])
    assert changed.seconds(960) == pytest.approx(1.0)
    assert changed.seconds(1440) == pytest.approx(2.0)  # one more beat at 60 BPM
    fast = TempoMap(96, [TempoChange(0, 240)])
    assert fast.seconds(96) == pytest.approx(0.25)


@pytest.mark.parametrize("bad", [0, -4, 1.5, True])
def test_tempo_map_rejects_bad_ppq(bad) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(MidiDataError):
        TempoMap(bad)


@pytest.mark.parametrize(
    "tempo",
    [TempoChange(0, 0), TempoChange(0, math.nan), TempoChange(-1, 100), TempoChange(0, 5000)],
)
def test_tempo_map_rejects_bad_tempi(tempo: TempoChange) -> None:
    with pytest.raises(MidiDataError):
        TempoMap(480, [tempo])


def on(tick: int, note: int, vel: int = 80, **kw) -> MidiEvent:  # type: ignore[no-untyped-def]
    return MidiEvent(tick, "note_on", note, vel, **kw)


def off(tick: int, note: int, **kw) -> MidiEvent:  # type: ignore[no-untyped-def]
    return MidiEvent(tick, "note_off", note, 0, **kw)


def test_note_pairing_velocity_and_duration() -> None:
    result = notes_from_events(
        [on(0, 60, 100), off(480, 60), on(480, 64, 40), off(960, 64)], TempoMap(480)
    )
    a, b = result.notes
    assert (a.midi, a.velocity, a.start_beat, a.end_beat, a.start_sec, a.end_sec) == (
        60,
        100,
        0.0,
        1.0,
        0.0,
        0.5,
    )
    assert (b.midi, b.velocity, b.duration_beats) == (64, 40, 1.0)
    assert [n.id for n in result.notes] == [0, 1] and not result.warnings


def test_note_on_with_zero_velocity_is_a_note_off_and_repeats_pair_in_order() -> None:
    events = [on(0, 60), on(240, 60), on(480, 60, 0), on(960, 60, 0)]
    notes = notes_from_events(events, TempoMap(480)).notes
    assert [(n.start_beat, n.end_beat) for n in notes] == [(0.0, 1.0), (0.5, 2.0)]


def test_a_note_off_and_on_at_the_same_tick_do_not_swallow_each_other() -> None:
    notes = notes_from_events(
        [on(0, 60), off(480, 60), on(480, 60), off(960, 60)], TempoMap(480)
    ).notes
    assert [(n.start_beat, n.end_beat) for n in notes] == [(0.0, 1.0), (1.0, 2.0)]


def test_tracks_and_channels_do_not_pair_with_each_other() -> None:
    ev = [on(0, 60, track=0), on(0, 60, track=1), off(480, 60, track=1), off(960, 60, track=0)]
    notes = notes_from_events(ev, TempoMap(480)).notes
    assert sorted((n.track, n.end_beat) for n in notes) == [(0, 2.0), (1, 1.0)]


def test_messy_files_produce_warnings_not_crashes() -> None:
    result = notes_from_events([on(0, 60), off(100, 61), on(200, 62), off(200, 62)], TempoMap(480))
    text = " ".join(result.warnings)
    assert "never released" in text and "no matching note-on" in text and "Zero-length" in text
    assert [n.midi for n in result.notes] == [60] and result.notes[0].end_beat == pytest.approx(
        200 / 480
    )
    closed = notes_from_events([on(0, 60)], TempoMap(480), end_tick=960).notes[0]
    assert closed.end_beat == 2.0


@pytest.mark.parametrize(
    "event",
    [MidiEvent(0, "note_on", 128), MidiEvent(0, "note_on", 60, 200), MidiEvent(-1, "note_on", 60),
     MidiEvent(0, "program_change", 60)],  # type: ignore[arg-type]
)  # fmt: skip
def test_invalid_events_are_rejected(event: MidiEvent) -> None:
    with pytest.raises(MidiDataError):
        notes_from_events([event], TempoMap(480))


# ------------------------------------------------------------ chord segmentation


def test_block_chords_become_segments_with_numerals() -> None:
    notes = chord_notes([
        (0, 4, [48, 60, 64, 67]), (4, 8, [45, 57, 60, 64]), (8, 12, [41, 60, 65, 69]), (12, 16, [43, 59, 62, 67]),
    ])  # fmt: skip
    a = analyze_notes(notes, grid="bar", key=C)
    assert symbols(a) == ["C", "Am", "F", "G"]
    assert [s.numeral.figure for s in a.segments if s.numeral] == ["I", "vi", "IV", "V"]
    assert a.key_source == "provided" and a.note_count == 16 and a.duration_beats == 16
    assert all(s.origin == "midi" for s in a.segments)
    assert [(s.start_beat, s.end_beat, s.start_sec, s.end_sec) for s in a.segments][1] == (
        4,
        8,
        2.0,
        4.0,
    )


def test_the_key_is_estimated_when_not_given_and_flagged_when_uncertain() -> None:
    notes = chord_notes(
        [
            (0, 4, [48, 60, 64, 67]),
            (4, 8, [45, 57, 60, 64]),
            (8, 12, [41, 60, 65, 69]),
            (12, 16, [43, 59, 62, 67]),
        ]
    )
    a = analyze_notes(notes, grid="bar")
    assert a.key is not None and a.key_source == "estimated"
    assert str(a.key.tonic) in {"C", "A"}  # relative keys are the honest ambiguity
    assert a.key_estimate.candidates
    if a.key_estimate.ambiguous:
        assert any("uncertain" in w for w in a.warnings)


def test_too_little_evidence_means_no_key_and_no_numerals() -> None:
    a = analyze_notes(chord_notes([(0, 4, [60, 64])]), grid="bar")
    assert a.key is None and a.key_source is None
    assert all(s.numeral is None for s in a.segments)
    assert any("Not enough harmonic evidence" in w for w in a.warnings)


def test_inversions_and_the_bass_note() -> None:
    a = analyze_notes(chord_notes([(0, 4, [47, 55, 62, 65])]), grid="bar", key=C)
    seg = a.segments[0]
    assert seg.best is not None and seg.best.symbol == "G7/B" and str(seg.bass) == "B"
    assert seg.numeral is not None and seg.numeral.figure == "V6/5"


def test_arpeggios_are_read_as_the_chord_and_passing_tones_are_ignored() -> None:
    arpeggio = [note_at(0, 60, 0, 1), note_at(1, 64, 1, 2), note_at(2, 67, 2, 3)]
    assert symbols(analyze_notes(arpeggio, grid="bar", key=C)) == ["C"]
    with_passing = chord_notes([(0, 4, [48, 60, 64, 67])]) + [note_at(10, 62, 1.5, 2.0)]
    a = analyze_notes(with_passing, grid="bar", key=C)
    assert symbols(a) == ["C"]  # the D lasts an eighth of a bar: not a chord tone
    assert 62 not in a.segments[0].pitches


def test_adjacent_cells_with_the_same_chord_are_merged() -> None:
    a = analyze_notes(
        chord_notes([(0, 4, [48, 60, 64, 67]), (4, 8, [43, 59, 62, 67])]), grid="beat", key=C
    )
    assert symbols(a) == ["C", "G"]
    assert [s.cells for s in a.segments] == [4, 4]
    assert [(s.start_beat, s.end_beat) for s in a.segments] == [(0, 4), (4, 8)]


def test_harmonic_rhythm_faster_than_the_grid_needs_a_finer_grid() -> None:
    notes = chord_notes([(0, 2, [48, 60, 64, 67]), (2, 4, [43, 59, 62, 67])])
    assert symbols(analyze_notes(notes, grid="half_bar", key=C)) == ["C", "G"]
    assert len(analyze_notes(notes, grid="bar", key=C).segments) == 1  # one bar, one reading


def test_silence_and_unnameable_sonorities_are_reported_honestly() -> None:
    notes = chord_notes([(0, 1, [60, 64]), (2, 3, [60, 61, 62])])
    a = analyze_notes(notes, grid="beat", key=C)
    assert [s.status for s in a.segments] == ["no_reliable_label", "silence", "no_reliable_label"]
    assert a.segments[0].reason and a.segments[0].candidates == ()
    assert a.segments[0].numeral is None
    stray = chord_notes([(0, 4, [48, 60, 64, 67])]) + [note_at(9, 60, 7.5, 8)]
    last = analyze_notes(stray, grid="bar", key=C).segments[1]  # only an eighth-note blip in bar 2
    assert last.status == "no_reliable_label" and "short" in last.warnings[0]


def test_empty_input() -> None:
    a = analyze_notes([])
    assert a.segments == () and a.warnings == ("No notes to analyse.",)


def test_invalid_parameters() -> None:
    with pytest.raises(TheoryError):
        analyze_notes(chord_notes([(0, 4, [60, 64, 67])]), grid="fortnight")  # type: ignore[arg-type]
    with pytest.raises(TheoryError):
        analyze_notes(chord_notes([(0, 4, [60, 64, 67])]), min_note_fraction=2)
    with pytest.raises(MidiDataError):
        analyze_notes(chord_notes([(0, 4, [60])]), time_signatures=[TimeSignatureChange(0, 4, 3)])


def test_time_signatures_set_the_bars() -> None:
    notes = chord_notes([(0, 3, [48, 60, 64, 67]), (3, 6, [43, 59, 62, 67])])
    waltz = analyze_notes(notes, grid="bar", key=C, time_signatures=[TimeSignatureChange(0, 3, 4)])
    assert [(s.start_beat, s.end_beat) for s in waltz.segments] == [(0, 3), (3, 6)]
    compound = analyze_notes(
        chord_notes([(0, 1.5, [48, 60, 64, 67]), (1.5, 3, [43, 59, 62, 67])]),
        grid="beat", key=C, time_signatures=[TimeSignatureChange(0, 6, 8)],
    )  # fmt: skip
    assert [(s.start_beat, s.end_beat) for s in compound.segments] == [
        (0, 1.5),
        (1.5, 3),
    ]  # dotted-quarter beats
    mixed = chord_notes(
        [(0, 4, [48, 60, 64, 67]), (4, 7, [43, 59, 62, 67]), (7, 10, [48, 60, 64, 67])]
    )
    a = analyze_notes(
        mixed, grid="bar", key=C, time_signatures=[TimeSignatureChange(4 * 480, 3, 4)], ppq=480
    )
    assert [(s.start_beat, s.end_beat) for s in a.segments] == [(0, 4), (4, 7), (7, 10)]


def test_a_piece_that_ends_mid_bar_is_not_padded_with_silence() -> None:
    a = analyze_notes(chord_notes([(0, 3, [48, 60, 64, 67])]), grid="bar", key=C)
    assert [(s.status, s.end_beat) for s in a.segments] == [("identified", 3)]


def test_events_to_analysis_with_tempo_changes() -> None:
    events = [on(0, m) for m in (48, 60, 64, 67)] + [off(1920, m) for m in (48, 60, 64, 67)]
    events += [on(1920, m) for m in (43, 59, 62, 67)] + [off(3840, m) for m in (43, 59, 62, 67)]
    a, warnings = analyze_midi_events(
        events, ppq=480, tempo_changes=[TempoChange(1920, 60)], key=C, grid="bar"
    )
    assert not warnings and symbols(a) == ["C", "G"]
    assert (a.segments[0].start_sec, a.segments[0].end_sec) == (0.0, 2.0)
    assert (a.segments[1].start_sec, a.segments[1].end_sec) == (2.0, 6.0)  # slower second half
    again, _ = analyze_midi_events(
        events, ppq=480, tempo_changes=[TempoChange(1920, 60)], key=C, grid="bar"
    )
    assert again == a


def test_lookups_for_synchronised_playback() -> None:
    notes = chord_notes([(0, 4, [48, 60, 64, 67]), (4, 8, [43, 59, 62, 67])])
    a = analyze_notes(notes, grid="bar", key=C)
    assert chord_at(a, 0).best.symbol == "C" and chord_at(a, 3.99).best.symbol == "C"  # type: ignore[union-attr]
    assert chord_at(a, 4).best.symbol == "G" and chord_at(a, 8).best.symbol == "G"  # type: ignore[union-attr]
    assert chord_at(a, 8.5) is None and chord_at(a, -1) is None
    assert [n.midi for n in active_notes_at(notes, 2)] == [48, 60, 64, 67]
    assert [n.midi for n in active_notes_at(notes, 4)] == [43, 59, 62, 67]
    assert active_notes_at(notes, 9) == []


# ------------------------------------------------------------ hands


def hand_map(notes, **kw):  # type: ignore[no-untyped-def]
    return assign_hands(notes, **kw).hands


def test_hands_split_a_typical_two_handed_texture() -> None:
    notes = [
        note_at(0, 36, 0, 2),
        note_at(1, 43, 0, 2),
        note_at(2, 64, 0, 1),
        note_at(3, 67, 0, 1),
        note_at(4, 72, 1, 2),
    ]
    h = hand_map(notes)
    assert [h[0], h[1], h[2], h[3], h[4]] == ["L", "L", "R", "R", "R"]


def test_a_compact_chord_straddling_the_split_stays_in_one_hand() -> None:
    right = [note_at(0, 66, 0, 1), note_at(1, 64, 1, 2)]
    chord = [note_at(2, 57, 2, 3), note_at(3, 61, 2, 3), note_at(4, 64, 2, 3)]  # straddles middle C
    h = hand_map(right + chord)
    assert {h[2], h[3], h[4]} == {"R"}  # follows the melody just played
    left = [note_at(0, 52, 0, 1), note_at(1, 54, 1, 2)]  # a hand already playing nearby
    assert {hand_map(left + chord)[i] for i in (2, 3, 4)} == {"L"}


def test_hand_limits_and_no_crossing() -> None:
    cluster = [note_at(i, 60 + 2 * i, 0, 1) for i in range(6)]
    h = assign_hands(cluster, max_per_hand=3).hands
    assert (
        sum(1 for v in h.values() if v == "L") <= 3 and sum(1 for v in h.values() if v == "R") <= 3
    )


@given(st.lists(st.tuples(st.integers(0, 6), st.integers(30, 96)), min_size=1, max_size=40))
def test_every_note_gets_a_hand_and_the_left_never_crosses_above_the_right(items) -> None:  # type: ignore[no-untyped-def]
    notes = [note_at(i, m, s, s + 1) for i, (s, m) in enumerate(items)]
    a = assign_hands(notes)
    assert set(a.hands) == {n.id for n in notes} and set(a.source.values()) == {"auto"}
    for start in {s for s, _ in items}:
        group = [n for n in notes if n.start_beat == start]
        lows = [n.midi for n in group if a.hands[n.id] == "L"]
        highs = [n.midi for n in group if a.hands[n.id] == "R"]
        if lows and highs:
            assert max(lows) <= min(highs)


def test_tracks_are_not_assumed_to_be_hands() -> None:
    one_track = [note_at(0, 40, 0, 1, track=0), note_at(1, 76, 0, 1, track=0)]
    h = hand_map(one_track)
    assert (h[0], h[1]) == ("L", "R")  # one track, two hands
    two_tracks = [note_at(0, 76, 0, 1, track=0), note_at(1, 40, 0, 1, track=1)]
    assert hand_map(two_tracks) == {0: "R", 1: "L"}  # track order does not decide


def test_hand_assignments_are_editable_and_remember_who_decided() -> None:
    notes = [note_at(0, 48, 0, 1), note_at(1, 72, 0, 1)]
    auto = assign_hands(notes)
    edited = auto.with_user_edits({0: "R"})
    assert edited.hands[0] == "R" and edited.source == {0: "user", 1: "auto"}
    assert auto.hands[0] == "L" and auto.source[0] == "auto"  # the original is untouched
    assert [n.id for n in edited.notes_for(notes, "R")] == [0, 1]
    with pytest.raises(TheoryError):
        auto.with_user_edits({9: "L"})
    with pytest.raises(TheoryError):
        auto.with_user_edits({0: "X"})  # type: ignore[dict-item]


# ------------------------------------------------------------ tracks


def test_mute_and_solo() -> None:
    states = [TrackState(0), TrackState(1, muted=True), TrackState(2)]
    assert audible_tracks(states) == {0, 2}
    assert audible_tracks(
        [TrackState(0), TrackState(1, solo=True), TrackState(2, solo=True, muted=True)]
    ) == {1}
    assert audible_tracks([]) == set()


def test_filtering_notes_by_track_state_and_hand() -> None:
    notes = [
        note_at(0, 40, 0, 1, track=0),
        note_at(1, 72, 0, 1, track=1),
        note_at(2, 50, 0, 1, track=2),
    ]
    assignment = assign_hands(notes)
    muted = filter_audible(notes, [TrackState(1, muted=True)])
    assert [n.id for n in muted] == [0, 2]  # unknown tracks stay audible when nothing is soloed
    solo = filter_audible(notes, [TrackState(0, solo=True), TrackState(1)])
    assert [n.id for n in solo] == [0]
    assert [n.id for n in filter_audible(notes, [], assignment, only_hand="R")] == [1]
    with pytest.raises(TheoryError) as err:
        filter_audible(notes, [], only_hand="L")
    assert err.value.code == "no_assignment"


def test_merging_and_splitting_tracks() -> None:
    notes = [
        note_at(0, 40, 0, 1, track=0),
        note_at(1, 72, 0, 1, track=1),
        note_at(2, 50, 0, 1, track=2),
    ]
    assert {n.track for n in merge_tracks(notes, [1, 2], 0)} == {0}
    split = split_track_by_pitch(merge_tracks(notes, [1, 2], 0), 0, 5, 60)
    assert [(n.id, n.track) for n in split] == [(0, 0), (1, 5), (2, 0)]
    with pytest.raises(TheoryError):
        split_track_by_pitch(notes, 0, 1, 60)


def test_hand_assignment_type_is_exposed() -> None:
    assert HandAssignment({}, {}).hands == {}
