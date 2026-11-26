"""Chord types (explicit interval formulas) and chords with spelling, inversions and voicing."""

from __future__ import annotations

from dataclasses import dataclass
from itertools import product

from music_theory.errors import TheoryError
from music_theory.intervals import (
    Interval,
    intervals,
    transpose_name,
    transpose_note,
)
from music_theory.notes import Note, NoteName, note_with_spelling, parse_note_name


@dataclass(frozen=True)
class ChordType:
    """`formula` lists every tone above (and including) the root. `omissible` tones may be left
    out in a real voicing without changing the chord's identity (e.g. the fifth of a 9th chord)."""

    id: str
    name: str
    symbol: str
    formula: tuple[Interval, ...]
    aliases: tuple[str, ...] = ()
    family: str = "tertian"
    omissible: tuple[Interval, ...] = ()

    @property
    def size(self) -> int:
        return len(self.formula)


_MINOR = ("m", "min", "-", "mi")
_MAJ = ("maj", "Maj", "M", "Δ", "△", "ma")


def _t(
    id: str,
    name: str,
    symbol: str,
    formula: str,
    *,
    aliases: tuple[str, ...] = (),
    family: str = "tertian",
    omit: str = "",
) -> ChordType:
    return ChordType(
        id, name, symbol, intervals(*formula.split()), aliases, family, intervals(*omit.split())
    )


def _minor(rest: str) -> tuple[str, ...]:
    return tuple(p + rest for p in _MINOR)


def _major(rest: str) -> tuple[str, ...]:
    return tuple(m + rest for m in _MAJ)


def _minor_major(rest: str) -> tuple[str, ...]:
    return tuple(p + m + rest for p, m in product(_MINOR, _MAJ))


_ALL_TYPES = (
    _t("major", "Major triad", "", "P1 M3 P5"),
    _t("minor", "Minor triad", "m", "P1 m3 P5", aliases=_minor("")),
    _t("diminished", "Diminished triad", "dim", "P1 m3 d5", aliases=("°", "o")),
    _t("augmented", "Augmented triad", "aug", "P1 M3 A5", aliases=("+",)),
    _t("sus2", "Suspended second", "sus2", "P1 M2 P5"),
    _t("sus4", "Suspended fourth", "sus4", "P1 P4 P5", aliases=("sus",)),
    _t("power", "Power chord", "5", "P1 P5", family="dyad"),
    _t("major6", "Major sixth", "6", "P1 M3 P5 M6", aliases=("maj6", "M6"), omit="P5"),
    _t("minor6", "Minor sixth", "m6", "P1 m3 P5 M6", aliases=_minor("6"), omit="P5"),
    _t("six_nine", "Six-nine", "6/9", "P1 M3 P5 M6 M9", aliases=("69", "6add9"), omit="P5"),
    _t(
        "major7",
        "Major seventh",
        "maj7",
        "P1 M3 P5 M7",
        aliases=_major("7") + ("Δ", "△"),
        omit="P5",
    ),
    _t("minor7", "Minor seventh", "m7", "P1 m3 P5 m7", aliases=_minor("7"), omit="P5"),
    _t("dominant7", "Dominant seventh", "7", "P1 M3 P5 m7", aliases=("dom7",), omit="P5"),
    _t(
        "minor_major7",
        "Minor-major seventh",
        "mMaj7",
        "P1 m3 P5 M7",
        aliases=_minor_major("7"),
        omit="P5",
    ),
    _t(
        "half_diminished7",
        "Half-diminished seventh (minor seventh flat five)",
        "m7b5",
        "P1 m3 d5 m7",
        aliases=("ø", "ø7", *_minor("7b5")),
    ),
    _t("diminished7", "Fully diminished seventh", "dim7", "P1 m3 d5 d7", aliases=("°7", "o7")),
    _t("dominant7_flat5", "Dominant seventh flat five", "7b5", "P1 M3 d5 m7", aliases=("7-5",)),
    _t(
        "dominant7_sharp5",
        "Dominant seventh sharp five",
        "7#5",
        "P1 M3 A5 m7",
        aliases=("+7", "aug7", "7+5"),
    ),
    _t(
        "major7_sharp5",
        "Major seventh sharp five",
        "maj7#5",
        "P1 M3 A5 M7",
        aliases=_major("7#5") + ("+maj7", "augmaj7"),
    ),
    _t("major7_flat5", "Major seventh flat five", "maj7b5", "P1 M3 d5 M7", aliases=_major("7b5")),
    _t(
        "dominant7_sus4",
        "Dominant seventh suspended fourth",
        "7sus4",
        "P1 P4 P5 m7",
        aliases=("7sus",),
        omit="P5",
    ),
    _t("add9", "Add nine", "add9", "P1 M3 P5 M9"),
    _t("minor_add9", "Minor add nine", "madd9", "P1 m3 P5 M9", aliases=_minor("add9")),
    _t("add11", "Add eleven", "add11", "P1 M3 P5 P11", aliases=("add4",)),
    _t(
        "minor_add11",
        "Minor add eleven",
        "madd11",
        "P1 m3 P5 P11",
        aliases=_minor("add11") + _minor("add4"),
    ),
    _t("dominant9", "Dominant ninth", "9", "P1 M3 P5 m7 M9", omit="P5"),
    _t("major9", "Major ninth", "maj9", "P1 M3 P5 M7 M9", aliases=_major("9"), omit="P5"),
    _t("minor9", "Minor ninth", "m9", "P1 m3 P5 m7 M9", aliases=_minor("9"), omit="P5"),
    _t(
        "minor_major9",
        "Minor-major ninth",
        "mMaj9",
        "P1 m3 P5 M7 M9",
        aliases=_minor_major("9"),
        omit="P5",
    ),
    _t("dominant11", "Dominant eleventh", "11", "P1 M3 P5 m7 M9 P11", omit="P5 M9"),
    _t(
        "minor11", "Minor eleventh", "m11", "P1 m3 P5 m7 M9 P11", aliases=_minor("11"), omit="P5 M9"
    ),
    _t(
        "major11",
        "Major eleventh",
        "maj11",
        "P1 M3 P5 M7 M9 P11",
        aliases=_major("11"),
        omit="P5 M9",
    ),
    _t("dominant13", "Dominant thirteenth", "13", "P1 M3 P5 m7 M9 M13", omit="P5 M9"),
    _t(
        "major13",
        "Major thirteenth",
        "maj13",
        "P1 M3 P5 M7 M9 M13",
        aliases=_major("13"),
        omit="P5 M9",
    ),
    _t(
        "minor13",
        "Minor thirteenth",
        "m13",
        "P1 m3 P5 m7 M9 M13",
        aliases=_minor("13"),
        omit="P5 M9",
    ),
    _t(
        "dominant7_flat9",
        "Dominant seventh flat nine",
        "7b9",
        "P1 M3 P5 m7 m9",
        aliases=("7-9",),
        omit="P5",
    ),
    _t(
        "dominant7_sharp9",
        "Dominant seventh sharp nine",
        "7#9",
        "P1 M3 P5 m7 A9",
        aliases=("7+9",),
        omit="P5",
    ),
    _t(
        "dominant7_sharp11",
        "Dominant seventh sharp eleven",
        "7#11",
        "P1 M3 P5 m7 A11",
        aliases=("7+11",),
        omit="P5",
    ),
    _t("dominant7_flat13", "Dominant seventh flat thirteen", "7b13", "P1 M3 P5 m7 m13", omit="P5"),
    _t(
        "altered",
        "Altered dominant",
        "7alt",
        "P1 M3 d5 m7 m9 A9 m13",
        aliases=("alt", "altered"),
        omit="d5 m9 A9 m13",
    ),
    _t("quartal3", "Quartal (three notes)", "quartal", "P1 P4 m7", family="quartal"),
    _t("quartal4", "Quartal (four notes)", "quartal4", "P1 P4 m7 m10", family="quartal"),
)

CHORD_TYPES: dict[str, ChordType] = {t.id: t for t in _ALL_TYPES}
MINOR_FAMILY = frozenset(
    {"minor", "minor6", "minor7", "minor_major7", "half_diminished7", "minor_add9",
     "minor_add11", "minor9", "minor_major9", "minor11", "minor13"}
)  # fmt: skip

_INVERSION_NAMES = ("root position", "first inversion", "second inversion", "third inversion")


def chord_type(type_id: str) -> ChordType:
    try:
        return CHORD_TYPES[type_id]
    except KeyError:
        raise TheoryError(f"Unknown chord type {type_id!r}", code="unknown_chord_type") from None


def find_chord_type(tones: tuple[Interval, ...]) -> ChordType | None:
    """The chord type whose formula is exactly these intervals above the root, if any."""
    wanted = frozenset((i.number, i.semitones) for i in tones)
    for t in _ALL_TYPES:
        if frozenset((i.number, i.semitones) for i in t.formula) == wanted:
            return t
    return None


def inversion_name(index: int) -> str:
    return _INVERSION_NAMES[index] if index < len(_INVERSION_NAMES) else f"inversion {index}"


@dataclass(frozen=True)
class Chord:
    root: NoteName
    type: ChordType
    bass: NoteName | None = None  # slash-chord bass; None means the root is the bass

    def tones(self) -> tuple[NoteName, ...]:
        """Chord tones in formula order (root, third, fifth, ...), correctly spelled."""
        return tuple(transpose_name(self.root, i) for i in self.type.formula)

    def pitch_classes(self) -> tuple[int, ...]:
        return tuple(n.pitch_class for n in self.tones())

    @property
    def bass_name(self) -> NoteName:
        return self.bass or self.root

    def inversion(self) -> int | None:
        """0 = root position, 1 = third in the bass, ... None if the bass is not a chord tone."""
        if self.bass is None:
            return 0
        for i, tone in enumerate(self.tones()):
            if tone.pitch_class == self.bass.pitch_class:
                return i
        return None

    def with_inversion(self, index: int) -> Chord:
        tones = self.tones()
        if not 0 <= index < len(tones):
            raise TheoryError(f"Inversion must be 0-{len(tones) - 1}", code="invalid_inversion")
        return Chord(self.root, self.type, None if index == 0 else tones[index])

    def notes(self, octave: int = 4, inversion: int | None = None) -> list[Note]:
        """Sounding notes, lowest first. `octave` is the root's octave in root position.
        A bass that is not a chord tone (C/D) is added below the chord."""
        root = note_with_spelling(12 * (octave + 1) + self.root.pitch_class, self.root)
        stack = [transpose_note(root, i) for i in self.type.formula]
        inv = self.inversion() if inversion is None else inversion
        if inv is None:
            lowest = stack[0].midi
            bass_midi = (
                12 * ((lowest - self.bass_name.pitch_class - 1) // 12) + self.bass_name.pitch_class
            )
            return [note_with_spelling(bass_midi, self.bass_name), *stack]
        if not 0 <= inv < len(stack):
            raise TheoryError(f"Inversion must be 0-{len(stack) - 1}", code="invalid_inversion")
        bass = stack[inv]
        raised = []
        for n in stack[:inv]:  # tones below the new bass go up whole octaves until above it
            while n.midi <= bass.midi:
                n = Note(n.name, n.octave + 1)
            raised.append(n)
        return [*stack[inv:], *sorted(raised, key=lambda x: x.midi)]

    def midi_notes(self, octave: int = 4, inversion: int | None = None) -> list[int]:
        return [n.midi for n in self.notes(octave, inversion)]

    def transposed(self, interval: Interval, *, down: bool = False) -> Chord:
        return Chord(
            transpose_name(self.root, interval, down=down),
            self.type,
            None if self.bass is None else transpose_name(self.bass, interval, down=down),
        )

    def symbol(self) -> str:
        from music_theory.chord_symbols import format_chord

        return format_chord(self)

    def __str__(self) -> str:
        return self.symbol()


def make_chord(root: str | NoteName, type_id: str, bass: str | NoteName | None = None) -> Chord:
    return Chord(
        parse_note_name(root) if isinstance(root, str) else root,
        chord_type(type_id),
        parse_note_name(bass) if isinstance(bass, str) else bass,
    )
