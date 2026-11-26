"""Keys, key signatures and key relationships."""

from __future__ import annotations

from dataclasses import dataclass

from music_theory.errors import TheoryError
from music_theory.intervals import m3, transpose_name
from music_theory.notes import NoteName
from music_theory.scales import Scale, make_scale

# Position of each mode's signature relative to the major scale on the same tonic (in fifths).
MODE_FIFTHS = {
    "major": 0, "ionian": 0, "lydian": 1, "mixolydian": -1, "dorian": -2,
    "minor": -3, "aeolian": -3, "phrygian": -4, "locrian": -5,
}  # fmt: skip
_MODE_SCALE = {"major": "major", "minor": "natural_minor"}
_FIFTHS_OF_LETTER = {"C": 0, "G": 1, "D": 2, "A": 3, "E": 4, "B": 5, "F": -1}
_SHARP_ORDER = ("F", "C", "G", "D", "A", "E", "B")
_FLAT_ORDER = tuple(reversed(_SHARP_ORDER))


@dataclass(frozen=True)
class KeySignature:
    """`fifths` is the number of sharps (positive) or flats (negative)."""

    fifths: int

    @property
    def is_practical(self) -> bool:
        """False for theoretical keys such as G# major, which need double accidentals."""
        return abs(self.fifths) <= 7

    def accidentals(self) -> tuple[NoteName, ...]:
        """Altered notes in signature order (F C G D A E B for sharps). Theoretical keys beyond
        seven sharps/flats put a double accidental on the first letters (G# major: F## C# ...)."""
        n = abs(self.fifths)
        order = _SHARP_ORDER if self.fifths > 0 else _FLAT_ORDER
        sign = 1 if self.fifths > 0 else -1
        return tuple(NoteName(order[i], sign * (2 if i < n - 7 else 1)) for i in range(min(n, 7)))

    def describe(self) -> str:
        if self.fifths == 0:
            return "no sharps or flats"
        kind = "sharp" if self.fifths > 0 else "flat"
        n = abs(self.fifths)
        return f"{n} {kind}{'s' if n != 1 else ''} ({' '.join(str(a) for a in self.accidentals())})"

    def spell(self, pitch_class: int) -> NoteName:
        """Spell a pitch class for this key: diatonic notes as in the key, others with the
        key's accidental direction (sharps in sharp keys, flats in flat keys)."""
        altered = {a.letter: a.accidental for a in self.accidentals()}
        for letter in "CDEFGAB":
            name = NoteName(letter, altered.get(letter, 0))
            if name.pitch_class == pitch_class % 12:
                return name
        from music_theory.notes import spell_pitch_class

        return spell_pitch_class(pitch_class, "sharps" if self.fifths >= 0 else "flats")


def key_signature(tonic: NoteName, mode: str = "major") -> KeySignature:
    offset = MODE_FIFTHS.get(mode.lower())
    if offset is None:
        raise TheoryError(f"Unknown mode {mode!r}", code="unknown_mode")
    return KeySignature(_FIFTHS_OF_LETTER[tonic.letter] + 7 * tonic.accidental + offset)


@dataclass(frozen=True)
class Key:
    tonic: NoteName
    mode: str = "major"  # "major" or "minor"

    def __post_init__(self) -> None:
        if self.mode not in _MODE_SCALE:
            raise TheoryError("Key mode must be 'major' or 'minor'", code="unknown_mode")

    @property
    def signature(self) -> KeySignature:
        return key_signature(self.tonic, self.mode)

    def scale(self) -> Scale:
        return make_scale(self.tonic, _MODE_SCALE[self.mode])

    def diatonic_pitch_classes(self) -> frozenset[int]:
        """Pitch classes of the key. Minor includes the raised seventh, so V and vii° count."""
        semis = (0, 2, 4, 5, 7, 9, 11) if self.mode == "major" else (0, 2, 3, 5, 7, 8, 10, 11)
        return frozenset((self.tonic.pitch_class + s) % 12 for s in semis)

    def relative(self) -> Key:
        """C major <-> A minor."""
        if self.mode == "major":
            return Key(transpose_name(self.tonic, m3, down=True), "minor")
        return Key(transpose_name(self.tonic, m3), "major")

    def parallel(self) -> Key:
        """C major <-> C minor."""
        return Key(self.tonic, "minor" if self.mode == "major" else "major")

    def __str__(self) -> str:
        return f"{self.tonic} {self.mode}"
