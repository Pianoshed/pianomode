"""Scoring a performance against expected notes (Phase 7, step 1).

Given what *should* be played (notes with beat positions, as in a movement's playback data) and
what *was* played (note-on times from a MIDI keyboard or the on-screen piano), report which notes
were hit, early, late, missed or extra, how the timing tended to go, and short plain-language
feedback. Everything is deterministic: the same input always gives the same result.

What this is not:
- It is not a grade. It reports counts and percentages and says how many notes they rest on.
- It does not judge touch, tone, pedalling or musicality. Velocity is not scored.
- Timing tendencies ("rushing", "dragging") are only reported with enough notes behind them.

Heuristics (all stated here so they can be challenged):
- A played note matches an expected note of the same pitch if it falls inside the timing window.
  The window is capped at half the gap to a neighbouring expected note of the same pitch, so one
  played note can never be claimed by two expected notes.
- Inside the window, the closest played note wins.
- `on_time` means within half the window; `early`/`late` are hits in the outer half.
- A missed note with an unmatched played note 1-2 semitones away at about the same time is
  reported as a near miss ("played E4 instead of F4"), not as a miss plus an unrelated extra.
- Tendency needs at least 8 hits and an average error of at least 20 ms; both numbers are
  rules of thumb, not measured thresholds.
- Input latency (a keyboard or a browser adding delay) shifts every note equally. If the player
  knows it, `latency_ms` removes it; otherwise it is mixed into the timing figures.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from typing import Final, Literal

from music_theory.errors import TheoryError
from music_theory.notes import check_midi, note_from_midi

WINDOWS_MS: Final[dict[str, float]] = {
    "beginner": 250.0,
    "intermediate": 150.0,
    "advanced": 90.0,
    "expert": 60.0,
}
MIN_WINDOW_MS: Final = 20.0
MAX_WINDOW_MS: Final = 1000.0
MAX_NOTES: Final = 5000
MIN_TEMPO: Final = 20.0
MAX_TEMPO: Final = 400.0
TENDENCY_MIN_HITS: Final = 8
TENDENCY_MIN_MS: Final = 20.0
SHORT_HOLD_RATIO: Final = 0.5
NEAR_MISS_SEMITONES: Final = 2
HAND_GAP_POINTS: Final = 15.0
HAND_MIN_NOTES: Final = 4

Status = Literal["on_time", "early", "late", "missed", "near_miss"]
Tendency = Literal["rushing", "dragging", "steady", "not_enough_notes"]


class PerformanceError(TheoryError):
    code = "invalid_performance"


@dataclass(frozen=True)
class ExpectedNote:
    midi: int
    start_beat: float
    duration_beats: float = 1.0
    hand: Literal["L", "R"] | None = None
    chord_index: int | None = None


@dataclass(frozen=True)
class PlayedNote:
    midi: int
    time_s: float  # note-on, seconds from the start of the recording
    off_time_s: float | None = None  # note-off, if known


@dataclass(frozen=True)
class ScoringConfig:
    tempo_bpm: float
    window_ms: float
    offset_s: float = 0.0  # when beat 0 happened, in recording time (after any count-in)
    latency_ms: float = 0.0  # known input delay to remove from every played note
    octave_equivalent: bool = False  # accept the right note name in any octave


@dataclass(frozen=True)
class NoteResult:
    index: int  # position in the expected list
    midi: int
    name: str
    start_beat: float
    hand: str | None
    chord_index: int | None
    status: Status
    error_ms: float | None  # played minus expected; negative is early. None when missed
    played_midi: int | None  # for a near miss, the note actually played
    held_ratio: float | None  # held time / expected time, when a note-off was given


@dataclass(frozen=True)
class ExtraNote:
    midi: int
    name: str
    time_s: float
    beat: float


@dataclass(frozen=True)
class ChordResult:
    chord_index: int
    expected: int
    hit: int
    complete: bool
    spread_ms: float | None  # gap between first and last matched note of the chord


@dataclass(frozen=True)
class HandResult:
    hand: str
    expected: int
    hit: int
    accuracy: float


@dataclass(frozen=True)
class TimingSummary:
    hits: int
    mean_error_ms: float | None
    mean_abs_error_ms: float | None
    median_error_ms: float | None
    spread_ms: float | None  # population standard deviation of the errors
    tendency: Tendency


@dataclass(frozen=True)
class PerformanceResult:
    expected: int
    hits: int
    on_time: int
    early: int
    late: int
    missed: int
    near_miss: int
    extra: int
    short_holds: int
    accuracy: float  # hits / expected, 0.0 to 1.0
    timing: TimingSummary
    notes: tuple[NoteResult, ...]
    extras: tuple[ExtraNote, ...]
    chords: tuple[ChordResult, ...]
    hands: tuple[HandResult, ...]
    feedback: tuple[str, ...]
    window_ms: float
    limits: tuple[str, ...]


def window_for(level: str) -> float:
    try:
        return WINDOWS_MS[level]
    except KeyError:
        raise PerformanceError(
            f"Unknown level {level!r}; use one of {', '.join(WINDOWS_MS)}.", code="unknown_level"
        ) from None


# ------------------------------------------------------------------ validation


def _check(expected: list[ExpectedNote], played: list[PlayedNote], cfg: ScoringConfig) -> None:
    if not expected:
        raise PerformanceError("There are no expected notes to score against.", code="no_expected")
    if len(expected) > MAX_NOTES or len(played) > MAX_NOTES:
        raise PerformanceError(f"At most {MAX_NOTES} notes in each list.", code="too_many_notes")
    if not MIN_TEMPO <= cfg.tempo_bpm <= MAX_TEMPO:
        raise PerformanceError(
            f"Tempo must be {MIN_TEMPO:g} to {MAX_TEMPO:g} BPM.", code="invalid_tempo"
        )
    if not MIN_WINDOW_MS <= cfg.window_ms <= MAX_WINDOW_MS:
        raise PerformanceError(
            f"The timing window must be {MIN_WINDOW_MS:g} to {MAX_WINDOW_MS:g} ms.",
            code="invalid_window",
        )
    seen: set[tuple[int, float]] = set()
    for e in expected:
        check_midi(e.midi)
        if e.start_beat < 0 or e.duration_beats <= 0:
            raise PerformanceError(
                "Expected notes need a start of 0 or more and a positive duration.",
                code="invalid_expected",
            )
        key = (e.midi, round(e.start_beat, 6))
        if key in seen:
            raise PerformanceError(
                "Two expected notes share a pitch and start; one keyboard cannot play both.",
                code="duplicate_expected_note",
            )
        seen.add(key)
    for p in played:
        check_midi(p.midi)
        if p.time_s < 0 or (p.off_time_s is not None and p.off_time_s < p.time_s):
            raise PerformanceError(
                "Played notes need a time of 0 or more, and a note-off after the note-on.",
                code="invalid_played",
            )


def _name(midi: int) -> str:
    return str(note_from_midi(midi))


# ------------------------------------------------------------------ selecting what to score


def restrict_to_beats(
    expected: list[ExpectedNote],
    played: list[PlayedNote],
    cfg: ScoringConfig,
    start_beat: float,
    end_beat: float,
) -> tuple[list[ExpectedNote], list[PlayedNote]]:
    """Keep only the expected notes that start in [start_beat, end_beat) and the played notes
    near that stretch, so practising one section (a loop) is not marked down for what was played
    before or after it. `offset_s` must still be the time of beat 0, even when the player began
    mid-piece (time of the loop start minus start_beat * seconds-per-beat)."""
    if not 0 <= start_beat < end_beat:
        raise PerformanceError(
            "The beat range must start at 0 or later and end after it.", code="invalid_range"
        )
    beat_s = 60.0 / cfg.tempo_bpm
    margin = cfg.window_ms / 1000.0
    lo = cfg.offset_s + start_beat * beat_s - margin
    hi = cfg.offset_s + end_beat * beat_s + margin
    shift = cfg.latency_ms / 1000.0
    kept = [e for e in expected if start_beat <= e.start_beat < end_beat]
    near = [p for p in played if lo <= p.time_s - shift <= hi]
    return kept, near


# ------------------------------------------------------------------ scoring


def score_performance(
    expected: list[ExpectedNote], played: list[PlayedNote], cfg: ScoringConfig
) -> PerformanceResult:
    _check(expected, played, cfg)
    beat_s = 60.0 / cfg.tempo_bpm
    window_s = cfg.window_ms / 1000.0
    shift = cfg.latency_ms / 1000.0

    def pkey(midi: int) -> int:
        return midi % 12 if cfg.octave_equivalent else midi

    exp_time = [cfg.offset_s + e.start_beat * beat_s for e in expected]
    play_time = [p.time_s - shift for p in played]

    # effective window per expected note: never wider than half the gap to the same pitch's
    # neighbours, so no played note can fall inside two expected windows
    groups: dict[int, list[int]] = {}
    for i, e in enumerate(expected):
        groups.setdefault(pkey(e.midi), []).append(i)
    eff = [window_s] * len(expected)
    for idxs in groups.values():
        idxs.sort(key=lambda i: exp_time[i])
        for a, b in zip(idxs, idxs[1:], strict=False):
            half = (exp_time[b] - exp_time[a]) / 2.0
            eff[a] = min(eff[a], half)
            eff[b] = min(eff[b], half)

    used = [False] * len(played)
    match: dict[int, int] = {}
    order = sorted(range(len(expected)), key=lambda i: (exp_time[i], expected[i].midi))
    for i in order:
        best: int | None = None
        best_err = 0.0
        for j, p in enumerate(played):
            if used[j] or pkey(p.midi) != pkey(expected[i].midi):
                continue
            err = play_time[j] - exp_time[i]
            if abs(err) <= eff[i] and (best is None or abs(err) < abs(best_err)):
                best, best_err = j, err
        if best is not None:
            used[best] = True
            match[i] = best

    # near misses: a missed note and an unused played note a semitone or two away, close in time
    near: dict[int, int] = {}
    for i in order:
        if i in match:
            continue
        pick: int | None = None
        pick_key = (99.0, 99.0)
        for j, p in enumerate(played):
            if used[j]:
                continue
            gap = abs(p.midi - expected[i].midi)
            if not 1 <= gap <= NEAR_MISS_SEMITONES or cfg.octave_equivalent and gap == 0:
                continue
            err = abs(play_time[j] - exp_time[i])
            if err <= 2 * window_s and (gap, err) < pick_key:
                pick, pick_key = j, (float(gap), err)
        if pick is not None:
            used[pick] = True
            near[i] = pick

    results: list[NoteResult] = []
    errors: list[float] = []
    half = window_s / 2.0

    def make(
        i: int,
        status: Status,
        error_ms: float | None = None,
        played_midi: int | None = None,
        held_ratio: float | None = None,
    ) -> NoteResult:
        e = expected[i]
        return NoteResult(
            i, e.midi, _name(e.midi), e.start_beat, e.hand, e.chord_index,
            status, error_ms, played_midi, held_ratio,
        )  # fmt: skip

    for i, e in enumerate(expected):
        if i in match:
            j = match[i]
            err = play_time[j] - exp_time[i]
            errors.append(err * 1000.0)
            status: Status = "on_time" if abs(err) <= half else ("early" if err < 0 else "late")
            ratio = None
            off = played[j].off_time_s
            if off is not None:
                ratio = round((off - played[j].time_s) / (e.duration_beats * beat_s), 4)
            results.append(make(i, status, round(err * 1000.0, 3), played[j].midi, ratio))
        elif i in near:
            results.append(make(i, "near_miss", None, played[near[i]].midi))
        else:
            results.append(make(i, "missed"))

    extras = tuple(
        ExtraNote(
            p.midi,
            _name(p.midi),
            round(p.time_s, 6),
            round((play_time[j] - cfg.offset_s) / beat_s, 4),
        )
        for j, p in enumerate(played)
        if not used[j]
    )

    hits = sum(1 for r in results if r.status in ("on_time", "early", "late"))
    count = {
        s: sum(1 for r in results if r.status == s)
        for s in ("on_time", "early", "late", "missed", "near_miss")
    }
    short = sum(1 for r in results if r.held_ratio is not None and r.held_ratio < SHORT_HOLD_RATIO)

    timing = _timing(errors)
    chords = _chords(results, played, match, play_time)
    hands = _hands(results)
    result = PerformanceResult(
        expected=len(expected), hits=hits, on_time=count["on_time"], early=count["early"],
        late=count["late"], missed=count["missed"], near_miss=count["near_miss"],
        extra=len(extras), short_holds=short, accuracy=round(hits / len(expected), 4),
        timing=timing, notes=tuple(results), extras=extras, chords=chords, hands=hands,
        feedback=(), window_ms=cfg.window_ms, limits=_limits(cfg),
    )  # fmt: skip
    return _with_feedback(result)


def _timing(errors: list[float]) -> TimingSummary:
    if not errors:
        return TimingSummary(0, None, None, None, None, "not_enough_notes")
    mean = statistics.fmean(errors)
    tendency: Tendency = "not_enough_notes"
    if len(errors) >= TENDENCY_MIN_HITS:
        tendency = (
            "rushing" if mean <= -TENDENCY_MIN_MS
            else "dragging" if mean >= TENDENCY_MIN_MS
            else "steady"
        )  # fmt: skip
    return TimingSummary(
        hits=len(errors),
        mean_error_ms=round(mean, 2),
        mean_abs_error_ms=round(statistics.fmean(abs(e) for e in errors), 2),
        median_error_ms=round(statistics.median(errors), 2),
        spread_ms=round(statistics.pstdev(errors), 2),
        tendency=tendency,
    )


def _chords(
    results: list[NoteResult],
    played: list[PlayedNote],
    match: dict[int, int],
    play_time: list[float],
) -> tuple[ChordResult, ...]:
    by_chord: dict[int, list[int]] = {}
    for r in results:
        if r.chord_index is not None:
            by_chord.setdefault(r.chord_index, []).append(r.index)
    out: list[ChordResult] = []
    for c in sorted(by_chord):
        idxs = by_chord[c]
        hit = [i for i in idxs if results[i].status in ("on_time", "early", "late")]
        times = [play_time[match[i]] for i in hit]
        spread = round((max(times) - min(times)) * 1000.0, 2) if len(times) >= 2 else None
        out.append(ChordResult(c, len(idxs), len(hit), len(hit) == len(idxs), spread))
    return tuple(out)


def _hands(results: list[NoteResult]) -> tuple[HandResult, ...]:
    out: list[HandResult] = []
    for hand in ("L", "R"):
        rs = [r for r in results if r.hand == hand]
        if rs:
            hit = sum(1 for r in rs if r.status in ("on_time", "early", "late"))
            out.append(HandResult(hand, len(rs), hit, round(hit / len(rs), 4)))
    return tuple(out)


def _limits(cfg: ScoringConfig) -> tuple[str, ...]:
    lim = [
        "Scores notes and timing only. Touch, tone, pedalling and musicality are not judged.",
        "Timing includes any delay added by the keyboard, browser or audio device"
        + (f" except the {cfg.latency_ms:g} ms you said to remove." if cfg.latency_ms else "."),
    ]
    if cfg.octave_equivalent:
        lim.append("Notes in the wrong octave count as correct.")
    return tuple(lim)


# ------------------------------------------------------------------ feedback


def _beat_text(beat: float) -> str:
    whole = round(beat + 1.0, 2)  # people count beats from 1
    return f"beat {whole:g}"


def _plural(n: int, one: str, many: str) -> str:
    return one if n == 1 else many


def _with_feedback(r: PerformanceResult) -> PerformanceResult:
    msgs: list[str] = []
    pct = round(r.accuracy * 100)
    line = f"You hit {r.hits} of {r.expected} notes ({pct}%) within {r.window_ms:g} ms."
    msgs.append(line + (f" {r.on_time} were right on the beat." if r.hits else ""))
    for n in [x for x in r.notes if x.status == "near_miss"][:3]:
        played = _name(n.played_midi) if n.played_midi is not None else "?"
        msgs.append(f"At {_beat_text(n.start_beat)} you played {played} instead of {n.name}.")
    mean = r.timing.mean_error_ms or 0.0
    if r.timing.tendency == "rushing":
        msgs.append(f"You tended to play early, by about {abs(mean):g} ms on average.")
    elif r.timing.tendency == "dragging":
        msgs.append(f"You tended to play late, by about {mean:g} ms on average.")
    elif r.timing.tendency == "not_enough_notes" and r.hits:
        msgs.append(
            f"Only {r.hits} notes were hit, too few to say whether you rush or drag "
            f"(at least {TENDENCY_MIN_HITS} are needed)."
        )
    if len(r.hands) == 2 and all(h.expected >= HAND_MIN_NOTES for h in r.hands):
        lo, hi = sorted(r.hands, key=lambda h: h.accuracy)
        if (hi.accuracy - lo.accuracy) * 100 >= HAND_GAP_POINTS:
            side = "left" if lo.hand == "L" else "right"
            msgs.append(
                f"Your {side} hand was less accurate "
                f"({round(lo.accuracy * 100)}% against {round(hi.accuracy * 100)}%)."
            )
    incomplete = [c.chord_index + 1 for c in r.chords if not c.complete]
    if incomplete:
        shown = ", ".join(str(i) for i in incomplete[:5])
        msgs.append(
            f"Chords with missing notes: {shown}" + (" and more." if len(incomplete) > 5 else ".")
        )
    if r.extra:
        noun = _plural(r.extra, "extra note", "extra notes")
        msgs.append(f"{r.extra} {noun} played that the music did not ask for.")
    if r.short_holds:
        noun = _plural(r.short_holds, "note was", "notes were")
        msgs.append(f"{r.short_holds} {noun} released early (held under half the written length).")
    return PerformanceResult(**{**r.__dict__, "feedback": tuple(msgs[:7])})
