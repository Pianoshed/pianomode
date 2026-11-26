"""Roman-numeral analysis, parsing, and cadences.

Analysis order for a chord in a key: diatonic -> secondary dominant / leading-tone chord ->
borrowed from the parallel mode -> chromatic. Numerals follow the spelling of the chord's root.
Functional labels are simplified (tonic / predominant / dominant).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from music_theory.chords import CHORD_TYPES, Chord, chord_type
from music_theory.errors import TheoryError
from music_theory.keys import Key
from music_theory.notes import NoteName

Case = Literal["upper", "lower"]
Category = Literal[
    "diatonic", "secondary_dominant", "secondary_leading_tone", "borrowed", "chromatic"
]

_NUMERALS = ("I", "II", "III", "IV", "V", "VI", "VII")
_MAJOR_SEMIS = (0, 2, 4, 5, 7, 9, 11)
_MINOR_SEMIS = (0, 2, 3, 5, 7, 8, 10)
_MAJOR_TRIADS = ("major", "minor", "minor", "major", "major", "minor", "diminished")
_MINOR_TRIADS = (
    "minor",
    "diminished",
    "major",
    "minor",
    "major",
    "major",
    "major",
)  # V from harmonic
_FUNCTION = {1: "tonic", 2: "predominant", 3: "tonic", 4: "predominant", 5: "dominant",
             6: "tonic", 7: "dominant"}  # fmt: skip

# chord type id -> (numeral case, quality mark, figure)
_FIGURES: dict[str, tuple[Case, str, str]] = {
    "major": ("upper", "", ""), "minor": ("lower", "", ""),
    "diminished": ("lower", "°", ""), "augmented": ("upper", "+", ""),
    "sus2": ("upper", "", "sus2"), "sus4": ("upper", "", "sus4"), "power": ("upper", "", "5"),
    "major6": ("upper", "", "add6"), "minor6": ("lower", "", "add6"),
    "six_nine": ("upper", "", "6/9"),
    "major7": ("upper", "", "maj7"), "minor7": ("lower", "", "7"), "dominant7": ("upper", "", "7"),
    "minor_major7": ("lower", "", "(maj7)"),
    "half_diminished7": ("lower", "ø", "7"), "diminished7": ("lower", "°", "7"),
    "dominant7_flat5": ("upper", "", "7b5"), "dominant7_sharp5": ("upper", "", "7#5"),
    "major7_sharp5": ("upper", "", "maj7#5"), "major7_flat5": ("upper", "", "maj7b5"),
    "dominant7_sus4": ("upper", "", "7sus4"),
    "add9": ("upper", "", "add9"), "minor_add9": ("lower", "", "add9"),
    "add11": ("upper", "", "add11"), "minor_add11": ("lower", "", "add11"),
    "dominant9": ("upper", "", "9"), "major9": ("upper", "", "maj9"), "minor9": ("lower", "", "9"),
    "minor_major9": ("lower", "", "(maj9)"),
    "dominant11": ("upper", "", "11"), "minor11": ("lower", "", "11"),
    "major11": ("upper", "", "maj11"),
    "dominant13": ("upper", "", "13"), "major13": ("upper", "", "maj13"),
    "minor13": ("lower", "", "13"),
    "dominant7_flat9": ("upper", "", "7b9"), "dominant7_sharp9": ("upper", "", "7#9"),
    "dominant7_sharp11": ("upper", "", "7#11"), "dominant7_flat13": ("upper", "", "7b13"),
    "altered": ("upper", "", "7alt"),
    "quartal3": ("upper", "", "quartal"), "quartal4": ("upper", "", "quartal4"),
}  # fmt: skip
_TRIAD_IDS = ("major", "minor", "diminished", "augmented")
_SEVENTH_IDS = ("major7", "minor7", "dominant7", "half_diminished7", "diminished7")
_TRIAD_FIGS = ("6", "6/4")
_SEVENTH_FIGS = ("6/5", "4/3", "4/2")
_DOMINANT_LIKE = frozenset(
    {"major", "dominant7", "dominant9", "dominant13", "dominant7_flat5", "dominant7_sharp5",
     "dominant7_flat9", "dominant7_sharp9", "dominant7_sharp11", "dominant7_flat13", "altered"}
)  # fmt: skip
_LEADING_TONE = frozenset({"diminished", "diminished7", "half_diminished7"})

assert set(_FIGURES) == set(CHORD_TYPES), "every chord type needs a numeral figure"


def _build_parse_table() -> dict[tuple[Case, str, str], tuple[str, int]]:
    table: dict[tuple[Case, str, str], tuple[str, int]] = {}

    def add(key: tuple[Case, str, str], value: tuple[str, int]) -> None:
        if key in table:
            raise RuntimeError(f"Duplicate numeral figure {key}")
        table[key] = value

    for type_id, (case, mark, fig) in _FIGURES.items():
        add((case, mark, fig), (type_id, 0))
    for type_id in _TRIAD_IDS:
        case, mark, _ = _FIGURES[type_id]
        for n, f in enumerate(_TRIAD_FIGS, start=1):
            add((case, mark, f), (type_id, n))
    for type_id in _SEVENTH_IDS:
        case, mark, fig = _FIGURES[type_id]
        for n, f in enumerate(_SEVENTH_FIGS, start=1):
            add((case, mark, fig[:-1] + f), (type_id, n))
    add(("lower", "ø", ""), ("half_diminished7", 0))
    return table


_PARSE = _build_parse_table()


def _figure_text(type_id: str, inversion: int | None) -> str:
    _, _, fig = _FIGURES[type_id]
    if not inversion:
        return fig
    if type_id in _TRIAD_IDS and inversion <= 2:
        return _TRIAD_FIGS[inversion - 1]
    if type_id in _SEVENTH_IDS and inversion <= 3:
        return fig[:-1] + _SEVENTH_FIGS[inversion - 1]
    return fig  # inversion of other chord types is reported in `inversion`, not in the figure


def _format(degree: int, accidental: int, type_id: str, inversion: int | None) -> str:
    case, mark, _ = _FIGURES[type_id]
    letters = _NUMERALS[degree - 1]
    letters = letters if case == "upper" else letters.lower()
    prefix = "#" * accidental if accidental > 0 else "b" * -accidental
    return f"{prefix}{letters}{mark}{_figure_text(type_id, inversion)}"


def _degree_and_accidental(root: NoteName, key: Key) -> tuple[int, int]:
    degree = (root.letter_index - key.tonic.letter_index) % 7 + 1
    semis = _MAJOR_SEMIS if key.mode == "major" else _MINOR_SEMIS
    ref_pc = (key.tonic.pitch_class + semis[degree - 1]) % 12
    acc = ((root.pitch_class - ref_pc + 6) % 12) - 6
    if key.mode == "minor" and degree == 7 and acc == 1:
        acc = 0  # raised leading tone: written vii°, not #vii°
    return degree, acc


@dataclass(frozen=True)
class RomanNumeral:
    chord: Chord
    key: Key
    figure: str
    degree: int
    accidental: int
    category: Category
    function: str | None
    applied_to: str | None
    borrowed_from: str | None
    inversion: int | None
    note: str | None = None
    alternatives: tuple[str, ...] = ()  # other plausible readings of the same chord

    def __str__(self) -> str:
        return self.figure


def _target_info(key: Key, degree: int) -> tuple[NoteName, str, str]:
    """Root, triad quality and numeral text of a diatonic degree, for tonicization."""
    notes = key.scale().notes()
    quality = (_MAJOR_TRIADS if key.mode == "major" else _MINOR_TRIADS)[degree - 1]
    text = _NUMERALS[degree - 1]
    if quality != "major":
        text = text.lower()
    if quality == "diminished":
        text += "°"
    return notes[degree - 1], quality, text


def analyze_chord(chord: Chord, key: Key) -> RomanNumeral:
    degree, acc = _degree_and_accidental(chord.root, key)
    inversion = chord.inversion()
    tones = set(chord.pitch_classes())
    type_id = chord.type.id

    def make(
        figure: str, category: Category, function: str | None = None,
        applied_to: str | None = None, borrowed_from: str | None = None, note: str | None = None,
        alternatives: tuple[str, ...] = (),
    ) -> RomanNumeral:  # fmt: skip
        return RomanNumeral(
            chord,
            key,
            figure,
            degree,
            acc,
            category,
            function,
            applied_to,
            borrowed_from,
            inversion,
            note,
            alternatives,
        )

    own = _format(degree, acc, type_id, inversion)
    if tones <= key.diatonic_pitch_classes():
        return make(own, "diatonic", _FUNCTION[degree] if acc == 0 else None)

    root_pc = chord.root.pitch_class
    for target_degree in range(2, 8):
        target_root, quality, target_text = _target_info(key, target_degree)
        if quality == "diminished":
            continue
        tpc = target_root.pitch_class
        if type_id in _DOMINANT_LIKE and root_pc == (tpc + 7) % 12:
            category: Category = "secondary_dominant"
        elif type_id in _LEADING_TONE and root_pc == (tpc - 1) % 12:
            category = "secondary_leading_tone"
        else:
            continue
        d, a = _degree_and_accidental(chord.root, Key(target_root, "major"))
        figure = f"{_format(d, a, type_id, inversion)}/{target_text}"
        label = "applied dominant" if category == "secondary_dominant" else "applied leading tone"
        parallel_pcs = key.parallel().diatonic_pitch_classes()
        alternatives: tuple[str, ...] = ()
        if tones <= parallel_pcs:  # context decides: applied chord or modal mixture?
            source = "parallel minor" if key.mode == "major" else "parallel major"
            alternatives = (f"{own} (borrowed from {source})",)
        return make(figure, category, label, applied_to=target_text, alternatives=alternatives)

    parallel = key.parallel()
    if tones <= parallel.diatonic_pitch_classes():
        source = "parallel minor" if key.mode == "major" else "parallel major"
        return make(own, "borrowed", None, borrowed_from=source, note="Modal interchange.")

    note = None
    if type_id == "major" and degree == 2 and acc == -1:
        note = "Neapolitan chord" + (" (Neapolitan sixth)" if inversion == 1 else "")
    return make(own, "chromatic", None, note=note)


def analyze_progression(chords: list[Chord], key: Key) -> list[RomanNumeral]:
    return [analyze_chord(c, key) for c in chords]


# ---------------------------------------------------------------- parsing


@dataclass(frozen=True)
class _Parsed:
    accidental: int
    degree: int
    case: Case
    type_id: str
    inversion: int
    target: str | None


_NUMERAL_RE = re.compile(r"^([b#]{0,2})(VII|VI|IV|V|III|II|I|vii|vi|iv|v|iii|ii|i)(.*)$")
_MARK_CASE: dict[str, Case] = {"°": "lower", "ø": "lower", "+": "upper"}


def _parse(text: str) -> _Parsed:
    m = _NUMERAL_RE.match(text.strip())
    if m is None:
        raise TheoryError(f"Not a Roman numeral: {text!r}", code="invalid_roman_numeral")
    prefix, numeral, rest = m.groups()
    if prefix and set(prefix) != {prefix[0]}:
        raise TheoryError(f"Mixed sharps and flats in {text!r}", code="invalid_roman_numeral")
    accidental = len(prefix) * (1 if prefix.startswith("#") else -1) if prefix else 0
    degree = _NUMERALS.index(numeral.upper()) + 1
    case: Case = "upper" if numeral.isupper() else "lower"
    mark = ""
    if rest[:1] == "o":
        rest = "°" + rest[1:]
    if rest[:1] in _MARK_CASE:
        mark, rest = rest[0], rest[1:]
    lookup_case = _MARK_CASE.get(mark, case)
    figures = sorted(
        (f for (c, mk, f) in _PARSE if c == lookup_case and mk == mark), key=len, reverse=True
    )
    for fig in figures:
        if rest.startswith(fig) and (len(rest) == len(fig) or rest[len(fig)] == "/"):
            tail = rest[len(fig) :]
            if tail and (len(tail) == 1 or tail[1:].startswith("/")):
                raise TheoryError(
                    f"Missing target after '/' in {text!r}", code="invalid_roman_numeral"
                )
            type_id, inversion = _PARSE[(lookup_case, mark, fig)]
            return _Parsed(accidental, degree, case, type_id, inversion, tail[1:] or None)
    raise TheoryError(f"Unknown figure {rest!r} in {text!r}", code="invalid_roman_numeral")


def chord_from_roman(text: str, key: Key) -> Chord:
    """Build the chord a numeral stands for: 'V7' in C is G7, 'V7/V' is D7, 'bVI' in C is Ab."""
    parsed = _parse(text)
    base = key
    if parsed.target is not None:
        base = Key(chord_from_roman(parsed.target, key).root, "major")
    if base.mode == "minor" and parsed.degree == 7 and parsed.case == "lower":
        note = Key(base.tonic, "major").scale().notes()[6]  # leading tone
    else:
        note = base.scale().notes()[parsed.degree - 1]
    root = NoteName(note.letter, note.accidental + parsed.accidental)
    chord = Chord(root, chord_type(parsed.type_id))
    return chord.with_inversion(parsed.inversion) if parsed.inversion else chord


# ---------------------------------------------------------------- cadences


@dataclass(frozen=True)
class Cadence:
    start: int
    end: int
    kind: str
    note: str


def _is_dominant(n: RomanNumeral) -> bool:
    return (
        n.category == "diatonic"
        and n.degree == 5
        and n.chord.type.id in _DOMINANT_LIKE
        or n.category == "diatonic"
        and n.degree == 7
        and n.chord.type.id in _LEADING_TONE
    )


def find_cadences(numerals: list[RomanNumeral]) -> list[Cadence]:
    """Cadence candidates from chord pairs. Melody and phrasing are not analysed, so a 'perfect'
    authentic cadence can only be suggested, not confirmed."""
    out: list[Cadence] = []
    for i in range(len(numerals) - 1):
        a, b = numerals[i], numerals[i + 1]
        if b.category != "diatonic":
            continue
        if _is_dominant(a) and b.degree == 1:
            both_root = a.inversion == 0 and b.inversion == 0
            out.append(
                Cadence(
                    i,
                    i + 1,
                    "authentic",
                    "Both chords in root position: a perfect authentic cadence if the melody ends "
                    "on the tonic."
                    if both_root
                    else "Authentic cadence with an inverted chord.",
                )  # fmt: skip
            )
        elif a.category == "diatonic" and a.degree == 4 and b.degree == 1:
            out.append(Cadence(i, i + 1, "plagal", "IV to I."))
        elif _is_dominant(a) and a.degree == 5 and b.degree == 6:
            out.append(Cadence(i, i + 1, "deceptive", "V resolves to vi/VI instead of the tonic."))
        elif (
            a.key.mode == "minor" and a.category == "diatonic" and a.degree == 4
            and a.inversion == 1 and _is_dominant(b) and b.degree == 5
        ):  # fmt: skip
            out.append(Cadence(i, i + 1, "phrygian half", "iv6 to V in a minor key."))
    if len(numerals) >= 2 and _is_dominant(numerals[-1]) and numerals[-1].degree == 5:
        out.append(Cadence(len(numerals) - 2, len(numerals) - 1, "half", "Phrase ends on V."))
    return out
