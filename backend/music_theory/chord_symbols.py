"""Chord-symbol parser and formatter.

Parsing is strict: an unrecognised suffix is an error, never a guess. "Cmaj" is rejected because it
is ambiguous between a triad and a seventh; write "C" or "Cmaj7".
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from music_theory.chords import CHORD_TYPES, MINOR_FAMILY, Chord, ChordType
from music_theory.errors import TheoryError
from music_theory.notes import NoteName, parse_note_name

_ROOT_ACCIDENTALS = ("##", "bb", "𝄪", "𝄫", "♯♯", "♭♭", "#", "b", "♯", "♭")


class ChordSymbolError(TheoryError):
    """`code` is one of: empty_symbol, invalid_root, unknown_quality, invalid_bass."""

    def __init__(self, message: str, *, code: str, symbol: str, position: int) -> None:
        super().__init__(message, code=code)
        self.symbol = symbol
        self.position = position


def normalize_suffix(text: str) -> str:
    """Canonical comparison form for a chord suffix: ASCII accidentals, no spaces or brackets."""
    for old, new in (("♭", "b"), ("♯", "#"), ("♮", ""), ("−", "-"), ("–", "-")):
        text = text.replace(old, new)
    return "".join(c for c in text if c not in " ()")


def _build_alias_table() -> dict[str, ChordType]:
    table: dict[str, ChordType] = {}
    for t in CHORD_TYPES.values():
        for raw in (t.symbol, *t.aliases):
            key = normalize_suffix(raw)
            owner = table.get(key)
            if owner is not None and owner is not t:
                raise RuntimeError(f"Chord alias {raw!r} is used by {owner.id} and {t.id}")
            table[key] = t
    return table


_ALIASES = _build_alias_table()


def _parse_root(symbol: str) -> tuple[NoteName, int]:
    if not symbol or symbol[0] not in "ABCDEFG":
        raise ChordSymbolError(
            f"A chord symbol starts with a root note A-G, got {symbol[:1]!r}",
            code="invalid_root", symbol=symbol, position=0,
        )  # fmt: skip
    rest = symbol[1:]
    for acc in _ROOT_ACCIDENTALS:
        if rest.startswith(acc):
            return parse_note_name(symbol[0] + acc), 1 + len(acc)
    return NoteName(symbol[0]), 1


def parse_chord(symbol: str) -> Chord:
    original = symbol
    symbol = symbol.strip()
    if not symbol:
        raise ChordSymbolError(
            "Empty chord symbol", code="empty_symbol", symbol=original, position=0
        )
    root, pos = _parse_root(symbol)
    rest = normalize_suffix(symbol[pos:])

    found = _ALIASES.get(rest)
    if found is not None:
        return Chord(root, found)

    if "/" in rest:
        quality, bass_text = rest.rsplit("/", 1)
        found = _ALIASES.get(quality)
        if found is None:
            raise ChordSymbolError(
                f"Unrecognised chord quality {quality!r} in {original!r}",
                code="unknown_quality", symbol=original, position=pos,
            )  # fmt: skip
        try:
            bass = parse_note_name(bass_text)
        except TheoryError as exc:
            raise ChordSymbolError(
                f"The note after '/' must be a note name like E or Bb, got {bass_text!r}",
                code="invalid_bass", symbol=original, position=len(symbol) - len(bass_text),
            ) from exc  # fmt: skip
        return Chord(root, found, bass)

    hint = (
        " Write C for a major triad or Cmaj7 for a major seventh." if rest in {"maj", "M"} else ""
    )
    raise ChordSymbolError(
        f"Unrecognised chord quality {symbol[pos:]!r} in {original!r}.{hint}",
        code="unknown_quality", symbol=original, position=pos,
    )  # fmt: skip


@dataclass(frozen=True)
class SymbolStyle:
    major7: Literal["maj7", "M7", "Δ7"] = "maj7"
    minor: Literal["m", "min", "-"] = "m"
    half_diminished: Literal["m7b5", "ø7"] = "m7b5"
    diminished: Literal["dim", "°"] = "dim"
    augmented: Literal["aug", "+"] = "aug"
    unicode_accidentals: bool = False


DEFAULT_STYLE = SymbolStyle()


def _suffix(t: ChordType, style: SymbolStyle) -> str:
    s = t.symbol
    if t.id == "half_diminished7" and style.half_diminished == "ø7":
        return "ø7"
    if t.id == "diminished":
        return "°" if style.diminished == "°" else s
    if t.id == "diminished7":
        return "°7" if style.diminished == "°" else s
    if t.id == "augmented":
        return "+" if style.augmented == "+" else s
    marker = {"maj7": "maj", "M7": "M", "Δ7": "Δ"}[style.major7]
    if "Maj" in s:
        s = s.replace("Maj", {"maj": "Maj", "M": "M", "Δ": "Δ"}[marker])
    elif "maj" in s:
        s = s.replace("maj", marker)
    if t.id in MINOR_FAMILY and s.startswith("m"):
        s = style.minor + s[1:]
    return s


def format_chord(chord: Chord, style: SymbolStyle = DEFAULT_STYLE) -> str:
    suffix = _suffix(chord.type, style)
    if style.unicode_accidentals:
        suffix = suffix.replace("b", "♭").replace("#", "♯")
    text = chord.root.format(unicode=style.unicode_accidentals) + suffix
    if chord.bass is not None:
        text += "/" + chord.bass.format(unicode=style.unicode_accidentals)
    return text
