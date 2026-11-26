"""Phrase-level harmonic interpretation.

Splits a chord sequence into phrase candidates and describes each one: the path through
harmonic functions, how it ends, and whether that ending sounds closed, open or interrupted.

Limits (stated in every result): boundaries come from harmony alone. Without melody, rhythm
and lyrics, the real phrase structure may differ, and a plagal or authentic cadence in the middle
of a long phrase is read as a boundary. A single key is assumed; modulations are not followed.
"""

from __future__ import annotations

from dataclasses import dataclass

from music_theory.errors import TheoryError
from music_theory.roman import Cadence, RomanNumeral

_PRIORITY = {"authentic": 0, "plagal": 1, "deceptive": 2, "phrygian half": 3, "half": 4}
_CHARACTER = {
    "authentic": "closed",
    "plagal": "closed",
    "deceptive": "interrupted",
    "half": "open",
    "phrygian half": "open",
}
PHRASE_LIMITATION = (
    "Phrase boundaries are inferred from harmony only. Melody, rhythm and lyrics could place "
    "them differently, and the whole sequence is read in one key."
)


@dataclass(frozen=True)
class Phrase:
    index: int
    start: int  # first chord index
    end: int  # last chord index (inclusive)
    figures: tuple[str, ...]
    function_path: tuple[str, ...]  # consecutive duplicates collapsed
    cadence: str | None
    character: str  # closed | open | interrupted | no cadence
    short: bool  # fewer chords than the minimum phrase length
    duration_beats: float | None
    text: str


def _function(n: RomanNumeral) -> str:
    return n.function or n.category.replace("_", " ")


def _collapse(items: list[str]) -> tuple[str, ...]:
    out: list[str] = []
    for it in items:
        if not out or out[-1] != it:
            out.append(it)
    return tuple(out)


def _describe(
    start: int, end: int, figures: tuple[str, ...], path: tuple[str, ...], cadence: str | None
) -> str:
    span = f"Chords {start + 1}-{end + 1}" if end > start else f"Chord {start + 1}"
    shape = f"stays on {path[0]}" if len(path) == 1 else "moves " + " to ".join(path)
    if cadence is None:
        ending = "has no cadence, so it does not sound finished"
    else:
        ending = {
            "authentic": "ends with an authentic cadence, which sounds closed",
            "plagal": "ends with a plagal cadence, a softer close",
            "deceptive": "ends with a deceptive cadence, which sounds interrupted",
            "half": "ends on the dominant (a half cadence), which sounds open",
            "phrygian half": "ends with a Phrygian half cadence, which sounds open",
        }[cadence]
    return f"{span} ({' '.join(figures)}): {shape} and {ending}."


def segment_phrases(
    numerals: list[RomanNumeral],
    cadences: list[Cadence],
    *,
    durations: list[float] | None = None,
    min_chords: int = 3,
) -> list[Phrase]:
    """Phrase candidates. A cadence closes a phrase when the phrase would hold at least
    `min_chords` chords; a leftover shorter than that becomes its own phrase marked `short`."""
    if min_chords < 1:
        raise TheoryError("min_chords must be at least 1", code="invalid_min_chords")
    if durations is not None and len(durations) != len(numerals):
        raise TheoryError("Give one duration per chord.", code="length_mismatch")
    if not numerals:
        return []
    best: dict[int, Cadence] = {}
    for c in cadences:
        if not 0 <= c.end < len(numerals):
            raise TheoryError("Cadence outside the chord list.", code="invalid_cadence")
        known = best.get(c.end)
        if known is None or _PRIORITY.get(c.kind, 9) < _PRIORITY.get(known.kind, 9):
            best[c.end] = c

    spans: list[tuple[int, int, str | None]] = []
    start = 0
    for end in sorted(best):
        if end - start + 1 >= min_chords:
            spans.append((start, end, best[end].kind))
            start = end + 1
    if start < len(numerals):
        spans.append((start, len(numerals) - 1, None))

    phrases: list[Phrase] = []
    for i, (a, b, cad) in enumerate(spans):
        figures = tuple(n.figure for n in numerals[a : b + 1])
        path = _collapse([_function(n) for n in numerals[a : b + 1]])
        length = b - a + 1
        phrases.append(
            Phrase(
                index=i, start=a, end=b, figures=figures, function_path=path, cadence=cad,
                character=_CHARACTER.get(cad, "no cadence") if cad else "no cadence",
                short=length < min_chords,
                duration_beats=None if durations is None else round(sum(durations[a : b + 1]), 6),
                text=_describe(a, b, figures, path, cad),
            )
        )  # fmt: skip
    return phrases
