"""Harmony from MIDI note events.

The engine takes note events (already parsed from a file by the MIDI layer) and answers: which
notes sound when, which chord is each stretch most plausibly, what key is it probably in, and which
hand plays what. Everything here is an estimate built on the same chord and key definitions as the
rest of the engine; results carry alternatives, assumptions and warnings, never a bare verdict.
Sustain pedal, pitch bend and other controllers are not interpreted.
"""

from __future__ import annotations

import bisect
import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any, Literal

from music_theory.errors import TheoryError
from music_theory.identify import ChordCandidate, Identification, identify_chord
from music_theory.key_analysis import KeyEstimate, estimate_key
from music_theory.keys import Key
from music_theory.notes import NoteName, Preference, spell_pitch_class
from music_theory.roman import RomanNumeral, analyze_chord

Hand = Literal["L", "R"]
DEFAULT_BPM = 120.0


class MidiDataError(TheoryError):
    code = "invalid_midi_event"


# ------------------------------------------------------------------ events and timing


@dataclass(frozen=True)
class MidiEvent:
    tick: int
    kind: Literal["note_on", "note_off"]
    note: int
    velocity: int = 64
    channel: int = 0
    track: int = 0


@dataclass(frozen=True)
class TempoChange:
    tick: int
    bpm: float


@dataclass(frozen=True)
class TimeSignatureChange:
    tick: int
    numerator: int
    denominator: int


class TempoMap:
    """Converts ticks to quarter-note beats and seconds, honouring tempo changes."""

    def __init__(self, ppq: int, changes: Sequence[TempoChange] = ()) -> None:
        if not isinstance(ppq, int) or isinstance(ppq, bool) or ppq < 1:
            raise MidiDataError("ppq (ticks per quarter note) must be a positive integer")
        ordered = sorted(changes, key=lambda c: c.tick)
        for c in ordered:
            if c.tick < 0 or not math.isfinite(c.bpm) or not 1 <= c.bpm <= 1000:
                raise MidiDataError("Tempo changes need tick >= 0 and a tempo of 1-1000 BPM")
        if not ordered or ordered[0].tick != 0:
            ordered.insert(0, TempoChange(0, DEFAULT_BPM))  # MIDI's default until told otherwise
        self.ppq = ppq
        self._ticks = [c.tick for c in ordered]
        self._bpm = [c.bpm for c in ordered]
        self._base = [0.0]
        for i in range(1, len(ordered)):
            span = (self._ticks[i] - self._ticks[i - 1]) / ppq
            self._base.append(self._base[-1] + span * 60.0 / self._bpm[i - 1])

    def beats(self, tick: int) -> float:
        return tick / self.ppq

    def seconds(self, tick: int) -> float:
        i = bisect.bisect_right(self._ticks, tick) - 1
        return self._base[i] + (tick - self._ticks[i]) / self.ppq * 60.0 / self._bpm[i]


@dataclass(frozen=True)
class NoteEvent:
    id: int
    midi: int
    velocity: int
    channel: int
    track: int
    start_beat: float
    end_beat: float
    start_sec: float
    end_sec: float

    @property
    def duration_beats(self) -> float:
        return self.end_beat - self.start_beat


def note_at(
    id: int,
    midi: int,
    start: float,
    end: float,
    *,
    velocity: int = 80,
    track: int = 0,
    bpm: float = DEFAULT_BPM,
) -> NoteEvent:  # fmt: skip
    """A note given directly in beats (constant tempo). Handy for tests and generated material."""
    spb = 60.0 / bpm
    return NoteEvent(id, midi, velocity, 0, track, start, end, start * spb, end * spb)


@dataclass(frozen=True)
class NoteExtraction:
    notes: tuple[NoteEvent, ...]
    warnings: tuple[str, ...]


def notes_from_events(
    events: Sequence[MidiEvent], tempo_map: TempoMap, *, end_tick: int | None = None
) -> NoteExtraction:  # fmt: skip
    """Pair note-on/off events into notes. A note-on with velocity 0 is a note-off. Repeated
    notes pair first-on with first-off. Unreleased notes end at `end_tick` (default: the last
    event); stray note-offs and zero-length notes are dropped with a warning."""
    for i, e in enumerate(events):
        if e.kind not in ("note_on", "note_off"):
            raise MidiDataError(f"Event {i + 1}: unknown kind {e.kind!r}")
        if not (isinstance(e.tick, int) and e.tick >= 0):
            raise MidiDataError(f"Event {i + 1}: tick must be a non-negative integer")
        if not 0 <= e.note <= 127 or not 0 <= e.velocity <= 127:
            raise MidiDataError(f"Event {i + 1}: note and velocity must be 0-127")
    warnings: list[str] = []

    def is_off(e: MidiEvent) -> bool:
        return e.kind == "note_off" or e.velocity == 0

    order = sorted(
        range(len(events)), key=lambda i: (events[i].tick, 0 if is_off(events[i]) else 1, i)
    )
    open_notes: dict[tuple[int, int, int], list[tuple[int, int]]] = {}
    raw: list[
        tuple[int, int, int, int, int, int]
    ] = []  # start, end, midi, velocity, channel, track
    for i in order:
        e = events[i]
        key = (e.track, e.channel, e.note)
        if is_off(e):
            stack = open_notes.get(key)
            if not stack:
                warnings.append(
                    f"Note-off for {e.note} at tick {e.tick} had no matching note-on; ignored."
                )
                continue
            start, vel = stack.pop(0)
            raw.append((start, e.tick, e.note, vel, e.channel, e.track))
        else:
            open_notes.setdefault(key, []).append((e.tick, e.velocity))
    last = max((e.tick for e in events), default=0)
    close_at = last if end_tick is None else end_tick
    for (track, channel, note), stack in open_notes.items():
        for start, vel in stack:
            warnings.append(
                f"Note {note} at tick {start} was never released; ended at tick {close_at}."
            )
            raw.append((start, close_at, note, vel, channel, track))
    kept = []
    for start, end, midi, vel, ch, tr in raw:
        if end <= start:
            warnings.append(f"Zero-length note {midi} at tick {start} dropped.")
            continue
        kept.append((start, end, midi, vel, ch, tr))
    kept.sort(key=lambda r: (r[0], r[2], r[5], r[4], r[1]))
    notes = tuple(
        NoteEvent(
            i,
            midi,
            vel,
            ch,
            tr,
            tempo_map.beats(s),
            tempo_map.beats(e),
            tempo_map.seconds(s),
            tempo_map.seconds(e),
        )  # fmt: skip
        for i, (s, e, midi, vel, ch, tr) in enumerate(kept)
    )
    return NoteExtraction(notes, tuple(warnings))


# ------------------------------------------------------------------ bars and grid

Grid = Literal["beat", "half_bar", "bar"]


def _check_signature(ts: TimeSignatureChange) -> None:
    if ts.numerator < 1 or ts.denominator not in (1, 2, 4, 8, 16, 32) or ts.tick < 0:
        raise MidiDataError(f"{ts.numerator}/{ts.denominator} is not a valid time signature")


def _bar_beats(ts: TimeSignatureChange) -> float:
    return ts.numerator * 4 / ts.denominator


def _beat_unit(ts: TimeSignatureChange) -> float:
    """Length of one counted beat in quarter notes (compound metres count dotted beats)."""
    if ts.denominator == 8 and ts.numerator in (6, 9, 12):
        return 1.5
    return 4 / ts.denominator


def _bars(
    total_beats: float, signatures: Sequence[TimeSignatureChange], ppq: int
) -> list[tuple[float, float, TimeSignatureChange]]:  # fmt: skip
    sigs = sorted(signatures, key=lambda s: s.tick)
    for s in sigs:
        _check_signature(s)
    if not sigs or sigs[0].tick != 0:
        sigs.insert(0, TimeSignatureChange(0, 4, 4))
    bars, pos, idx = [], 0.0, 0
    while pos < total_beats - 1e-9:
        while idx + 1 < len(sigs) and sigs[idx + 1].tick / ppq <= pos + 1e-9:
            idx += 1
        ts = sigs[idx]
        end = pos + _bar_beats(ts)
        if idx + 1 < len(sigs):  # a change inside a bar starts a new bar
            end = (
                min(end, sigs[idx + 1].tick / ppq) if sigs[idx + 1].tick / ppq > pos + 1e-9 else end
            )
        bars.append((pos, end, ts))
        pos = end
    return bars


def _cells(
    bars: list[tuple[float, float, TimeSignatureChange]], grid: Grid
) -> list[tuple[float, float]]:
    out: list[tuple[float, float]] = []
    for start, end, ts in bars:
        if grid == "bar":
            out.append((start, end))
        elif grid == "half_bar":
            mid = start + (end - start) / 2
            out += [(start, mid), (mid, end)]
        else:
            unit = _beat_unit(ts)
            p = start
            while p < end - 1e-9:
                out.append((p, min(p + unit, end)))
                p += unit
    return out


# ------------------------------------------------------------------ chord segmentation


@dataclass(frozen=True)
class ChordSegment:
    start_beat: float
    end_beat: float
    start_sec: float
    end_sec: float
    status: Literal["identified", "ambiguous", "no_reliable_label", "silence"]
    candidates: tuple[ChordCandidate, ...]
    reason: str | None
    bass: NoteName | None
    pitches: tuple[int, ...]  # distinct sounding MIDI pitches considered
    cells: int  # how many grid cells were merged into this segment
    numeral: RomanNumeral | None = None
    warnings: tuple[str, ...] = ()

    @property
    def best(self) -> ChordCandidate | None:
        return self.candidates[0] if self.candidates else None

    @property
    def origin(self) -> str:
        return "midi"  # constructed from known pitches, not inferred from audio


@dataclass(frozen=True)
class MidiAnalysis:
    segments: tuple[ChordSegment, ...]
    key_estimate: KeyEstimate
    key: Key | None
    key_source: Literal["provided", "estimated"] | None
    note_count: int
    duration_beats: float
    warnings: tuple[str, ...]


def _velocity_weight(velocity: int) -> float:
    return 0.5 + velocity / 254.0


def _analyze_cell(
    notes: Sequence[NoteEvent], c0: float, c1: float, *, key: Key | None, prefer: Preference,
    max_candidates: int, min_fraction: float,
) -> tuple[Identification | None, tuple[int, ...], NoteName | None, list[str]]:  # fmt: skip
    length = c1 - c0
    overlapping = [(n, min(n.end_beat, c1) - max(n.start_beat, c0)) for n in notes]
    overlapping = [(n, o) for n, o in overlapping if o > 1e-9]
    if not overlapping:
        return None, (), None, []
    warnings: list[str] = []
    relevant = [(n, o) for n, o in overlapping if o >= min_fraction * length - 1e-9]
    if not relevant:
        relevant = overlapping
        warnings.append("Only very short notes here; the reading is weak.")
    midis = sorted({n.midi for n, _ in relevant})
    result = identify_chord(midis, key=key, prefer=prefer, max_candidates=max_candidates)
    if result.status == "no_reliable_label" and len({m % 12 for m in midis}) >= 3:
        loose = identify_chord(
            midis, key=key, prefer=prefer, max_candidates=max_candidates, max_extra_tones=1
        )
        if loose.candidates:
            result = loose
    bass_pool = [n for n, o in relevant if o >= 0.25 * length - 1e-9] or [n for n, _ in relevant]
    low = min(n.midi for n in bass_pool)
    bass = result.bass if result.bass is not None and min(midis) == low else None
    if bass is None:
        bass = key.signature.spell(low) if key is not None else spell_pitch_class(low % 12, prefer)
    return result, tuple(midis), bass, warnings


def analyze_notes(
    notes: Sequence[NoteEvent],
    *,
    time_signatures: Sequence[TimeSignatureChange] = (),
    key: Key | None = None,
    grid: Grid = "beat",
    prefer: Preference = "sharps",
    max_candidates: int = 3,
    min_note_fraction: float = 0.2,
    ppq: int = 480,
) -> MidiAnalysis:
    """Segment notes into chords on a bar/beat grid and interpret each stretch.

    - `grid`: analysis cell size: one counted beat, half a bar, or a whole bar. Adjacent cells
      with the same best chord are merged.
    - Notes sounding for less than `min_note_fraction` of a cell are treated as passing tones.
    - Key: given, else estimated from the notes (only used if the estimate has enough evidence);
      without a key there are no Roman numerals.
    """
    if grid not in ("beat", "half_bar", "bar"):
        raise TheoryError("grid must be 'beat', 'half_bar' or 'bar'", code="invalid_grid")
    if not 0 <= min_note_fraction <= 1:
        raise TheoryError("min_note_fraction must be between 0 and 1", code="invalid_parameter")
    warnings: list[str] = []
    if not notes:
        empty = KeyEstimate((), False, False, ("No notes.",), "krumhansl-schmuckler")
        return MidiAnalysis(
            (), empty, key, "provided" if key else None, 0, 0.0, ("No notes to analyse.",)
        )

    weights = [0.0] * 12
    for n in notes:
        weights[n.midi % 12] += n.duration_beats * _velocity_weight(n.velocity)
    estimate = estimate_key(weights)
    used = key
    source: Literal["provided", "estimated"] | None = "provided" if key is not None else None
    if used is None and estimate.reliable and estimate.best is not None:
        used, source = estimate.best.key, "estimated"
        if estimate.ambiguous:
            warnings.append(
                f"The key is uncertain ({used} is one of several close fits); "
                "numerals are relative to it."
            )
    elif used is None:
        warnings.append(
            "Not enough harmonic evidence to estimate a key, so no Roman numerals are given."
        )

    total = max(n.end_beat for n in notes)
    cells = [
        (a, min(b, total))
        for a, b in _cells(_bars(total, time_signatures, ppq), grid)
        if a < total - 1e-9
    ]  # nothing is analysed after the last note ends
    sec_of = _seconds_interpolator(notes)

    # Cells come in ascending order, so keep a window of notes that can touch the current cell
    # instead of rescanning every note per cell (which is quadratic on long files).
    by_start = sorted(notes, key=lambda n: n.start_beat)
    active: list[NoteEvent] = []
    upcoming = 0
    raw: list[ChordSegment] = []
    for c0, c1 in cells:
        while upcoming < len(by_start) and by_start[upcoming].start_beat < c1:
            active.append(by_start[upcoming])
            upcoming += 1
        active = [n for n in active if n.end_beat > c0]
        result, midis, bass, cell_warnings = _analyze_cell(
            active, c0, c1, key=used, prefer=prefer, max_candidates=max_candidates,
            min_fraction=min_note_fraction,
        )  # fmt: skip
        t0, t1 = sec_of(c0), sec_of(c1)
        if result is None:
            raw.append(ChordSegment(c0, c1, t0, t1, "silence", (), None, None, (), 1))
        else:
            raw.append(
                ChordSegment(
                    c0,
                    c1,
                    t0,
                    t1,
                    result.status,
                    result.candidates,
                    result.reason,
                    bass,
                    midis,
                    1,
                    None,
                    tuple(cell_warnings),
                )
            )

    merged: list[ChordSegment] = []
    for seg in raw:
        prev = merged[-1] if merged else None
        if prev is not None and _same_reading(prev, seg):
            merged[-1] = replace(
                prev, end_beat=seg.end_beat, end_sec=seg.end_sec, cells=prev.cells + 1,
                pitches=tuple(sorted(set(prev.pitches) | set(seg.pitches))),
                warnings=tuple(dict.fromkeys((*prev.warnings, *seg.warnings))),
            )  # fmt: skip
        else:
            merged.append(seg)
    if used is not None:
        merged = [
            replace(s, numeral=analyze_chord(s.best.chord, used)) if s.best is not None else s
            for s in merged
        ]
    return MidiAnalysis(tuple(merged), estimate, used, source, len(notes), total, tuple(warnings))


def _same_reading(a: ChordSegment, b: ChordSegment) -> bool:
    if a.status == b.status == "silence":
        return True
    if a.best is not None and b.best is not None:
        return a.best.symbol == b.best.symbol
    if a.status == b.status == "no_reliable_label":
        return {p % 12 for p in a.pitches} == {p % 12 for p in b.pitches}
    return False


def _seconds_interpolator(notes: Sequence[NoteEvent]) -> Callable[[float], float]:
    """Beat -> seconds using the tempo implied by the notes' own timings (exact for notes)."""
    points = sorted(
        {(n.start_beat, n.start_sec) for n in notes} | {(n.end_beat, n.end_sec) for n in notes}
    )
    beats = [p[0] for p in points]

    def sec(beat: float) -> float:
        i = bisect.bisect_left(beats, beat)
        if i < len(beats) and abs(beats[i] - beat) < 1e-9:
            return points[i][1]
        if i == 0:
            b0, s0 = points[0]
            nb, ns = points[1] if len(points) > 1 else (b0 + 1, s0 + 60 / DEFAULT_BPM)
            return s0 - (b0 - beat) * (ns - s0) / (nb - b0)
        if i >= len(points):
            b1, s1 = points[-1]
            pb, ps = points[-2] if len(points) > 1 else (b1 - 1, s1 - 60 / DEFAULT_BPM)
            return s1 + (beat - b1) * (s1 - ps) / (b1 - pb)
        (b0, s0), (b1, s1) = points[i - 1], points[i]
        return s0 + (beat - b0) / (b1 - b0) * (s1 - s0)

    return sec


def analyze_midi_events(
    events: Sequence[MidiEvent],
    *,
    ppq: int,
    tempo_changes: Sequence[TempoChange] = (),
    time_signatures: Sequence[TimeSignatureChange] = (),
    **options: Any,
) -> tuple[MidiAnalysis, tuple[str, ...]]:
    """Events to analysis. Returns the analysis and any warnings from note extraction."""
    tempo = TempoMap(ppq, tempo_changes)
    extracted = notes_from_events(events, tempo)
    return analyze_notes(
        extracted.notes, time_signatures=time_signatures, ppq=ppq, **options
    ), extracted.warnings


def chord_at(analysis: MidiAnalysis, beat: float) -> ChordSegment | None:
    """The segment sounding at a beat (for synchronised highlighting)."""
    starts = [s.start_beat for s in analysis.segments]
    i = bisect.bisect_right(starts, beat + 1e-9) - 1
    if i < 0:
        return None
    seg = analysis.segments[i]
    return (
        seg
        if beat < seg.end_beat - 1e-9 or (i == len(starts) - 1 and beat <= seg.end_beat)
        else None
    )


def active_notes_at(notes: Sequence[NoteEvent], beat: float) -> list[NoteEvent]:
    """Notes sounding at a beat, lowest first (for keyboard highlighting)."""
    return sorted(
        (n for n in notes if n.start_beat <= beat + 1e-9 < n.end_beat), key=lambda n: (n.midi, n.id)
    )


# ------------------------------------------------------------------ hands (editable metadata)


@dataclass(frozen=True)
class HandAssignment:
    """Which hand plays each note (by note id). `source` records whether the app guessed or a
    person decided; guesses are suggestions to be corrected, not facts."""

    hands: Mapping[int, Hand]
    source: Mapping[int, Literal["auto", "user"]]

    def with_user_edits(self, edits: Mapping[int, Hand]) -> HandAssignment:
        for note_id, hand in edits.items():
            if note_id not in self.hands:
                raise TheoryError(f"Unknown note id {note_id}", code="unknown_note")
            if hand not in ("L", "R"):
                raise TheoryError("Hand must be 'L' or 'R'", code="invalid_hand")
        return HandAssignment(
            {**self.hands, **edits}, {**self.source, **{i: "user" for i in edits}}
        )  # fmt: skip

    def notes_for(self, notes: Sequence[NoteEvent], hand: Hand) -> list[NoteEvent]:
        return [n for n in notes if self.hands.get(n.id) == hand]


def _clusters(ordered: Sequence[NoteEvent], window: float) -> list[list[NoteEvent]]:
    out: list[list[NoteEvent]] = []
    for n in ordered:
        if out and n.start_beat - out[-1][0].start_beat <= window:
            out[-1].append(n)
        else:
            out.append([n])
    return out


def _by_continuity(
    midi: int, last: Mapping[Hand, Sequence[tuple[int, float]]], start: float
) -> Hand | None:
    """The hand whose recent note (within two beats) is nearest in pitch, if within a fifth."""
    best: tuple[int, Hand] | None = None
    hands: tuple[Hand, Hand] = ("L", "R")
    for hand in hands:
        for m, end in last[hand]:
            if (
                end >= start - 2.0
                and abs(m - midi) <= 7
                and (best is None or abs(m - midi) < best[0])
            ):
                best = (abs(m - midi), hand)
    return best[1] if best else None


def assign_hands(
    notes: Sequence[NoteEvent],
    *,
    split_pitch: int = 60,
    hysteresis: int = 5,
    cluster_window: float = 0.05,
    max_per_hand: int = 5,
) -> HandAssignment:
    """Suggest a hand for every note, using more than absolute pitch.

    Notes starting together form a cluster. Clearly low or high notes (beyond `hysteresis`
    semitones from `split_pitch`) go to the left or right hand; notes near the split follow the
    nearest recent note of either hand; a compact cluster (an octave or less) stays in one hand
    even if it straddles the split, decided by its clearly low/high members; a hand never gets
    more than `max_per_hand` notes at once; and within a cluster the left hand never sits above
    the right. Track numbers are deliberately ignored. These are suggestions to be edited."""
    ordered = sorted(notes, key=lambda n: (n.start_beat, n.midi, n.id))
    hands: dict[int, Hand] = {}
    last: dict[Hand, list[tuple[int, float]]] = {"L": [], "R": []}
    for cluster in _clusters(ordered, cluster_window):
        cluster.sort(key=lambda n: (n.midi, n.id))
        start = cluster[0].start_beat
        clear: dict[int, Hand] = {}
        for n in cluster:
            if n.midi < split_pitch - hysteresis:
                clear[n.id] = "L"
            elif n.midi > split_pitch + hysteresis:
                clear[n.id] = "R"
        guess: dict[int, Hand] = dict(clear)
        for n in cluster:
            if n.id not in guess:
                fallback: Hand = "L" if n.midi < split_pitch else "R"
                guess[n.id] = _by_continuity(n.midi, last, start) or fallback
        if len(cluster) >= 2 and cluster[-1].midi - cluster[0].midi <= 12:
            pool = list(clear.values()) or list(guess.values())
            mean_hand: Hand = (
                "L" if sum(n.midi for n in cluster) / len(cluster) < split_pitch else "R"
            )
            chosen: Hand = max(("L", "R"), key=lambda h: (pool.count(h), h == mean_hand))
            guess = {n.id: chosen for n in cluster}
        n_left = sum(1 for h in guess.values() if h == "L")
        n_left = min(max(n_left, len(cluster) - max_per_hand), max_per_hand)
        crossed, seen_right = False, False
        for n in cluster:
            if guess[n.id] == "R":
                seen_right = True
            elif seen_right:
                crossed = True
        if crossed or n_left != sum(1 for h in guess.values() if h == "L"):
            guess = {n.id: ("L" if k < n_left else "R") for k, n in enumerate(cluster)}
        for n in cluster:
            hands[n.id] = guess[n.id]
            last[guess[n.id]] = [*last[guess[n.id]], (n.midi, n.end_beat)][-8:]
    return HandAssignment(hands, {n.id: "auto" for n in notes})


# ------------------------------------------------------------------ tracks


@dataclass(frozen=True)
class TrackState:
    track: int
    name: str | None = None
    hand: Literal["L", "R", "both", "other"] | None = None  # set by a person, never assumed
    muted: bool = False
    solo: bool = False


def audible_tracks(states: Sequence[TrackState]) -> set[int]:
    """Tracks that should sound: if any track is soloed only soloed (and not muted) tracks do;
    otherwise every track that is not muted."""
    if any(s.solo for s in states):
        return {s.track for s in states if s.solo and not s.muted}
    return {s.track for s in states if not s.muted}


def filter_audible(
    notes: Sequence[NoteEvent], states: Sequence[TrackState],
    assignment: HandAssignment | None = None, *, only_hand: Hand | None = None,
) -> list[NoteEvent]:  # fmt: skip
    """Notes to play after mute/solo, optionally isolating one hand (needs an assignment).
    Tracks with no state entry are treated as audible when nothing is soloed."""
    known = {s.track for s in states}
    audible = audible_tracks(states)
    solo_active = any(s.solo for s in states)
    out = []
    for n in notes:
        if n.track in known:
            if n.track not in audible:
                continue
        elif solo_active:
            continue
        if only_hand is not None:
            if assignment is None:
                raise TheoryError("Isolating a hand needs a hand assignment", code="no_assignment")
            if assignment.hands.get(n.id) != only_hand:
                continue
        out.append(n)
    return out


def merge_tracks(notes: Sequence[NoteEvent], sources: Sequence[int], into: int) -> list[NoteEvent]:
    """Move every note of the `sources` tracks onto track `into`."""
    return [replace(n, track=into) if n.track in sources else n for n in notes]


def split_track_by_pitch(
    notes: Sequence[NoteEvent], track: int, new_track: int, split_pitch: int
) -> list[NoteEvent]:  # fmt: skip
    """Separate one track in two: notes at or above `split_pitch` move to `new_track`."""
    if any(n.track == new_track for n in notes) and new_track != track:
        raise TheoryError(f"Track {new_track} already has notes", code="track_in_use")
    return [
        replace(n, track=new_track) if n.track == track and n.midi >= split_pitch else n
        for n in notes
    ]
