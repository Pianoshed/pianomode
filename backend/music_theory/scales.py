"""Data-driven scales and modes.

Scales are defined by interval formulas in `data/scales.json`, validated on load. Adding a scale
means adding a definition (via JSON or `ScaleRegistry.register`), never editing this module.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from functools import lru_cache
from importlib import resources
from typing import Literal

from music_theory.errors import TheoryError
from music_theory.intervals import P1, Interval, parse_interval, transpose_name
from music_theory.notes import Note, NoteName, note_with_spelling, parse_note_name

Direction = Literal["ascending", "descending"]
_ID_RE = re.compile(r"^[a-z][a-z0-9_]*$")
CHURCH_MODES = ("ionian", "dorian", "phrygian", "lydian", "mixolydian", "aeolian", "locrian")


class ScaleDefinitionError(TheoryError):
    code = "invalid_scale_definition"


def _key(text: str) -> str:
    return re.sub(r"[\s\-]+", "_", text.strip().lower())


def _check_formula(label: str, formula: tuple[Interval, ...]) -> None:
    if not formula or formula[0] != P1:
        raise ScaleDefinitionError(f"{label} must start with P1")
    semis = [i.semitones for i in formula]
    if any(b <= a for a, b in zip(semis, semis[1:], strict=False)):
        raise ScaleDefinitionError(f"{label} must rise strictly in pitch")
    if semis[-1] >= 12 or any(i.number > 8 for i in formula):
        raise ScaleDefinitionError(f"{label} must stay within one octave")


@dataclass(frozen=True)
class ScaleDefinition:
    id: str
    name: str
    formula: tuple[Interval, ...]
    descending: tuple[Interval, ...] | None = None
    family: str = "scale"
    aliases: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not _ID_RE.match(self.id):
            raise ScaleDefinitionError(f"Invalid scale id {self.id!r} (use a-z, 0-9, _)")
        if not self.name.strip():
            raise ScaleDefinitionError("Scale name is required")
        _check_formula(f"{self.id} formula", self.formula)
        if self.descending is not None:
            _check_formula(f"{self.id} descending formula", self.descending)
            if len(self.descending) != len(self.formula):
                raise ScaleDefinitionError(f"{self.id}: descending form must have the same length")

    @property
    def size(self) -> int:
        return len(self.formula)


def parse_definition(data: Mapping[str, object]) -> ScaleDefinition:
    try:
        raw_formula = data["formula"]
        raw_desc = data.get("descending")
        aliases = data.get("aliases", [])
        if not isinstance(raw_formula, list) or not isinstance(aliases, list):
            raise ScaleDefinitionError("formula and aliases must be lists")
        return ScaleDefinition(
            id=str(data["id"]),
            name=str(data["name"]),
            formula=tuple(parse_interval(str(s)) for s in raw_formula),
            descending=(
                tuple(parse_interval(str(s)) for s in raw_desc)
                if isinstance(raw_desc, list)
                else None
            ),
            family=str(data.get("family", "scale")),
            aliases=tuple(str(a) for a in aliases),
        )
    except KeyError as exc:
        raise ScaleDefinitionError(f"Missing field {exc.args[0]!r}") from exc
    except ScaleDefinitionError:
        raise
    except TheoryError as exc:
        raise ScaleDefinitionError(f"{data.get('id', '?')}: {exc.message}") from exc


def load_definitions(json_text: str) -> list[ScaleDefinition]:
    try:
        payload = json.loads(json_text)
    except json.JSONDecodeError as exc:
        raise ScaleDefinitionError(f"Invalid JSON: {exc.msg}") from exc
    items = payload.get("scales") if isinstance(payload, dict) else None
    if not isinstance(items, list):
        raise ScaleDefinitionError('Expected {"scales": [...]}')
    return [parse_definition(item) for item in items]


class ScaleRegistry:
    def __init__(self, definitions: Iterable[ScaleDefinition] = ()) -> None:
        self._by_id: dict[str, ScaleDefinition] = {}
        self._alias: dict[str, str] = {}
        for d in definitions:
            self.register(d)

    def register(self, definition: ScaleDefinition, *, replace: bool = False) -> None:
        if definition.id in self._by_id and not replace:
            raise ScaleDefinitionError(f"Scale {definition.id!r} already exists")
        keys = [_key(definition.id), *(_key(a) for a in definition.aliases)]
        for k in keys:
            owner = self._alias.get(k)
            if owner is not None and owner != definition.id:
                raise ScaleDefinitionError(f"{k!r} is already used by scale {owner!r}")
        for stale in [k for k, owner in self._alias.items() if owner == definition.id]:
            del self._alias[stale]
        self._by_id[definition.id] = definition
        for k in keys:
            self._alias[k] = definition.id

    def get(self, key: str) -> ScaleDefinition:
        found = self._alias.get(_key(key))
        if found is None:
            raise TheoryError(f"Unknown scale {key!r}", code="unknown_scale")
        return self._by_id[found]

    def ids(self) -> list[str]:
        return list(self._by_id)

    def all(self) -> list[ScaleDefinition]:
        return list(self._by_id.values())

    def copy(self) -> ScaleRegistry:
        return ScaleRegistry(self._by_id.values())


@lru_cache
def default_registry() -> ScaleRegistry:
    """Built-in scales. Treat as read-only; call `.copy()` before registering extras."""
    text = resources.files("music_theory.data").joinpath("scales.json").read_text("utf-8")
    return ScaleRegistry(load_definitions(text))


@dataclass(frozen=True)
class ScaleDegree:
    number: int
    note: NoteName
    interval: Interval


@dataclass(frozen=True)
class Scale:
    root: NoteName
    definition: ScaleDefinition

    def _spell(self, formula: tuple[Interval, ...]) -> tuple[NoteName, ...]:
        try:
            return tuple(transpose_name(self.root, i) for i in formula)
        except TheoryError as exc:
            raise TheoryError(
                f"{self.definition.name} on {self.root} needs more than double accidentals; "
                "choose the enharmonic root",
                code="spelling_overflow",
            ) from exc

    def notes(self, direction: Direction = "ascending") -> tuple[NoteName, ...]:
        """Scale tones from the root. Descending runs root, then down through the scale
        (A melodic minor descending: A G F E D C B)."""
        if direction == "ascending":
            return self._spell(self.definition.formula)
        formula = self.definition.descending or self.definition.formula
        spelled = self._spell(formula)
        return (spelled[0], *reversed(spelled[1:]))

    def degrees(self) -> tuple[ScaleDegree, ...]:
        notes = self.notes()
        return tuple(
            ScaleDegree(i + 1, n, iv)
            for i, (n, iv) in enumerate(zip(notes, self.definition.formula, strict=True))
        )

    def pitch_classes(self) -> frozenset[int]:
        return frozenset(n.pitch_class for n in self.notes())

    def contains(self, pitch_class: int) -> bool:
        return pitch_class % 12 in self.pitch_classes()

    def note_at_degree(self, degree: int) -> NoteName:
        notes = self.notes()
        if not 1 <= degree <= len(notes):
            raise TheoryError(f"Degree must be 1-{len(notes)}", code="invalid_degree")
        return notes[degree - 1]

    def keyboard_notes(self, octave: int = 4, *, include_octave: bool = False) -> list[Note]:
        """Ascending sounding notes starting on the root in `octave`."""
        root = note_with_spelling(12 * (octave + 1) + self.root.pitch_class, self.root)
        notes = [
            note_with_spelling(root.midi + i.semitones, transpose_name(self.root, i))
            for i in self.definition.formula
        ]
        if include_octave:
            notes.append(note_with_spelling(root.midi + 12, self.root))
        return notes


def make_scale(root: str | NoteName, scale: str, registry: ScaleRegistry | None = None) -> Scale:
    name = parse_note_name(root) if isinstance(root, str) else root
    return Scale(name, (registry or default_registry()).get(scale))
