import pytest
from hypothesis import given
from hypothesis import strategies as st

from music_theory.errors import TheoryError
from music_theory.performance import (
    WINDOWS_MS,
    ExpectedNote,
    PerformanceError,
    PlayedNote,
    ScoringConfig,
    score_performance,
    window_for,
)

# 120 BPM: one beat is 0.5 s, so beat n is at n * 0.5 s with no offset.
CFG = ScoringConfig(tempo_bpm=120, window_ms=150)


def exp(midi: int, beat: float, **kw: object) -> ExpectedNote:
    return ExpectedNote(midi, beat, **kw)  # type: ignore[arg-type]


def ply(midi: int, seconds: float, off: float | None = None) -> PlayedNote:
    return PlayedNote(midi, seconds, off)


def statuses(
    expected: list[ExpectedNote], played: list[PlayedNote], cfg: ScoringConfig = CFG
) -> list[str]:
    return [n.status for n in score_performance(expected, played, cfg).notes]


# ------------------------------------------------------------------ matching and timing


def test_perfect_performance() -> None:
    e = [exp(60, 0), exp(62, 1), exp(64, 2)]
    r = score_performance(e, [ply(60, 0.0), ply(62, 0.5), ply(64, 1.0)], CFG)
    assert (r.hits, r.on_time, r.missed, r.extra, r.accuracy) == (3, 3, 0, 0, 1.0)
    assert r.timing.mean_abs_error_ms == 0.0


def test_error_sign_and_early_late_bands() -> None:
    e = [exp(60, 0), exp(62, 1), exp(64, 2)]
    r = score_performance(e, [ply(60, -0.0 + 0.0), ply(62, 0.5 - 0.1), ply(64, 1.0 + 0.1)], CFG)
    assert [n.status for n in r.notes] == ["on_time", "early", "late"]
    assert r.notes[1].error_ms == -100.0 and r.notes[2].error_ms == 100.0
    assert r.hits == 3  # early and late inside the window still count as hits


def test_note_outside_the_window_is_missed_and_the_played_note_is_extra() -> None:
    r = score_performance([exp(60, 0)], [ply(60, 0.4)], CFG)
    assert r.notes[0].status == "missed"
    assert r.extra == 1 and r.extras[0].midi == 60


def test_window_edge_is_inclusive() -> None:
    assert statuses([exp(60, 0)], [ply(60, 0.15)]) == ["late"]
    assert statuses([exp(60, 0)], [ply(60, 0.1501)]) == ["missed"]


def test_wrong_octave_is_a_miss_unless_octave_equivalent() -> None:
    assert statuses([exp(60, 0)], [ply(72, 0.0)]) == ["missed"]
    lenient = ScoringConfig(tempo_bpm=120, window_ms=150, octave_equivalent=True)
    assert statuses([exp(60, 0)], [ply(72, 0.0)], lenient) == ["on_time"]


def test_closest_played_note_wins() -> None:
    # beat 1 is at 0.5 s; one press is 80 ms early, the other 20 ms late
    r = score_performance([exp(60, 1)], [ply(60, 0.42), ply(60, 0.52)], CFG)
    assert r.notes[0].error_ms == 20.0
    assert r.extra == 1 and r.extras[0].time_s == 0.42


def test_one_played_note_cannot_satisfy_two_expected_notes() -> None:
    # the same pitch twice, 0.25 s apart (half a beat at 120 BPM); one press cannot hit both
    e = [exp(60, 0), exp(60, 0.5)]
    r = score_performance(e, [ply(60, 0.1)], ScoringConfig(tempo_bpm=120, window_ms=400))
    assert r.hits == 1 and r.missed == 1


def test_repeated_notes_each_need_their_own_press() -> None:
    e = [exp(60, 0), exp(60, 1), exp(60, 2)]
    assert statuses(e, [ply(60, 0.0), ply(60, 0.5), ply(60, 1.0)]) == ["on_time"] * 3
    assert statuses(e, [ply(60, 0.0), ply(60, 1.0)]) == ["on_time", "missed", "on_time"]


def test_count_in_offset_and_latency() -> None:
    cfg = ScoringConfig(tempo_bpm=120, window_ms=150, offset_s=2.0)
    r = score_performance([exp(60, 0), exp(62, 1)], [ply(60, 2.0), ply(62, 2.5)], cfg)
    assert r.on_time == 2
    slow = [ply(60, 2.08), ply(62, 2.58)]  # every note 80 ms late
    raw = score_performance([exp(60, 0), exp(62, 1)], slow, cfg)
    fixed = score_performance(
        [exp(60, 0), exp(62, 1)], slow, ScoringConfig(120, 150, offset_s=2.0, latency_ms=80)
    )
    assert raw.timing.mean_error_ms == 80.0 and fixed.timing.mean_error_ms == 0.0
    assert any("delay" in s for s in raw.limits)


def test_tempo_changes_the_time_grid() -> None:
    fast = ScoringConfig(tempo_bpm=240, window_ms=150)  # a beat is 0.25 s
    assert statuses([exp(60, 4)], [ply(60, 1.0)], fast) == ["on_time"]


# ------------------------------------------------------------------ near misses, extras, chords, hands


def test_near_miss_names_both_notes() -> None:
    r = score_performance([exp(65, 1)], [ply(66, 0.52)], CFG)
    n = r.notes[0]
    assert n.status == "near_miss" and n.played_midi == 66 and r.extra == 0
    assert any("F#4 instead of F4" in f for f in r.feedback)


def test_far_wrong_note_is_extra_not_near_miss() -> None:
    r = score_performance([exp(65, 1)], [ply(70, 0.5)], CFG)
    assert r.notes[0].status == "missed" and r.extra == 1 and r.near_miss == 0


def test_extra_note_reports_its_beat() -> None:
    r = score_performance([exp(60, 0)], [ply(60, 0.0), ply(70, 1.0)], CFG)
    assert r.extras[0].midi == 70 and r.extras[0].beat == 2.0


def test_chords_report_completeness_and_spread() -> None:
    e = [
        exp(60, 0, chord_index=0),
        exp(64, 0, chord_index=0),
        exp(67, 0, chord_index=0),
        exp(62, 1, chord_index=1),
    ]
    r = score_performance(e, [ply(60, 0.0), ply(64, 0.04), ply(62, 0.5)], CFG)
    c0, c1 = r.chords
    assert (c0.expected, c0.hit, c0.complete) == (3, 2, False) and c0.spread_ms == 40.0
    assert c1.complete and c1.spread_ms is None
    assert any("Chords with missing notes: 1" in f for f in r.feedback)


def test_hands_are_scored_separately() -> None:
    e = [exp(48 + i, i, hand="L") for i in range(4)] + [exp(60 + i, i, hand="R") for i in range(4)]
    played = [ply(60 + i, i * 0.5) for i in range(4)]  # right hand only
    r = score_performance(e, played, CFG)
    by = {h.hand: h for h in r.hands}
    assert by["R"].accuracy == 1.0 and by["L"].accuracy == 0.0
    assert any("left hand was less accurate" in f for f in r.feedback)


def test_hand_comparison_needs_enough_notes() -> None:
    e = [exp(48, 0, hand="L"), exp(60, 0, hand="R")]
    r = score_performance(e, [ply(60, 0.0)], CFG)
    assert not any("hand was less accurate" in f for f in r.feedback)


def test_held_ratio_and_short_holds() -> None:
    e = [exp(60, 0, duration_beats=2.0)]  # 1.0 s expected
    r = score_performance(e, [ply(60, 0.0, off=0.3)], CFG)
    assert r.notes[0].held_ratio == 0.3 and r.short_holds == 1
    assert any("released early" in f for f in r.feedback)
    ok = score_performance(e, [ply(60, 0.0, off=0.9)], CFG)
    assert ok.short_holds == 0
    assert score_performance(e, [ply(60, 0.0)], CFG).notes[0].held_ratio is None


# ------------------------------------------------------------------ tendency honesty


COUNT_IN = ScoringConfig(tempo_bpm=120, window_ms=150, offset_s=2.0)  # a two-second count-in


def line(n: int, bias_s: float) -> tuple[list[ExpectedNote], list[PlayedNote]]:
    return [exp(60 + i % 12, i) for i in range(n)], [
        ply(60 + i % 12, 2.0 + i * 0.5 + bias_s) for i in range(n)
    ]


@pytest.mark.parametrize(
    ("bias", "want"), [(-0.05, "rushing"), (0.05, "dragging"), (0.005, "steady")]
)
def test_tendency_with_enough_notes(bias: float, want: str) -> None:
    e, p = line(10, bias)
    assert score_performance(e, p, COUNT_IN).timing.tendency == want


def test_tendency_is_withheld_with_few_notes() -> None:
    e, p = line(5, -0.06)
    r = score_performance(e, p, COUNT_IN)
    assert r.timing.tendency == "not_enough_notes"
    assert any("too few to say" in f for f in r.feedback)
    assert not any("tended to" in f for f in r.feedback)


def test_no_hits_gives_no_timing_figures() -> None:
    r = score_performance([exp(60, 0)], [], CFG)
    t = r.timing
    assert t.hits == 0 and t.mean_error_ms is None and t.tendency == "not_enough_notes"
    assert r.accuracy == 0.0 and r.missed == 1
    assert not any("right on the beat" in f for f in r.feedback)


# ------------------------------------------------------------------ validation and levels


def test_levels_have_narrowing_windows() -> None:
    w = [window_for(level) for level in ("beginner", "intermediate", "advanced", "expert")]
    assert w == sorted(w, reverse=True) and w == [WINDOWS_MS[k] for k in WINDOWS_MS]
    with pytest.raises(PerformanceError) as err:
        window_for("godlike")
    assert err.value.code == "unknown_level"


@pytest.mark.parametrize(
    ("expected", "played", "cfg", "code"),
    [
        ([], [], CFG, "no_expected"),
        ([exp(60, 0)], [], ScoringConfig(10, 150), "invalid_tempo"),
        ([exp(60, 0)], [], ScoringConfig(120, 5), "invalid_window"),
        ([exp(60, 0)], [], ScoringConfig(120, 5000), "invalid_window"),
        ([exp(60, -1)], [], CFG, "invalid_expected"),
        ([exp(60, 0, duration_beats=0)], [], CFG, "invalid_expected"),
        ([exp(60, 0), exp(60, 0)], [], CFG, "duplicate_expected_note"),
        ([exp(60, 0)], [ply(60, -1)], CFG, "invalid_played"),
        ([exp(60, 0)], [ply(60, 1, off=0.5)], CFG, "invalid_played"),
    ],
)
def test_invalid_input_has_stable_codes(
    expected: list[ExpectedNote], played: list[PlayedNote], cfg: ScoringConfig, code: str
) -> None:
    with pytest.raises(PerformanceError) as err:
        score_performance(expected, played, cfg)
    assert err.value.code == code


def test_out_of_range_midi_is_refused() -> None:
    with pytest.raises(TheoryError):
        score_performance([exp(300, 0)], [], CFG)
    with pytest.raises(TheoryError):
        score_performance([exp(60, 0)], [ply(-1, 0.0)], CFG)


def test_too_many_notes_is_refused() -> None:
    many = [exp(60, i) for i in range(5001)]
    with pytest.raises(PerformanceError) as err:
        score_performance(many, [], CFG)
    assert err.value.code == "too_many_notes"


def test_is_deterministic() -> None:
    e, p = line(12, 0.03)
    assert score_performance(e, p, CFG) == score_performance(e, p, CFG)


# ------------------------------------------------------------------ properties


notes = st.lists(
    st.tuples(st.integers(36, 84), st.integers(0, 60)), min_size=1, max_size=25, unique=True
)


@given(notes, st.lists(st.tuples(st.integers(36, 84), st.floats(0, 40)), max_size=40))
def test_counts_always_add_up(
    exp_pairs: list[tuple[int, int]], played_pairs: list[tuple[int, float]]
) -> None:
    e = [exp(m, b / 2) for m, b in exp_pairs]
    p = [ply(m, t) for m, t in played_pairs]
    r = score_performance(e, p, CFG)
    assert r.hits + r.missed + r.near_miss == r.expected
    assert r.on_time + r.early + r.late == r.hits
    assert len(r.notes) == r.expected
    # every played note is hit, a near miss, or extra: none is counted twice
    assert r.hits + r.near_miss + r.extra == len(p)
    assert 0.0 <= r.accuracy <= 1.0


@given(notes)
def test_playing_exactly_as_written_scores_perfectly(pairs: list[tuple[int, int]]) -> None:
    e = [exp(m, b / 2) for m, b in pairs]
    p = [ply(m, b / 2 * 0.5) for m, b in pairs]
    r = score_performance(e, p, CFG)
    assert r.accuracy == 1.0 and r.extra == 0 and r.timing.mean_abs_error_ms == 0.0


@given(notes)
def test_playing_nothing_scores_zero(pairs: list[tuple[int, int]]) -> None:
    r = score_performance([exp(m, b / 2) for m, b in pairs], [], CFG)
    assert r.hits == 0 and r.missed == r.expected and r.accuracy == 0.0


# ------------------------------------------------------------------ practising one section


def test_restrict_to_beats_ignores_notes_outside_the_loop() -> None:
    from music_theory.performance import restrict_to_beats

    e = [exp(60 + i, i) for i in range(8)]  # one note per beat
    p = [ply(60 + i, i * 0.5) for i in range(8)]
    ke, kp = restrict_to_beats(e, p, CFG, 2, 5)
    assert [n.start_beat for n in ke] == [2, 3, 4]
    # played notes from beats 2-4 plus the ones inside the 150 ms margin; nothing from far away
    assert {n.midi for n in kp} == {62, 63, 64, 65}
    r = score_performance(ke, kp, CFG)
    assert r.accuracy == 1.0 and r.missed == 0


def test_restrict_to_beats_validates_the_range() -> None:
    from music_theory.performance import restrict_to_beats

    with pytest.raises(PerformanceError) as err:
        restrict_to_beats([exp(60, 0)], [], CFG, 4, 2)
    assert err.value.code == "invalid_range"
