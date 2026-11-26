"""Key estimation. Every result is an estimate with alternatives, never a certainty.

Two methods, both heuristic:
- `estimate_key`: Krumhansl-Schmuckler. Correlates a pitch-class weight profile with the
  Krumhansl-Kessler major/minor profiles. Scores are correlations (-1..1), not probabilities.
- `rank_keys_for_chords`: how many chords are diatonic to each key, plus small bonuses for a
  tonic chord at the start/end. Cannot separate relative major/minor on its own.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from music_theory.chords import Chord
from music_theory.errors import TheoryError
from music_theory.keys import Key
from music_theory.notes import parse_note_name

KK_MAJOR = (6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88)
KK_MINOR = (6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17)
# Conventional key names: fewest accidentals, F# major over Gb, Eb minor over D# minor.
MAJOR_TONICS = ("C", "Db", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B")
MINOR_TONICS = ("C", "C#", "D", "Eb", "E", "F", "F#", "G", "G#", "A", "Bb", "B")
ALL_KEYS = tuple(
    [Key(parse_note_name(t), "major") for t in MAJOR_TONICS]
    + [Key(parse_note_name(t), "minor") for t in MINOR_TONICS]
)

MIN_FIT = 0.4  # below this correlation the fit is called weak (uncalibrated threshold)


@dataclass(frozen=True)
class KeyCandidate:
    key: Key
    score: float  # correlation or fit score; for ranking only


@dataclass(frozen=True)
class KeyEstimate:
    candidates: tuple[KeyCandidate, ...]  # best first
    reliable: bool
    ambiguous: bool
    warnings: tuple[str, ...]
    method: str

    @property
    def best(self) -> KeyCandidate | None:
        return self.candidates[0] if self.candidates else None


def _pearson(x: Sequence[float], y: Sequence[float]) -> float | None:
    n = len(x)
    mx, my = sum(x) / n, sum(y) / n
    sxx = sum((a - mx) ** 2 for a in x)
    syy = sum((b - my) ** 2 for b in y)
    if sxx == 0 or syy == 0:
        return None
    sxy = sum((a - mx) * (b - my) for a, b in zip(x, y, strict=True))
    return sxy / math.sqrt(sxx * syy)


def _rotate(profile: Sequence[float], tonic_pc: int) -> list[float]:
    return [profile[(pc - tonic_pc) % 12] for pc in range(12)]


def weights_from_midi(events: Iterable[tuple[int, float]]) -> list[float]:
    """Pitch-class weights from (midi, duration) pairs."""
    w = [0.0] * 12
    for midi, duration in events:
        if duration < 0 or not math.isfinite(duration):
            raise TheoryError("Durations must be non-negative numbers", code="invalid_duration")
        w[midi % 12] += duration
    return w


def weights_from_chords(
    chords: Sequence[Chord], durations: Sequence[float] | None = None
) -> list[float]:
    """Root counts double, other chord tones once, scaled by duration."""
    if durations is not None and len(durations) != len(chords):
        raise TheoryError("One duration per chord", code="invalid_duration")
    w = [0.0] * 12
    for i, chord in enumerate(chords):
        d = 1.0 if durations is None else durations[i]
        for j, pc in enumerate(chord.pitch_classes()):
            w[pc] += d * (2.0 if j == 0 else 1.0)
    return w


def _finish(
    scored: list[KeyCandidate], top: int, margin: float, reliable: bool, method: str,
    warnings: list[str],
) -> KeyEstimate:  # fmt: skip
    scored.sort(key=lambda c: (-c.score, c.key.mode != "major", c.key.tonic.pitch_class))
    best = scored[:top]
    ambiguous = len(best) > 1 and best[0].score - best[1].score < margin
    if ambiguous:
        a, b = best[0].key, best[1].key
        if a.relative() == b:
            warnings.append(f"{a} and its relative key {b} fit almost equally well.")
        else:
            warnings.append("Several keys fit almost equally well.")
    if best and best[0].score < MIN_FIT and method == "krumhansl-schmuckler":
        warnings.append(
            "Even the best key fits weakly; the music may be modal, chromatic or atonal."
        )
    return KeyEstimate(tuple(best), reliable, ambiguous, tuple(warnings), method)


def estimate_key(
    weights: Sequence[float], *, top: int = 5, ambiguity_margin: float = 0.05
) -> KeyEstimate:
    if len(weights) != 12 or any(w < 0 or not math.isfinite(w) for w in weights):
        raise TheoryError("Need 12 non-negative pitch-class weights", code="invalid_weights")
    method = "krumhansl-schmuckler"
    distinct = sum(1 for w in weights if w > 0)
    scored = []
    for key in ALL_KEYS:
        profile = KK_MAJOR if key.mode == "major" else KK_MINOR
        r = _pearson(weights, _rotate(profile, key.tonic.pitch_class))
        if r is None:
            return KeyEstimate((), False, False, ("No usable pitch information.",), method)
        scored.append(KeyCandidate(key, round(r, 4)))
    warnings: list[str] = []
    reliable = distinct >= 3
    if not reliable:
        warnings.append("Fewer than three distinct pitch classes: too little evidence for a key.")
    return _finish(scored, top, ambiguity_margin, reliable, method, warnings)


def _is_tonic_chord(chord: Chord, key: Key) -> bool:
    if chord.root.pitch_class != key.tonic.pitch_class:
        return False
    third = next((i for i in chord.type.formula if i.number == 3), None)
    if third is None:
        return False
    return third.semitones == (4 if key.mode == "major" else 3)


def rank_keys_for_chords(
    chords: Sequence[Chord],
    durations: Sequence[float] | None = None,
    *,
    top: int = 5,
    ambiguity_margin: float = 0.1,
) -> KeyEstimate:
    method = "diatonic-fit"
    if not chords:
        return KeyEstimate((), False, False, ("No chords given.",), method)
    ks_weights = weights_from_chords(chords, durations)
    scored = []
    for key in ALL_KEYS:
        pcs = key.diatonic_pitch_classes()
        fit = sum(1 for c in chords if set(c.pitch_classes()) <= pcs) / len(chords)
        score = fit
        score += 0.1 if _is_tonic_chord(chords[0], key) else 0.0
        score += 0.15 if _is_tonic_chord(chords[-1], key) else 0.0
        profile = KK_MAJOR if key.mode == "major" else KK_MINOR
        r = _pearson(ks_weights, _rotate(profile, key.tonic.pitch_class))
        score += 0.1 * (r or 0.0)
        scored.append(KeyCandidate(key, round(score, 4)))
    warnings = ["Chord-only analysis cannot fully separate a key from its relative key."]
    return _finish(scored, top, ambiguity_margin, len(chords) >= 3, method, warnings)


@dataclass(frozen=True)
class ModulationCandidate:
    index: int  # first chord of the window where the new key becomes the best fit
    from_key: Key
    to_key: Key
    note: str


def detect_modulations(chords: Sequence[Chord], *, window: int = 4) -> list[ModulationCandidate]:
    """Candidate key changes: where the best-fitting key of a sliding window changes and stays.
    Boundaries are approximate (within one window) and every result is only a candidate."""
    if window < 3:
        raise TheoryError("Window must be at least 3 chords", code="invalid_window")
    if len(chords) < window + 1:
        return []
    best: list[Key | None] = []
    for i in range(len(chords) - window + 1):
        est = rank_keys_for_chords(chords[i : i + window])
        best.append(est.best.key if est.best and not est.ambiguous else None)
    out: list[ModulationCandidate] = []
    current = next((k for k in best if k is not None), None)
    for i, k in enumerate(best):
        if k is None or current is None or k == current:
            continue
        if i + 1 < len(best) and best[i + 1] != k:
            continue  # one-window blip, not a lasting change
        out.append(
            ModulationCandidate(
                i, current, k, "Best-fitting key changed; boundary is approximate (+/- one window)."
            )
        )
        current = k
    return out
