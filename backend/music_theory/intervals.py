"""Intervals: quality + number, with correct spelling when transposing notes."""

from __future__ import annotations

import re
from dataclasses import dataclass

from music_theory.errors import TheoryError
from music_theory.notes import (
    LETTER_PC,
    LETTERS,
    Note,
    NoteName,
    note_with_spelling,
)

_BASE = {1: 0, 2: 2, 3: 4, 4: 5, 5: 7, 6: 9, 7: 11, 8: 12}  # major / perfect size by simple number
_PERFECT = {1, 4, 5, 8}
_ORDINALS = {
    1: "unison", 2: "second", 3: "third", 4: "fourth", 5: "fifth", 6: "sixth", 7: "seventh",
    8: "octave", 9: "ninth", 10: "tenth", 11: "eleventh", 12: "twelfth", 13: "thirteenth",
    14: "fourteenth", 15: "fifteenth",
}  # fmt: skip
_QUALITY_WORDS = {"P": "perfect", "M": "major", "m": "minor", "A": "augmented", "d": "diminished"}
_INTERVAL_RE = re.compile(r"^(P|M|m|A+|d+)(\d+)$")


def _simple_number(number: int) -> int:
    return number if number <= 8 else ((number - 2) % 7) + 2


@dataclass(frozen=True)
class Interval:
    """`number` counts letter names (third = 3). `semitones` is the sounding size."""

    number: int
    semitones: int

    def __post_init__(self) -> None:
        if self.number < 1 or self.semitones < 0:
            raise TheoryError("Interval must be at least a unison", code="invalid_interval")
        if abs(self._delta) > 3:
            raise TheoryError(
                f"{self.semitones} semitones is not a valid size for a {self.number}",
                code="invalid_interval",
            )

    @property
    def simple_number(self) -> int:
        return _simple_number(self.number)

    @property
    def _octaves(self) -> int:
        return (self.number - self.simple_number) // 7

    @property
    def simple_semitones(self) -> int:
        return self.semitones - 12 * self._octaves

    @property
    def _delta(self) -> int:
        return self.simple_semitones - _BASE[self.simple_number]

    @property
    def is_compound(self) -> bool:
        return self.number > 8

    @property
    def whole_tones(self) -> float:
        return self.semitones / 2

    @property
    def quality(self) -> str:
        d = self._delta
        if self.simple_number in _PERFECT:
            return "P" if d == 0 else ("A" * d if d > 0 else "d" * -d)
        if d == 0:
            return "M"
        if d == -1:
            return "m"
        return "A" * d if d > 0 else "d" * (-d - 1)

    @property
    def short(self) -> str:
        return f"{self.quality}{self.number}"

    @property
    def long(self) -> str:
        q = self.quality
        if q in _QUALITY_WORDS:
            word = _QUALITY_WORDS[q]
        elif q[0] == "A":
            word = {2: "doubly", 3: "triply"}.get(len(q), "multiply") + " augmented"
        else:
            word = {2: "doubly", 3: "triply"}.get(len(q), "multiply") + " diminished"
        ordinal = _ORDINALS.get(self.number, f"{self.number}th")
        return f"{word} {ordinal}"

    def simple(self) -> Interval:
        return Interval(self.simple_number, self.simple_semitones)

    def inverted(self) -> Interval:
        """Inversion within one octave. Compound intervals are reduced first."""
        s, semis = self.simple_number, self.simple_semitones
        number = 8 if s == 1 else 1 if s == 8 else 9 - s
        return Interval(number, 12 - semis)

    def describe(self) -> str:
        return f"{self.short} ({self.long}, {self.semitones} semitones)"

    @staticmethod
    def of(quality: str, number: int) -> Interval:
        if number < 1:
            raise TheoryError("Interval number must be at least 1", code="invalid_interval")
        simple = _simple_number(number)
        octaves = (number - simple) // 7
        count = len(quality)
        if simple in _PERFECT:
            if quality == "P":
                delta = 0
            elif set(quality) == {"A"}:
                delta = count
            elif set(quality) == {"d"}:
                delta = -count
            else:
                raise TheoryError(
                    f"{quality}{number} does not exist: a {_ORDINALS.get(number, number)} "
                    "is perfect, augmented or diminished",
                    code="invalid_interval",
                )
        elif quality == "M":
            delta = 0
        elif quality == "m":
            delta = -1
        elif set(quality) == {"A"}:
            delta = count
        elif set(quality) == {"d"}:
            delta = -count - 1
        else:
            raise TheoryError(
                f"{quality}{number} does not exist: a {_ORDINALS.get(number, number)} "
                "is major, minor, augmented or diminished",
                code="invalid_interval",
            )
        return Interval(number, _BASE[simple] + delta + 12 * octaves)


def parse_interval(text: str) -> Interval:
    m = _INTERVAL_RE.match(text.strip())
    if m is None:
        raise TheoryError(f"Not an interval: {text!r}", code="invalid_interval")
    return Interval.of(m.group(1), int(m.group(2)))


def intervals(*symbols: str) -> tuple[Interval, ...]:
    return tuple(parse_interval(s) for s in symbols)


P1, m2, M2, m3, M3, P4, A4, d5, P5, m6, M6, m7, M7, P8 = intervals(
    "P1", "m2", "M2", "m3", "M3", "P4", "A4", "d5", "P5", "m6", "M6", "m7", "M7", "P8"
)
SIMPLE_INTERVALS = (P1, m2, M2, m3, M3, P4, A4, d5, P5, m6, M6, m7, M7, P8)


def transpose_name(name: NoteName, interval: Interval, *, down: bool = False) -> NoteName:
    """Spell the note an interval above (or below) `name`: C + M3 = E, C + d4 = Fb."""
    step = interval.number - 1
    idx = (name.letter_index + (-step if down else step)) % 7
    letter = LETTERS[idx]
    shift = -interval.semitones if down else interval.semitones
    target = (name.pitch_class + shift) % 12
    accidental = ((target - LETTER_PC[letter] + 6) % 12) - 6
    return NoteName(letter, accidental)


def transpose_note(note: Note, interval: Interval, *, down: bool = False) -> Note:
    name = transpose_name(note.name, interval, down=down)
    midi = note.midi + (-interval.semitones if down else interval.semitones)
    return note_with_spelling(midi, name)


def interval_between_names(lower: NoteName, upper: NoteName) -> Interval:
    """Interval going up from `lower` to the next `upper` within an octave (C to C is P1)."""
    number = (upper.letter_index - lower.letter_index) % 7 + 1
    semis = (upper.pitch_class - lower.pitch_class) % 12
    if number == 1:  # C-C#, or C up to Cb which is a diminished octave
        return Interval(1, semis) if semis <= 6 else Interval(8, semis)
    delta = semis - _BASE[number]
    if delta > 6:
        semis -= 12
    elif delta < -6:
        semis += 12
    return Interval(number, semis)


def interval_between_notes(a: Note, b: Note) -> Interval:
    """Size of the interval between two notes, whichever is higher."""
    lo, hi = sorted((a, b), key=lambda n: (n.midi, n.diatonic_position))
    return Interval(hi.diatonic_position - lo.diatonic_position + 1, hi.midi - lo.midi)


def signed_semitones(a: Note, b: Note) -> int:
    return b.midi - a.midi


def interval_class(pc_a: int, pc_b: int) -> int:
    """Shortest distance between two pitch classes, 0-6."""
    d = (pc_b - pc_a) % 12
    return min(d, 12 - d)
