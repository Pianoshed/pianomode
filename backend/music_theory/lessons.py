"""Theory lessons (spec 8.7).

Lessons are authored data (`data/lessons.json`): objectives, explanation text, examples and
practice goals. **No notes are written in lesson text or data.** An example names a chord, scale,
interval or chord sequence and the theory engine builds the notes, MIDI numbers, Roman numerals
and playback events when the lesson is requested, so a lesson can never disagree with the engine
that marks the exercises.

The loader is strict: it refuses duplicate ids, unknown prerequisites, prerequisite cycles,
unknown exercise kinds, malformed examples (they are built at load time) and empty objectives.

Limits: lessons are authored in English only; examples are built at one octave of the author's
choosing; prerequisites are advice for the learner and are never enforced by this module.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Final, Literal

from music_theory.chord_symbols import format_chord, parse_chord
from music_theory.errors import TheoryError
from music_theory.exercises import DIFFICULTIES, KINDS
from music_theory.intervals import interval_between_notes
from music_theory.keys import Key
from music_theory.notes import parse_note
from music_theory.roman import analyze_chord
from music_theory.scales import make_scale
from music_theory.validation import parse_key

LESSON_SCHEMA_VERSION: Final = 1
DATA_FILE: Final = Path(__file__).parent / "data" / "lessons.json"
LEVELS: Final = ("beginner", "intermediate", "advanced", "expert")
DEFAULT_GOAL: Final = 3
MAX_GOAL: Final = 20
Level = Literal["beginner", "intermediate", "advanced", "expert"]


class LessonError(TheoryError):
    code = "invalid_lesson"


def _bad(message: str, code: str = "invalid_lesson") -> LessonError:
    err = LessonError(message)
    err.code = code
    return err


# ------------------------------------------------------------------ authored shapes


@dataclass(frozen=True)
class ExampleSpec:
    type: Literal["chord", "scale", "interval", "sequence"]
    caption: str
    data: dict[str, Any]


@dataclass(frozen=True)
class Section:
    heading: str
    body: tuple[str, ...]
    examples: tuple[ExampleSpec, ...] = ()


@dataclass(frozen=True)
class PracticeGoal:
    kind: str
    difficulty: str
    goal: int = DEFAULT_GOAL


@dataclass(frozen=True)
class Lesson:
    id: str
    title: str
    level: Level
    summary: str
    objectives: tuple[str, ...]
    prerequisites: tuple[str, ...]
    sections: tuple[Section, ...]
    practice: tuple[PracticeGoal, ...]
    revision: int = 1
    movement_template: str | None = None  # a progression template id to link to
    tags: tuple[str, ...] = field(default_factory=tuple)


# ------------------------------------------------------------------ built examples


@dataclass(frozen=True)
class ExampleItem:
    label: str
    notes: tuple[str, ...]  # spelled names, lowest first
    midi: tuple[int, ...]
    detail: str | None = None  # e.g. a Roman numeral or an interval name


@dataclass(frozen=True)
class PlayStep:
    notes: tuple[int, ...]
    start: float
    duration: float
    item: int  # index of the ExampleItem that is sounding


@dataclass(frozen=True)
class BuiltExample:
    type: str
    caption: str
    items: tuple[ExampleItem, ...]
    play: tuple[PlayStep, ...]
    tempo: int = 80


def _need(data: dict[str, Any], key: str, kind: type, where: str) -> Any:
    if key not in data or not isinstance(data[key], kind) or isinstance(data[key], bool):
        raise _bad(f"{where}: needs {key!r} ({kind.__name__}).", "invalid_example")
    return data[key]


def _octave(data: dict[str, Any], where: str) -> int:
    octave = data.get("octave", 4)
    if isinstance(octave, bool) or not isinstance(octave, int) or not 1 <= octave <= 6:
        raise _bad(f"{where}: octave must be a whole number from 1 to 6.", "invalid_example")
    return int(octave)


def _chord_item(symbol: str, octave: int, key: Key | None, where: str) -> ExampleItem:
    try:
        chord = parse_chord(symbol)
        notes = chord.notes(octave)
        detail = analyze_chord(chord, key).figure if key is not None else None
    except TheoryError as exc:
        raise _bad(f"{where}: {exc}", "invalid_example") from exc
    return ExampleItem(
        label=format_chord(chord),
        notes=tuple(str(n.name) for n in notes),
        midi=tuple(n.midi for n in notes),
        detail=detail,
    )


def build_example(spec: ExampleSpec) -> BuiltExample:
    """Build one example with the engine. Raises LessonError if the spec cannot be built."""
    where = f"example {spec.caption!r}"
    d = spec.data
    if spec.type == "chord":
        item = _chord_item(_need(d, "symbol", str, where), _octave(d, where), None, where)
        return BuiltExample(
            "chord", spec.caption, (item,), (PlayStep(item.midi, 0.0, 3.0, 0),), tempo=80
        )
    if spec.type == "sequence":
        key = None
        if "key" in d:
            try:
                tonic, _, mode = str(_need(d, "key", str, where)).partition(" ")
                key = parse_key(tonic, mode or "major")
            except TheoryError as exc:
                raise _bad(f"{where}: {exc}", "invalid_example") from exc
        symbols = _need(d, "chords", list, where)
        if not symbols or len(symbols) > 12 or not all(isinstance(s, str) for s in symbols):
            raise _bad(f"{where}: chords must be 1 to 12 chord symbols.", "invalid_example")
        octave = _octave(d, where)
        octaves = d.get("octaves")
        if octaves is None:
            octaves = [octave] * len(symbols)
        elif (
            not isinstance(octaves, list)
            or len(octaves) != len(symbols)
            or not all(
                isinstance(o, int) and not isinstance(o, bool) and 1 <= o <= 6 for o in octaves
            )
        ):
            raise _bad(
                f"{where}: octaves must be one whole number (1 to 6) for each chord.",
                "invalid_example",
            )
        # `octave` places the root-position chord; an inversion sits above it, so an author who
        # wants close voicings gives a lower octave to the inverted chords.
        items = tuple(_chord_item(s, o, key, where) for s, o in zip(symbols, octaves, strict=True))
        steps = tuple(PlayStep(it.midi, i * 2.0, 2.0, i) for i, it in enumerate(items))
        return BuiltExample("sequence", spec.caption, items, steps, tempo=72)
    if spec.type == "scale":
        octave = _octave(d, where)
        try:
            scale = make_scale(_need(d, "root", str, where), _need(d, "scale", str, where))
            notes = scale.keyboard_notes(octave, include_octave=True)
        except TheoryError as exc:
            raise _bad(f"{where}: {exc}", "invalid_example") from exc
        items = tuple(
            ExampleItem(
                str(n.name),
                (str(n.name),),
                (n.midi,),
                f"degree {i + 1}" if i < len(notes) - 1 else None,
            )
            for i, n in enumerate(notes)
        )
        steps = tuple(PlayStep(it.midi, i * 0.5, 0.5, i) for i, it in enumerate(items))
        return BuiltExample("scale", spec.caption, items, steps, tempo=120)
    if spec.type == "interval":
        try:
            low = parse_note(_need(d, "lower", str, where))
            high = parse_note(_need(d, "upper", str, where))
            iv = interval_between_notes(low, high)
        except TheoryError as exc:
            raise _bad(f"{where}: {exc}", "invalid_example") from exc
        item = ExampleItem(
            label=f"{iv.short} ({iv.semitones} semitones)",
            notes=(str(low.name), str(high.name)),
            midi=(low.midi, high.midi),
            detail=iv.short,
        )
        steps = (
            PlayStep((low.midi,), 0.0, 1.0, 0),
            PlayStep((high.midi,), 1.0, 1.0, 0),
            PlayStep((low.midi, high.midi), 2.5, 2.0, 0),
        )
        return BuiltExample("interval", spec.caption, (item,), steps, tempo=80)
    raise _bad(f"{where}: unknown example type {spec.type!r}.", "invalid_example")


# ------------------------------------------------------------------ loading


def _text(d: dict[str, Any], key: str, where: str, *, limit: int = 2000) -> str:
    val = d.get(key)
    if not isinstance(val, str) or not val.strip() or len(val) > limit:
        raise _bad(f"{where}: {key!r} must be 1-{limit} characters of text.", "invalid_lesson")
    return val


def _strings(
    d: dict[str, Any], key: str, where: str, *, minimum: int = 0, maximum: int = 12
) -> tuple[str, ...]:
    val = d.get(key, [])
    if not isinstance(val, list) or not all(isinstance(s, str) and s.strip() for s in val):
        raise _bad(f"{where}: {key!r} must be a list of text.", "invalid_lesson")
    if not minimum <= len(val) <= maximum:
        raise _bad(f"{where}: {key!r} needs {minimum} to {maximum} items.", "invalid_lesson")
    return tuple(val)


def _parse_lesson(raw: dict[str, Any]) -> Lesson:
    if not isinstance(raw, dict):
        raise _bad("A lesson must be an object.")
    lid = raw.get("id")
    if (
        not isinstance(lid, str)
        or not lid
        or not all(c.islower() or c.isdigit() or c == "-" for c in lid)
    ):
        raise _bad(f"Lesson id {lid!r} must be lower-case letters, digits and hyphens.")
    where = f"lesson {lid}"
    level = raw.get("level")
    if level not in LEVELS:
        raise _bad(f"{where}: level must be one of {', '.join(LEVELS)}.")
    sections = []
    for i, s in enumerate(raw.get("sections", [])):
        sw = f"{where} section {i + 1}"
        examples = []
        for e in s.get("examples", []):
            etype = e.get("type")
            if etype not in ("chord", "scale", "interval", "sequence"):
                raise _bad(f"{sw}: unknown example type {etype!r}.", "invalid_example")
            data = {k: v for k, v in e.items() if k not in ("type", "caption")}
            examples.append(ExampleSpec(etype, _text(e, "caption", sw, limit=200), data))
        sections.append(
            Section(
                _text(s, "heading", sw, limit=120),
                _strings(s, "body", sw, minimum=1, maximum=8),
                tuple(examples),
            )
        )
    if not sections:
        raise _bad(f"{where}: needs at least one section.")
    practice = []
    for p in raw.get("practice", []):
        kind, diff, goal = p.get("kind"), p.get("difficulty"), p.get("goal", DEFAULT_GOAL)
        if kind not in KINDS:
            raise _bad(f"{where}: unknown exercise kind {kind!r}.", "unknown_exercise_kind")
        if diff not in DIFFICULTIES:
            raise _bad(f"{where}: unknown difficulty {diff!r}.")
        if isinstance(goal, bool) or not isinstance(goal, int) or not 1 <= goal <= MAX_GOAL:
            raise _bad(f"{where}: goal must be a whole number from 1 to {MAX_GOAL}.")
        practice.append(PracticeGoal(kind, diff, goal))
    if not practice:
        raise _bad(f"{where}: needs at least one practice goal.")
    template = raw.get("movement_template")
    return Lesson(
        id=lid,
        title=_text(raw, "title", where, limit=120),
        level=level,
        summary=_text(raw, "summary", where, limit=300),
        objectives=_strings(raw, "objectives", where, minimum=1, maximum=6),
        prerequisites=_strings(raw, "prerequisites", where, maximum=6),
        sections=tuple(sections),
        practice=tuple(practice),
        revision=int(raw.get("revision", 1)),
        movement_template=template if isinstance(template, str) else None,
        tags=_strings(raw, "tags", where, maximum=8),
    )


def _check_graph(lessons: list[Lesson]) -> None:
    ids = [x.id for x in lessons]
    if len(set(ids)) != len(ids):
        dup = next(i for i in ids if ids.count(i) > 1)
        raise _bad(f"Duplicate lesson id {dup!r}.", "duplicate_lesson")
    known = set(ids)
    by_id = {x.id: x for x in lessons}
    for x in lessons:
        for p in x.prerequisites:
            if p not in known:
                raise _bad(
                    f"Lesson {x.id!r} lists unknown prerequisite {p!r}.", "unknown_prerequisite"
                )
            if p == x.id:
                raise _bad(f"Lesson {x.id!r} lists itself as a prerequisite.", "prerequisite_cycle")
    state: dict[str, int] = {}

    def visit(lid: str, path: tuple[str, ...]) -> None:
        if state.get(lid) == 2:
            return
        if state.get(lid) == 1:
            raise _bad("Prerequisite cycle: " + " -> ".join((*path, lid)), "prerequisite_cycle")
        state[lid] = 1
        for p in by_id[lid].prerequisites:
            visit(p, (*path, lid))
        state[lid] = 2

    for lid in ids:
        visit(lid, ())


def parse_lessons(data: dict[str, Any], *, check_templates: bool = True) -> tuple[Lesson, ...]:
    """Validate and build lesson objects from loaded JSON. Builds every example once, so a lesson
    with a broken example cannot be loaded."""
    if data.get("schema_version") != LESSON_SCHEMA_VERSION:
        raise _bad(
            f"Lesson data has schema version {data.get('schema_version')!r}; "
            f"expected {LESSON_SCHEMA_VERSION}.",
            "unsupported_lesson_version",
        )
    lessons = [_parse_lesson(r) for r in data.get("lessons", [])]
    if not lessons:
        raise _bad("No lessons found.")
    _check_graph(lessons)
    for x in lessons:
        for s in x.sections:
            for e in s.examples:
                build_example(e)
    if check_templates:
        from music_theory.progressions import default_library

        lib = default_library()
        for x in lessons:
            if x.movement_template is not None:
                lib.get(x.movement_template)  # raises a stable error if it does not exist
    return tuple(lessons)


@lru_cache(maxsize=1)
def all_lessons() -> tuple[Lesson, ...]:
    return parse_lessons(json.loads(DATA_FILE.read_text(encoding="utf-8")))


def get_lesson(lesson_id: str) -> Lesson:
    for x in all_lessons():
        if x.id == lesson_id:
            return x
    raise _bad(f"No lesson named {lesson_id!r}.", "lesson_not_found")


def followers(lesson_id: str) -> tuple[str, ...]:
    """Lessons that list this one as a prerequisite, in curriculum order."""
    return tuple(x.id for x in all_lessons() if lesson_id in x.prerequisites)


# ------------------------------------------------------------------ authored-lesson helpers


def validate_lesson(raw: dict[str, Any], *, check_template: bool = True) -> Lesson:
    """Validate one authored lesson on its own: structure, every example built by the engine,
    and the linked progression template. Prerequisites are checked against a catalogue
    separately (`check_lesson_graph`), because they depend on which other lessons are live."""
    lesson = _parse_lesson(raw)
    for s in lesson.sections:
        for e in s.examples:
            build_example(e)
    if check_template and lesson.movement_template is not None:
        from music_theory.progressions import default_library

        default_library().get(lesson.movement_template)
    return lesson


def check_lesson_graph(lessons: list[Lesson]) -> None:
    """Refuse duplicate ids, unknown prerequisites and prerequisite cycles in a catalogue."""
    _check_graph(lessons)


def lesson_publication_blockers(lesson: Lesson) -> list[str]:
    """Why an authored lesson cannot be published. Empty means it can. The loader already
    guarantees objectives, a section with text and a practice goal; publication also needs at least
    one engine-built example so learners always see and hear something."""
    blockers: list[str] = []
    if not any(s.examples for s in lesson.sections):
        blockers.append("Add at least one musical example (chord, scale, interval or sequence).")
    return blockers


def lesson_publication_warnings(lesson: Lesson, levels_of: Mapping[str, str]) -> list[str]:
    """Advice that does not block publication."""
    warnings: list[str] = []
    for i, s in enumerate(lesson.sections, start=1):
        if not s.examples:
            warnings.append(f"Section {i} ({s.heading}) has no example.")
    if len(lesson.objectives) < 2:
        warnings.append("Only one learning objective; most lessons state two or three.")
    order = {name: n for n, name in enumerate(LEVELS)}
    for p in lesson.prerequisites:
        if p in levels_of and order[levels_of[p]] > order[lesson.level]:
            warnings.append(
                f"Prerequisite {p!r} is a harder level ({levels_of[p]}) than this lesson."
            )
    return warnings
