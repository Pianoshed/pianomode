"""Interpreting chord estimates that came from audio.

The audio pipeline (chroma features, a chord-recognition model, ...) produces regions with a chord
label and sometimes scores and detected pitches. This module is the interpretation layer: it
parses those labels with the engine's chord definitions, cross-checks them against any pitch
evidence, adds key context and Roman numerals, and keeps manual corrections apart from the
original result.

Principles: an audio estimate is a *hypothesis*, a different type from a chord built from known
MIDI pitches. Raw model scores are never presented as probabilities; `confidence` is only set
when the pipeline names the calibration that was evaluated for it. Ambiguity and weak evidence are
reported, not hidden.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Literal

from music_theory.chord_symbols import ChordSymbolError, parse_chord
from music_theory.chords import Chord
from music_theory.errors import TheoryError
from music_theory.identify import identify_chord
from music_theory.intervals import parse_interval, transpose_name
from music_theory.key_analysis import KeyEstimate, rank_keys_for_chords
from music_theory.keys import Key
from music_theory.notes import NoteName, Preference, parse_note_name, spell_pitch_class
from music_theory.roman import RomanNumeral, analyze_chord


class AudioLabelError(TheoryError):
    code = "unrecognised_chord_label"


class RegionError(TheoryError):
    code = "invalid_regions"


_HARTE_QUALITY = {
    "maj": "", "min": "m", "maj7": "maj7", "min7": "m7", "7": "7", "dim": "dim", "aug": "aug",
    "sus2": "sus2", "sus4": "sus4", "hdim7": "m7b5", "dim7": "dim7", "min6": "m6", "maj6": "6",
    "maj9": "maj9", "min9": "m9", "9": "9", "minmaj7": "mMaj7", "5": "5", "11": "11",
    "min11": "m11", "13": "13", "maj13": "maj13", "min13": "m13",
}  # fmt: skip
_HARTE_DEGREE = {
    "1": "P1", "b2": "m2", "2": "M2", "b3": "m3", "3": "M3", "4": "P4", "#4": "A4", "b5": "d5",
    "5": "P5", "#5": "A5", "b6": "m6", "6": "M6", "b7": "m7", "7": "M7", "9": "M9", "b9": "m9",
    "#9": "A9", "11": "P11", "#11": "A11", "13": "M13", "b13": "m13",
}  # fmt: skip


def parse_audio_label(label: str) -> Chord | None:
    """Parse a chord label from an audio model. Returns None for the "no chord" label `N`.
    Understands Harte syntax (`C:min7`, `Bb:maj/3`) and the engine's own symbols (`Cm7`, `D/F#`).
    Anything else raises `AudioLabelError`; it is never remapped to a different chord."""
    text = label.strip()
    if not text:
        raise AudioLabelError("Empty chord label")
    if text == "N":
        return None
    if ":" in text:
        root_text, rest = text.split(":", 1)
        try:
            root = parse_note_name(root_text)
        except TheoryError as exc:
            raise AudioLabelError(f"Bad root in label {label!r}") from exc
        quality_text, _, bass_degree = rest.partition("/")
        if quality_text not in _HARTE_QUALITY:
            raise AudioLabelError(f"Unsupported chord quality {quality_text!r} in label {label!r}")
        chord = parse_chord(root_text + _HARTE_QUALITY[quality_text])
        if bass_degree:
            if bass_degree not in _HARTE_DEGREE:
                raise AudioLabelError(f"Unsupported bass degree {bass_degree!r} in label {label!r}")
            bass = transpose_name(root, parse_interval(_HARTE_DEGREE[bass_degree]))
            return Chord(chord.root, chord.type, None if bass == root else bass)
        return chord
    try:
        return parse_chord(text)
    except ChordSymbolError as exc:
        raise AudioLabelError(f"Unrecognised chord label {label!r}: {exc.message}") from exc


@dataclass(frozen=True)
class AudioRegion:
    """One stretch of audio as reported by the analysis pipeline (times in seconds)."""

    start: float
    end: float
    label: str
    scores: Mapping[str, float] | None = None  # raw model scores per label; any scale
    bass_pc: int | None = None
    pitch_classes: Sequence[int] | None = None  # pitch classes found in the audio, if known
    probability: float | None = None
    calibration: str | None = None  # name of the evaluated calibration that justifies `probability`


@dataclass(frozen=True)
class Alternative:
    label: str | None
    chord: Chord | None
    source: Literal["model", "pitch_evidence"]
    model_score: float | None = None


@dataclass(frozen=True)
class ChordHypothesis:
    """A chord *estimated from audio* (origin "audio") or set by a person (origin "user")."""

    origin: Literal["audio", "user"]
    start: float
    end: float
    status: Literal["estimated", "ambiguous", "no_chord", "unrecognised_label", "user_set"]
    chord: Chord | None
    raw_label: str
    alternatives: tuple[Alternative, ...] = ()
    model_score: float | None = None  # raw and uncalibrated
    confidence: float | None = None  # only when a calibration is named
    calibration: str | None = None
    bass: NoteName | None = None
    pitch_classes: tuple[int, ...] | None = None
    numeral: RomanNumeral | None = None
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class AudioInterpretation:
    hypotheses: tuple[ChordHypothesis, ...]
    key_estimate: KeyEstimate | None
    key: Key | None
    key_source: Literal["provided", "estimated"] | None
    warnings: tuple[str, ...]


def _validate_times(items: Sequence[tuple[float, float]]) -> None:
    prev_end = 0.0
    for i, (start, end) in enumerate(items):
        if not (math.isfinite(start) and math.isfinite(end)) or start < 0 or end <= start:
            raise RegionError(f"Region {i + 1}: needs 0 <= start < end (seconds)")
        if start < prev_end - 1e-6:
            raise RegionError(f"Region {i + 1} overlaps or precedes the previous region")
        prev_end = end


def _pitch_midis(pcs: Sequence[int], bass_pc: int | None) -> list[int]:
    midis = {60 + p % 12 for p in pcs}
    if bass_pc is not None:
        midis.add(48 + bass_pc % 12)
    return sorted(midis)


def interpret_regions(
    regions: Sequence[AudioRegion],
    *,
    key: Key | None = None,
    min_duration: float = 0.25,
    score_margin: float = 0.1,
    prefer: Preference = "sharps",
) -> AudioInterpretation:
    """Turn pipeline regions into hypotheses with alternatives, warnings and key context."""
    _validate_times([(r.start, r.end) for r in regions])
    hyps: list[ChordHypothesis] = []
    for r in regions:
        hyps.append(_interpret(r, key, min_duration, score_margin, prefer))

    warnings: list[str] = []
    estimate: KeyEstimate | None = None
    used, source = key, ("provided" if key is not None else None)
    chord_hyps = [h for h in hyps if h.chord is not None]
    if used is None and chord_hyps:
        estimate = rank_keys_for_chords(
            [h.chord for h in chord_hyps if h.chord is not None],
            [h.end - h.start for h in chord_hyps],
        )
        if estimate.reliable and estimate.best is not None:
            used, source = estimate.best.key, "estimated"
            if estimate.ambiguous:
                warnings.append(
                    f"The key is uncertain ({used} is one of several close fits); numerals are "
                    "relative to it."
                )
        else:
            warnings.append("Too few chords to estimate a key, so no Roman numerals are given.")
    if used is not None:
        hyps = [
            replace(h, numeral=analyze_chord(h.chord, used)) if h.chord is not None else h
            for h in hyps
        ]
    return AudioInterpretation(tuple(hyps), estimate, used, source, tuple(warnings))  # type: ignore[arg-type]


def _interpret(
    r: AudioRegion, key: Key | None, min_duration: float, margin: float, prefer: Preference
) -> ChordHypothesis:  # fmt: skip
    warnings: list[str] = []
    ambiguous = False
    try:
        chord = parse_audio_label(r.label)
        status: Literal["estimated", "ambiguous", "no_chord", "unrecognised_label"] = (
            "no_chord" if chord is None else "estimated"
        )
    except AudioLabelError as exc:
        chord, status = None, "unrecognised_label"
        warnings.append(exc.message)

    scores = dict(r.scores or {})
    for label, value in scores.items():
        if not math.isfinite(value):
            raise RegionError(f"Score for {label!r} is not a finite number")
    alternatives: list[Alternative] = []
    model_score = scores.get(r.label)
    if scores:
        ranked = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))
        for label, value in ranked:
            if label == r.label:
                continue
            try:
                alt_chord = parse_audio_label(label)
            except AudioLabelError:
                warnings.append(f"Alternative label {label!r} was not understood and was skipped.")
                continue
            alternatives.append(Alternative(label, alt_chord, "model", value))
        top_label, top_value = ranked[0]
        if top_label != r.label:
            warnings.append(
                f"The chosen label {r.label!r} is not the highest-scoring one ({top_label!r})."
            )
            ambiguous = True
        elif model_score is not None and model_score > 0 and len(ranked) > 1:
            runner = ranked[1][1]
            if model_score - runner < margin * model_score:
                warnings.append(
                    f"Close competing label {ranked[1][0]!r}; the raw scores are nearly equal."
                )
                ambiguous = True
    elif r.pitch_classes is None and chord is not None:
        warnings.append(
            "Only a label was provided: no scores or pitches to cross-check it against."
        )

    pcs = None if r.pitch_classes is None else tuple(sorted({p % 12 for p in r.pitch_classes}))
    if pcs is not None and chord is not None:
        ambiguous |= _cross_check(r, chord, pcs, key, prefer, alternatives, warnings)
    elif pcs is not None and len(pcs) < 2:
        warnings.append("Too few detected pitches to cross-check anything.")

    bass: NoteName | None = None
    if r.bass_pc is not None:
        if not 0 <= r.bass_pc <= 11:
            raise RegionError("bass_pc must be 0-11")
        tones = {t.pitch_class: t for t in chord.tones()} if chord is not None else {}
        bass = tones.get(r.bass_pc) or (
            key.signature.spell(r.bass_pc)
            if key is not None
            else spell_pitch_class(r.bass_pc, prefer)
        )
        if chord is not None and r.bass_pc != chord.bass_name.pitch_class:
            if r.bass_pc in tones:
                warnings.append(
                    f"Estimated bass {bass} is not the bass of {chord}; it may be an inversion."
                )
            else:
                warnings.append(
                    f"Estimated bass {bass} is not a tone of {chord}; it may be a slash chord."
                )

    if r.end - r.start < min_duration:
        warnings.append(f"Very short region ({r.end - r.start:.2f}s); the estimate is weak.")

    confidence = None
    if r.probability is not None:
        if r.calibration and 0.0 <= r.probability <= 1.0:
            confidence = r.probability
        else:
            warnings.append(
                "A probability was supplied without a named calibration, so it is not shown "
                "as confidence."
            )
            model_score = r.probability if model_score is None else model_score

    if ambiguous and status == "estimated":
        status = "ambiguous"
    return ChordHypothesis(
        "audio", r.start, r.end, status, chord, r.label, tuple(alternatives), model_score,
        confidence, r.calibration if confidence is not None else None, bass, pcs, None,
        tuple(warnings),
    )  # fmt: skip


def _cross_check(
    r: AudioRegion, chord: Chord, pcs: tuple[int, ...], key: Key | None, prefer: Preference,
    alternatives: list[Alternative], warnings: list[str],
) -> bool:  # fmt: skip
    """Compare the labelled chord with the detected pitches. Returns True if they disagree."""
    tones = {t.pitch_class for t in chord.tones()}
    root = chord.root.pitch_class
    third = next((i for i in chord.type.formula if i.number in (3, 4, 2)), None)
    missing_key = []
    if root not in pcs and chord.type.family != "quartal":
        missing_key.append("root")
    if third is not None and (root + third.semitones) % 12 not in pcs:
        missing_key.append("third")
    if missing_key:
        warnings.append(f"The detected pitches lack the chord's {' and '.join(missing_key)}.")
    bass_hint = r.bass_pc if r.bass_pc is not None else chord.bass_name.pitch_class
    result = identify_chord(_pitch_midis(pcs, bass_hint), key=key, prefer=prefer, max_candidates=3)
    if not result.candidates:
        warnings.append(
            f"The detected pitches are too sparse or unclear to confirm {chord}. "
            f"{result.reason or ''}".strip()
        )
        return False
    same = [
        c
        for c in result.candidates
        if (c.chord.root.pitch_class, c.chord.type.id) == (root, chord.type.id)
    ]
    stray = set(pcs) - tones
    if same and result.candidates[0] in same:
        return False
    for c in result.candidates:
        if c not in same:
            alternatives.append(Alternative(c.symbol, c.chord, "pitch_evidence"))
    best = result.candidates[0]
    if same:
        warnings.append(f"The detected pitches fit {chord} but also read as {best.symbol}.")
    else:
        extra = f" (unexplained pitches: {sorted(stray)})" if stray else ""
        warnings.append(f"The detected pitches suggest {best.symbol} rather than {chord}{extra}.")
    return True


# ------------------------------------------------------------------ manual correction


@dataclass(frozen=True)
class Correction:
    kind: Literal["relabel", "retime", "add", "delete"]
    index: int
    before: ChordHypothesis | None
    after: ChordHypothesis | None


@dataclass(frozen=True)
class CorrectedAnalysis:
    """The original estimate is never overwritten; corrections are recorded beside it."""

    original: tuple[ChordHypothesis, ...]
    current: tuple[ChordHypothesis, ...]
    corrections: tuple[Correction, ...]
    key: Key | None


def start_corrections(interp: AudioInterpretation) -> CorrectedAnalysis:
    return CorrectedAnalysis(interp.hypotheses, interp.hypotheses, (), interp.key)


def _user_hypothesis(start: float, end: float, label: str, key: Key | None) -> ChordHypothesis:
    chord = parse_audio_label(label)  # raises AudioLabelError for labels we cannot understand
    status: Literal["user_set", "no_chord"] = "no_chord" if chord is None else "user_set"
    numeral = analyze_chord(chord, key) if chord is not None and key is not None else None
    return ChordHypothesis("user", start, end, status, chord, label, numeral=numeral)


def _apply(
    ca: CorrectedAnalysis, current: list[ChordHypothesis], c: Correction
) -> CorrectedAnalysis:
    _validate_times([(h.start, h.end) for h in current])
    return replace(ca, current=tuple(current), corrections=(*ca.corrections, c))


def _index(ca: CorrectedAnalysis, index: int) -> ChordHypothesis:
    if not 0 <= index < len(ca.current):
        raise RegionError(f"No region at position {index + 1}")
    return ca.current[index]


def relabel(ca: CorrectedAnalysis, index: int, label: str) -> CorrectedAnalysis:
    """Replace a region's chord. Its times stay; alternatives and scores are dropped because they
    described the old label."""
    before = _index(ca, index)
    after = _user_hypothesis(before.start, before.end, label, ca.key)
    cur = list(ca.current)
    cur[index] = after
    return _apply(ca, cur, Correction("relabel", index, before, after))


def retime(ca: CorrectedAnalysis, index: int, start: float, end: float) -> CorrectedAnalysis:
    before = _index(ca, index)
    after = replace(before, start=start, end=end)
    cur = list(ca.current)
    cur[index] = after
    return _apply(ca, cur, Correction("retime", index, before, after))


def add_region(ca: CorrectedAnalysis, start: float, end: float, label: str) -> CorrectedAnalysis:
    new = _user_hypothesis(start, end, label, ca.key)
    cur = sorted([*ca.current, new], key=lambda h: (h.start, h.end))
    return _apply(ca, cur, Correction("add", cur.index(new), None, new))


def delete_region(ca: CorrectedAnalysis, index: int) -> CorrectedAnalysis:
    before = _index(ca, index)
    cur = list(ca.current)
    del cur[index]
    return _apply(ca, cur, Correction("delete", index, before, None))
