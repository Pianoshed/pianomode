"""Input limits and parsing helpers shared by every caller of the engine (API, workers, tools).

Limits exist because several operations are combinatorial (voicing generation and sequence
search) and because requests come from the network. They are deliberately generous for a
learner and a lesson author and are enforced here, not only in the HTTP layer, so a background
job cannot bypass them by accident.
"""

from __future__ import annotations

import math
import re
from typing import Final

from music_theory.errors import TheoryError
from music_theory.keys import Key
from music_theory.notes import Note, NoteName, parse_note, parse_note_name

MAX_NOTES: Final = 24  # notes in one chord-identification request
MAX_SYMBOL_LENGTH: Final = 40
MAX_PROGRESSION_CHORDS: Final = 64  # chords in a progression that is transposed or validated
MAX_VOICED_CHORDS: Final = 16  # chords in one voice-leading search (about 2 s at 16 jazz chords)
MAX_CANDIDATES: Final = 80  # voicing candidates kept per chord in a sequence search
MAX_VOICING_RESULTS: Final = 200
MAX_MIDI_EVENTS: Final = 20_000  # about 10,000 notes; longer files belong in a background job
MAX_AUDIO_REGIONS: Final = 2_000
MAX_CORRECTIONS: Final = 200

_OCTAVE_RE = re.compile(r"-?\d+$")


def check_count(label: str, count: int, limit: int, *, minimum: int = 1) -> None:
    """Reject too few or too many items with a stable code."""
    if count < minimum:
        raise TheoryError(f"Give at least {minimum} {label}.", code="too_few_items")
    if count > limit:
        raise TheoryError(
            f"Too many {label}: {count} given, at most {limit} allowed.", code="too_many_items"
        )


def check_finite(label: str, value: float) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        raise TheoryError(f"{label} must be a finite number.", code="invalid_number")
    return float(value)


def parse_key(tonic: str, mode: str = "major") -> Key:
    """A key from text. The mode must be 'major' or 'minor' (checked by `Key`)."""
    if not isinstance(tonic, str) or not tonic.strip():
        raise TheoryError("A key needs a tonic note such as C or Eb.", code="invalid_note")
    return Key(parse_note_name(tonic.strip()), mode)


def has_octave(text: str) -> bool:
    return bool(_OCTAVE_RE.search(text.strip()))


def parse_note_or_name(text: str, *, middle_c_octave: int = 4) -> Note | NoteName:
    """`C#4` gives a `Note`; `C#` gives a `NoteName`."""
    text = text.strip()
    if has_octave(text):
        return parse_note(text, middle_c_octave=middle_c_octave)
    return parse_note_name(text)


def check_midi_range(notes: list[int], label: str = "MIDI notes") -> list[int]:
    for n in notes:
        if isinstance(n, bool) or not isinstance(n, int) or not 0 <= n <= 127:
            raise TheoryError(f"{label} must be integers from 0 to 127.", code="invalid_midi_note")
    return notes
