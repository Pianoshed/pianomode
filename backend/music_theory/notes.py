"""Notes, pitch classes, MIDI numbers and frequencies.

Sounding pitch is an integer MIDI number (60 = middle C). Spelling (C# vs Db, E# vs F) is kept
separately in `NoteName`, so B#3 and C4 are the same sounding pitch but different notes.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Literal

from music_theory.errors import TheoryError

LETTERS = ("C", "D", "E", "F", "G", "A", "B")
LETTER_PC = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
MIDI_MIN, MIDI_MAX = 0, 127
PIANO_MIN, PIANO_MAX = 21, 108  # A0 .. C8

SHARP_NAMES = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")
FLAT_NAMES = ("C", "Db", "D", "Eb", "E", "F", "Gb", "G", "Ab", "A", "Bb", "B")

Preference = Literal["sharps", "flats"]

_ASCII = {2: "##", 1: "#", 0: "", -1: "b", -2: "bb"}
_UNICODE = {2: "\U0001d12a", 1: "♯", 0: "", -1: "♭", -2: "\U0001d12b"}
_ACCIDENTAL_VALUES = {
    "##": 2, "#": 1, "bb": -2, "b": -1, "x": 2, "♯♯": 2, "♯": 1, "♭♭": -2, "♭": -1,
    "\U0001d12a": 2, "\U0001d12b": -2,
}  # fmt: skip
_NOTE_RE = re.compile(r"^([A-G])(##|#|bb|b|x|♯♯|♯|♭♭|♭|\U0001d12a|\U0001d12b)?(-?\d+)?$")


@dataclass(frozen=True)
class NoteName:
    """A spelled pitch class such as C, F#, Bb or E## (no octave)."""

    letter: str
    accidental: int = 0

    def __post_init__(self) -> None:
        if self.letter not in LETTER_PC:
            raise TheoryError(f"Invalid note letter {self.letter!r}", code="invalid_note")
        if not -2 <= self.accidental <= 2:
            raise TheoryError(
                "Only up to two sharps or flats are supported; use the enharmonic spelling",
                code="spelling_overflow",
            )

    @property
    def pitch_class(self) -> int:
        return (LETTER_PC[self.letter] + self.accidental) % 12

    @property
    def letter_index(self) -> int:
        return LETTERS.index(self.letter)

    def format(self, *, unicode: bool = False) -> str:
        return self.letter + (_UNICODE if unicode else _ASCII)[self.accidental]

    def __str__(self) -> str:
        return self.format()


@dataclass(frozen=True)
class Note:
    """A spelled, sounding note: name plus scientific-pitch octave (C4 = MIDI 60)."""

    name: NoteName
    octave: int

    @property
    def midi(self) -> int:
        return 12 * (self.octave + 1) + LETTER_PC[self.name.letter] + self.name.accidental

    @property
    def pitch_class(self) -> int:
        return self.name.pitch_class

    @property
    def diatonic_position(self) -> int:
        """Letter-steps from C0; used for interval numbers (C4 to E5 spans a tenth)."""
        return self.octave * 7 + self.name.letter_index

    def frequency(self, a4: float = 440.0) -> float:
        return midi_to_frequency(self.midi, a4)

    def format(self, *, unicode: bool = False, middle_c_octave: int = 4) -> str:
        shown = self.octave + (middle_c_octave - 4)
        return f"{self.name.format(unicode=unicode)}{shown}"

    def __str__(self) -> str:
        return self.format()


def check_midi(midi: int) -> int:
    if not isinstance(midi, int) or isinstance(midi, bool) or not MIDI_MIN <= midi <= MIDI_MAX:
        raise TheoryError(f"MIDI note must be an integer 0-127, got {midi!r}", code="invalid_midi")
    return midi


def parse_note_name(text: str) -> NoteName:
    m = _NOTE_RE.match(text.strip())
    if m is None or m.group(3) is not None:
        raise TheoryError(f"Not a note name: {text!r}", code="invalid_note")
    return NoteName(m.group(1), _ACCIDENTAL_VALUES.get(m.group(2) or "", 0))


def parse_note(text: str, *, middle_c_octave: int = 4) -> Note:
    """Parse e.g. 'C4', 'Bb2', 'F#-1', 'E##3'. `middle_c_octave` sets the octave-number convention
    (4 = scientific pitch / MIDI 60 is C4; 3 = common in Yamaha-style labelling)."""
    m = _NOTE_RE.match(text.strip())
    if m is None or m.group(3) is None:
        raise TheoryError(f"Not a note with octave: {text!r}", code="invalid_note")
    name = NoteName(m.group(1), _ACCIDENTAL_VALUES.get(m.group(2) or "", 0))
    return Note(name, int(m.group(3)) - (middle_c_octave - 4))


def spell_pitch_class(pc: int, prefer: Preference = "sharps") -> NoteName:
    table = SHARP_NAMES if prefer == "sharps" else FLAT_NAMES
    return parse_note_name(table[pc % 12])


def note_with_spelling(midi: int, name: NoteName) -> Note:
    """The note with this exact spelling that sounds at `midi` (e.g. 60 + B# -> B#3)."""
    if (midi - name.pitch_class) % 12 != 0:
        raise TheoryError(f"{name} cannot sound at MIDI {midi}", code="spelling_mismatch")
    octave = (midi - name.accidental - LETTER_PC[name.letter]) // 12 - 1
    return Note(name, octave)


def note_from_midi(midi: int, prefer: Preference = "sharps") -> Note:
    check_midi(midi)
    return note_with_spelling(midi, spell_pitch_class(midi % 12, prefer))


def is_enharmonic(a: NoteName | Note, b: NoteName | Note) -> bool:
    """Same sounding pitch class (and same pitch, when both have octaves)."""
    if isinstance(a, Note) and isinstance(b, Note):
        return a.midi == b.midi
    return a.pitch_class == b.pitch_class


def midi_to_frequency(midi: float, a4: float = 440.0) -> float:
    if a4 <= 0:
        raise TheoryError("Tuning reference must be positive", code="invalid_tuning")
    return float(a4 * 2.0 ** ((midi - 69) / 12))


def frequency_to_midi(frequency: float, a4: float = 440.0) -> tuple[int, float]:
    """Nearest MIDI note and the deviation from it in cents (-50..+50]."""
    if frequency <= 0 or not math.isfinite(frequency):
        raise TheoryError("Frequency must be a positive number", code="invalid_frequency")
    if a4 <= 0:
        raise TheoryError("Tuning reference must be positive", code="invalid_tuning")
    exact = 69 + 12 * math.log2(frequency / a4)
    nearest = round(exact)
    check_midi(nearest)
    return nearest, (exact - nearest) * 100


def frequency_to_note(
    frequency: float, a4: float = 440.0, prefer: Preference = "sharps"
) -> tuple[Note, float]:
    midi, cents = frequency_to_midi(frequency, a4)
    return note_from_midi(midi, prefer), cents
