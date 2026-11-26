"""Harmony built on scales: diatonic chords (Roman-numeral analysis is added later)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from music_theory.chords import Chord, find_chord_type
from music_theory.errors import TheoryError
from music_theory.intervals import Interval, interval_between_names
from music_theory.notes import NoteName
from music_theory.scales import Scale


@dataclass(frozen=True)
class DiatonicChord:
    degree: int
    tones: tuple[NoteName, ...]
    intervals: tuple[Interval, ...]
    chord: Chord | None  # None when the stacked thirds form no supported chord type


def diatonic_chords(scale: Scale, size: Literal[3, 4] = 3) -> list[DiatonicChord]:
    """Chords built by stacking thirds on each degree of a seven-note scale."""
    notes = scale.notes()
    if len(notes) != 7:
        raise TheoryError("Diatonic chords need a seven-note scale", code="not_heptatonic")
    result = []
    for i in range(7):
        tones = tuple(notes[(i + 2 * k) % 7] for k in range(size))
        ivs = tuple(interval_between_names(tones[0], t) for t in tones)
        found = find_chord_type(ivs)
        chord = Chord(tones[0], found) if found is not None else None
        result.append(DiatonicChord(i + 1, tones, ivs, chord))
    return result
