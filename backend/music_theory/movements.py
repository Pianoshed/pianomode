"""Chord-movement library (spec 8.6).

A *movement* is one named chord progression practised at up to four levels. Each level is a
complete, voiced realisation built with the same engine as everything else:

- **beginner**: triads; bass note below, close triad above, root position preferred.
- **intermediate**: seventh chords; octave or root-and-fifth bass, close sevenths, basic inversions.
- **advanced**: seventh chords; shell and guide-tone left hand, smooth rootless and drop-2
  right hand.
- **expert**: sevenths plus tritone substitutes where a dominant resolves down a fifth; tenths,
  spread, upper-structure and altered voicings.

What is *stored* is a small `MovementDefinition` (key, template or custom chords, texts). The
four versions are **derived**, deterministically, from it. When a movement is published the
built result is also frozen as a snapshot by the caller, so learners keep seeing exactly what
was reviewed even if the voicing engine is improved later. This module is pure: no database.

Heuristic limits are listed in docs/music-theory.md ("Movement library").
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Any, Final, Literal

from music_theory.chord_symbols import format_chord
from music_theory.chords import Chord
from music_theory.errors import TheoryError
from music_theory.keys import Key
from music_theory.progressions import (
    _TRITONE_SUBBABLE,
    Progression,
    ProgressionLibrary,
    ProgressionTemplate,
    default_library,
    make_progression,
    realize,
    substitute_tritone,
    transpose_progression,
    validate_progression,
    voice_progression,
)
from music_theory.validation import MAX_VOICED_CHORDS, check_count, parse_key
from music_theory.voice_leading import config_for
from music_theory.voicings import (
    PRESETS,
    Voicing,
    VoicingConstraints,
    constraints_for_skill,
    voiced_notes,
)

MOVEMENT_SCHEMA_VERSION: Final = 1
GENERATOR_VERSION: Final = 1  # bump when what `build_movement` produces for a definition changes
Level = Literal["beginner", "intermediate", "advanced", "expert"]
LEVELS: Final[tuple[Level, ...]] = ("beginner", "intermediate", "advanced", "expert")

Status = Literal["draft", "under_review", "approved", "published", "archived"]
STATUSES: Final[tuple[Status, ...]] = (
    "draft",
    "under_review",
    "approved",
    "published",
    "archived",
)
# Allowed moves. "unpublish" is published -> approved; "restore" is archived -> draft.
TRANSITIONS: Final[dict[str, tuple[str, ...]]] = {
    "draft": ("under_review", "archived"),
    "under_review": ("draft", "approved", "archived"),
    "approved": ("draft", "published", "archived"),
    "published": ("approved", "archived"),
    "archived": ("draft",),
}
ACTION_FOR_MOVE: Final[dict[tuple[str, str], str]] = {
    ("draft", "under_review"): "submit",
    ("under_review", "draft"): "request_changes",
    ("under_review", "approved"): "approve",
    ("approved", "draft"): "return_to_draft",
    ("approved", "published"): "publish",
    ("published", "approved"): "unpublish",
    ("archived", "draft"): "restore",
}

MAX_TAGS: Final = 12
MAX_TEXT: Final = 4000
MAX_HISTORY: Final = 200


class MovementError(TheoryError):
    code = "invalid_movement"


def _bad(message: str, code: str = "invalid_movement") -> MovementError:
    err = MovementError(message)
    err.code = code
    return err


# ------------------------------------------------------------------ level recipes


@dataclass(frozen=True)
class LevelRecipe:
    level: Level
    vocabulary: Literal["triads", "sevenths"]
    preset: str
    weights: str
    style: str
    voicing_type: str  # one plain sentence shown to the learner
    constraint_overrides: Mapping[str, Any] = field(default_factory=dict)
    substitutions: bool = False


RECIPES: Final[dict[Level, LevelRecipe]] = {
    "beginner": LevelRecipe(
        "beginner", "triads", "beginner", "root_position", "pop",
        "Left hand plays the bass note; right hand plays a close triad, "
        "root position where it fits.",
        {"preferred_inversion": 0},
    ),
    "intermediate": LevelRecipe(
        "intermediate", "sevenths", "intermediate", "balanced", "pop",
        "Seventh chords with octave or root-and-fifth bass and basic inversions on the right.",
    ),
    "advanced": LevelRecipe(
        "advanced", "sevenths", "advanced", "smooth", "jazz",
        "Shell and guide-tone left hand; smooth rootless and drop-2 right-hand voicings.",
    ),
    "expert": LevelRecipe(
        "expert", "sevenths", "expert", "smooth", "jazz",
        "Tenths and open shells below; spread, upper-structure and altered voicings above, "
        "with tritone substitutes where a dominant resolves down a fifth.",
        {"tensions": ("M9",)},
        substitutions=True,
    ),
}  # fmt: skip


def _recipe_checks() -> None:
    for r in RECIPES.values():  # fail at import, not at request time
        if r.preset not in PRESETS:
            raise RuntimeError(f"recipe {r.level}: unknown preset {r.preset}")


_recipe_checks()


# ------------------------------------------------------------------ definition


@dataclass(frozen=True)
class CustomChord:
    symbol: str
    beats: float = 4.0


@dataclass(frozen=True)
class MovementDefinition:
    """Everything an author supplies. Exactly one of `template_id` or `custom_chords`."""

    name: str
    key: Key
    template_id: str | None = None
    custom_chords: tuple[CustomChord, ...] = ()
    tempo: int = 80
    time_signature: tuple[int, int] = (4, 4)
    tags: tuple[str, ...] = ()
    theory_explanation: str = ""
    practice: Mapping[str, str] = field(default_factory=dict)  # per level; falls back to default
    variations: tuple[str, ...] = ()  # author's own, appended to the generated ones
    levels: tuple[Level, ...] = LEVELS
    author: str | None = None
    source: str | None = None
    schema_version: int = MOVEMENT_SCHEMA_VERSION


def make_slug(name: str) -> str:
    out, prev_dash = [], True
    for ch in name.lower():
        if ch.isascii() and ch.isalnum():
            out.append(ch)
            prev_dash = False
        elif not prev_dash:
            out.append("-")
            prev_dash = True
    slug = "".join(out).strip("-")
    return slug[:80] or "movement"


def check_definition(d: MovementDefinition, library: ProgressionLibrary | None = None) -> None:
    """Structural checks that do not need the engine to build anything."""
    if not d.name.strip() or len(d.name) > 120:
        raise _bad("Name must be 1-120 characters.", "invalid_name")
    if (d.template_id is None) == (not d.custom_chords):
        raise _bad(
            "Give either a template_id or a list of custom chords, not both and not neither.",
            "invalid_source",
        )
    if not 20 <= d.tempo <= 300:
        raise _bad("Tempo must be between 20 and 300 BPM.", "invalid_tempo")
    num, den = d.time_signature
    if num < 1 or num > 16 or den not in (2, 4, 8, 16):
        raise _bad("Time signature must be like 4/4 or 6/8.", "invalid_time_signature")
    if len(d.tags) > MAX_TAGS or any(not t.strip() or len(t) > 32 for t in d.tags):
        raise _bad(f"At most {MAX_TAGS} tags of 1-32 characters.", "invalid_tags")
    for label, text in (("theory_explanation", d.theory_explanation), *d.practice.items()):
        if len(text) > MAX_TEXT:
            raise _bad(f"{label} is longer than {MAX_TEXT} characters.", "text_too_long")
    unknown = set(d.practice) - set(LEVELS)
    if unknown:
        raise _bad(
            f"Unknown level in practice text: {', '.join(sorted(unknown))}.", "unknown_level"
        )
    if (
        not d.levels
        or len(set(d.levels)) != len(d.levels)
        or any(x not in LEVELS for x in d.levels)
    ):
        raise _bad("levels must be a non-empty list of distinct level names.", "unknown_level")
    if d.template_id is not None:
        (library or default_library()).get(d.template_id)  # raises with a stable code
    else:
        check_count("chords", len(d.custom_chords), MAX_VOICED_CHORDS)
        for c in d.custom_chords:
            if not 0 < c.beats <= 32:
                raise _bad("Each chord lasts between 0 and 32 beats.", "invalid_duration")


# ------------------------------------------------------------------ built output


@dataclass(frozen=True)
class MovementStep:
    index: int
    symbol: str
    roman: str | None
    beat: float
    duration: float
    role: str
    chord_tones: tuple[str, ...]
    bass: str
    inversion: str  # plain words, from the lowest sounding note
    left: tuple[int, ...]
    right: tuple[int, ...]
    left_names: tuple[str, ...]
    right_names: tuple[str, ...]
    voicing_type: str
    omitted: tuple[str, ...]
    tensions: tuple[str, ...]
    explanation: tuple[str, ...]
    cost: float


@dataclass(frozen=True)
class PlaybackEvent:
    midi: int
    hand: Literal["L", "R"]
    start_beat: float
    duration_beats: float
    chord_index: int
    velocity: int = 80


@dataclass(frozen=True)
class MovementVersion:
    level: Level
    progression: Progression
    steps: tuple[MovementStep, ...]
    playback: tuple[PlaybackEvent, ...]
    voicing_type: str
    theory_explanation: str
    practice: str
    variations: tuple[str, ...]
    total_cost: float
    method: str
    warnings: tuple[str, ...]  # voice-leading notes (relaxed leap limit etc.)
    validation_errors: tuple[str, ...]
    validation_warnings: tuple[str, ...]


@dataclass(frozen=True)
class BuiltMovement:
    slug: str
    definition: MovementDefinition
    versions: tuple[MovementVersion, ...]
    transposition_options: tuple[str, ...]
    generator_version: int = GENERATOR_VERSION

    def version(self, level: str) -> MovementVersion:
        for v in self.versions:
            if v.level == level:
                return v
        raise _bad(f"This movement has no {level} version.", "unknown_level")


# ------------------------------------------------------------------ building


_INVERSION_WORDS = {0: "root position", 1: "first inversion", 2: "second inversion",
                    3: "third inversion"}  # fmt: skip


def _inversion_text(chord: Chord, voicing: Voicing) -> str:
    notes = voiced_notes(chord, voicing)
    if not notes:
        return "no notes"
    low = notes[0]
    tones = chord.tones()
    for i, tone in enumerate(tones):
        if tone.pitch_class == low.name.pitch_class and low.role != "tension":
            return _INVERSION_WORDS.get(i, f"inversion {i}")
    return "bass note outside the chord" if low.role == "unknown" else "chord tone in the bass"


def _voicing_type(v: Voicing) -> str:
    return f"{v.lh_style} + {v.rh_style}".replace("_", " ")


def _generated_variations(
    d: MovementDefinition, level: Level, prog: Progression, subs: int
) -> tuple[str, ...]:
    out = []
    nxt = LEVELS[LEVELS.index(level) + 1] if level != "expert" else None
    if nxt and nxt in d.levels:
        out.append(f"When this feels easy, move to the {nxt} version.")
    out.append("Play it in a new key; the transposition options list every key.")
    if level in ("beginner", "intermediate"):
        out.append("Try each chord in a different inversion, keeping the notes close together.")
    if level == "expert" and subs == 0:
        out.append("No chord here resolves down a fifth, so no tritone substitute was applied.")
    if level in ("advanced", "expert"):
        out.append("Swap the left-hand shell for a root-and-fifth to hear what the shell adds.")
    return (*out, *d.variations)


def _default_practice(level: Level, name: str) -> str:
    return {
        "beginner": f"Play {name} one chord at a time, hands together, "
        "saying each chord name aloud.",
        "intermediate": f"Play {name} with seventh chords; keep the hand shape and slide to the "
        "nearest inversion rather than jumping.",
        "advanced": f"Play {name} with guide tones: find the third and seventh of each chord and "
        "notice which move by a half or whole step.",
        "expert": f"Play {name} from memory in three keys, then add the substitution and tensions "
        "one at a time.",
    }[level]


def _base_progression(
    d: MovementDefinition, level: Level, library: ProgressionLibrary
) -> Progression:
    recipe = RECIPES[level]
    if d.template_id is not None:
        tpl: ProgressionTemplate = library.get(d.template_id)
        prog = realize(tpl, d.key, recipe.vocabulary, tempo=d.tempo, difficulty=level)
        return replace(prog, name=d.name)
    # Custom chords are used as written at every level: the author chose the vocabulary.
    chords: list[str] = [c.symbol for c in d.custom_chords]
    prog = make_progression(
        d.name, d.key, chords, beats=[c.beats for c in d.custom_chords],
        time_signature=d.time_signature, tempo=d.tempo, difficulty=level,
    )  # fmt: skip
    return prog


def _apply_substitutions(prog: Progression) -> tuple[Progression, int]:
    """Tritone-substitute dominants that resolve down a fifth. Indices are stable (1:1)."""
    count = 0
    for i, pc in enumerate(prog.chords[:-1]):
        if pc.chord.type.id not in _TRITONE_SUBBABLE or pc.chord.bass is not None:
            continue
        nxt = prog.chords[i + 1].chord
        if (pc.chord.root.pitch_class - nxt.root.pitch_class) % 12 != 7:
            continue
        try:
            prog = substitute_tritone(prog, i)
        except TheoryError:  # a type we did not anticipate: leave the chord as written
            continue
        count += 1
    return prog, count


def _constraints(recipe: LevelRecipe) -> VoicingConstraints:
    return constraints_for_skill(recipe.level, **dict(recipe.constraint_overrides))


def _build_version(
    d: MovementDefinition, level: Level, library: ProgressionLibrary
) -> MovementVersion:
    recipe = RECIPES[level]
    prog = _base_progression(d, level, library)
    subs = 0
    if recipe.substitutions:
        prog, subs = _apply_substitutions(prog)
    constraints = _constraints(recipe)
    voiced_prog, voiced = voice_progression(
        prog, constraints, config_for(recipe.style, recipe.weights), preset=recipe.preset
    )
    voiced_prog = replace(
        voiced_prog,
        tempo=d.tempo,
        styles=tuple(dict.fromkeys((*d.tags, *voiced_prog.styles))),
        difficulty=level,
        explanation=d.theory_explanation or voiced_prog.explanation,
    )
    steps, events = [], []
    for i, (pc, item) in enumerate(zip(voiced_prog.chords, voiced.items, strict=True)):
        v = item.voicing
        vn = voiced_notes(pc.chord, v)
        names = {n.midi: str(n.name) for n in vn}
        steps.append(
            MovementStep(
                index=i, symbol=format_chord(pc.chord), roman=pc.roman, beat=pc.beat,
                duration=pc.duration, role=pc.role,
                chord_tones=tuple(str(t) for t in pc.chord.tones()),
                bass=str(pc.chord.bass_name), inversion=_inversion_text(pc.chord, v),
                left=v.left, right=v.right,
                left_names=tuple(names.get(m, "?") for m in v.left),
                right_names=tuple(names.get(m, "?") for m in v.right),
                voicing_type=_voicing_type(v), omitted=v.omitted, tensions=v.tensions,
                explanation=item.explanation, cost=round(item.cost, 3),
            )
        )  # fmt: skip
        for hand, notes in (("L", v.left), ("R", v.right)):
            for m in notes:
                events.append(PlaybackEvent(m, hand, pc.beat, pc.duration, i))  # type: ignore[arg-type]
    report = validate_progression(voiced_prog, constraints=constraints)
    return MovementVersion(
        level=level,
        progression=voiced_prog,
        steps=tuple(steps),
        playback=tuple(sorted(events, key=lambda e: (e.start_beat, e.hand, e.midi))),
        voicing_type=recipe.voicing_type,
        theory_explanation=d.theory_explanation or voiced_prog.explanation,
        practice=d.practice.get(level) or _default_practice(level, d.name),
        variations=_generated_variations(d, level, voiced_prog, subs),
        total_cost=round(voiced.total_cost, 3),
        method=voiced.method,
        warnings=voiced.warnings,
        validation_errors=tuple(f"{i.code}: {i.message}" for i in report.errors),
        validation_warnings=tuple(f"{i.code}: {i.message}" for i in report.warnings),
    )


def transposition_options(d: MovementDefinition) -> tuple[str, ...]:
    """Every key of the same mode (flat spellings for flat keys). Spelling is chosen per key by
    `transpose_progression` / `realize`, not here."""
    majors = ("C", "Db", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B")
    minors = ("C", "C#", "D", "Eb", "E", "F", "F#", "G", "G#", "A", "Bb", "B")
    return majors if d.key.mode == "major" else minors


def build_movement(
    d: MovementDefinition, *, slug: str | None = None, library: ProgressionLibrary | None = None
) -> BuiltMovement:
    """Build every requested level. Deterministic: the same definition gives the same result."""
    lib = library or default_library()
    check_definition(d, lib)
    versions = tuple(_build_version(d, lvl, lib) for lvl in LEVELS if lvl in d.levels)
    return BuiltMovement(slug or make_slug(d.name), d, versions, transposition_options(d))


def in_key(d: MovementDefinition, tonic: str) -> MovementDefinition:
    """The same movement in another key of the same mode (templates are re-realised from their
    Roman numerals; custom chords are transposed by interval with respelling)."""
    new_key = parse_key(tonic, d.key.mode)
    if d.template_id is not None:
        return replace(d, key=new_key)
    base = _base_progression(d, "beginner", default_library())
    moved = transpose_progression(base, new_key, on_unplayable="revoice").progression
    chords = tuple(CustomChord(format_chord(pc.chord), pc.duration) for pc in moved.chords)
    return replace(d, key=new_key, custom_chords=chords)


# ------------------------------------------------------------------ definition <-> dict


def definition_to_dict(d: MovementDefinition) -> dict[str, Any]:
    return {
        "schema_version": d.schema_version,
        "name": d.name,
        "key": {"tonic": str(d.key.tonic), "mode": d.key.mode},
        "template_id": d.template_id,
        "custom_chords": [{"symbol": c.symbol, "beats": c.beats} for c in d.custom_chords],
        "tempo": d.tempo,
        "time_signature": list(d.time_signature),
        "tags": list(d.tags),
        "theory_explanation": d.theory_explanation,
        "practice": dict(d.practice),
        "variations": list(d.variations),
        "levels": list(d.levels),
        "author": d.author,
        "source": d.source,
    }


def definition_from_dict(data: Mapping[str, Any]) -> MovementDefinition:
    """Strict: a missing or wrongly typed field names itself in the error."""
    if not isinstance(data, Mapping):
        raise _bad("A movement must be an object.", "invalid_movement_data")
    version = data.get("schema_version", MOVEMENT_SCHEMA_VERSION)
    if version != MOVEMENT_SCHEMA_VERSION:
        raise _bad(
            f"Movement data has schema version {version!r}; this server reads "
            f"{MOVEMENT_SCHEMA_VERSION}.",
            "unsupported_movement_version",
        )

    def field_of(name: str, kind: type | tuple[type, ...], default: Any = ...) -> Any:
        if name not in data:
            if default is ...:
                raise _bad(f"Missing field '{name}'.", "invalid_movement_data")
            return default
        val = data[name]
        if isinstance(val, bool) and bool not in (kind if isinstance(kind, tuple) else (kind,)):
            raise _bad(f"Field '{name}' has the wrong type.", "invalid_movement_data")
        if not isinstance(val, kind):
            raise _bad(f"Field '{name}' has the wrong type.", "invalid_movement_data")
        return val

    key = field_of("key", Mapping)
    ts = field_of("time_signature", (list, tuple), [4, 4])
    if len(ts) != 2 or not all(isinstance(x, int) for x in ts):
        raise _bad("time_signature must be two integers.", "invalid_time_signature")
    customs = []
    for i, c in enumerate(field_of("custom_chords", (list, tuple), [])):
        if not isinstance(c, Mapping) or not isinstance(c.get("symbol"), str):
            raise _bad(f"custom_chords[{i}] needs a text 'symbol'.", "invalid_movement_data")
        beats = c.get("beats", 4.0)
        if isinstance(beats, bool) or not isinstance(beats, int | float):
            raise _bad(f"custom_chords[{i}].beats must be a number.", "invalid_movement_data")
        customs.append(CustomChord(c["symbol"], float(beats)))
    practice = field_of("practice", Mapping, {})
    if not all(isinstance(k, str) and isinstance(v, str) for k, v in practice.items()):
        raise _bad("practice must map level names to text.", "invalid_movement_data")

    def str_list(name: str) -> tuple[str, ...]:
        return tuple(str(x) for x in field_of(name, (list, tuple), []))

    levels = str_list("levels") or LEVELS
    return MovementDefinition(
        name=str(field_of("name", str)),
        key=parse_key(str(key.get("tonic", "")), str(key.get("mode", "major"))),
        template_id=field_of("template_id", (str, type(None)), None),
        custom_chords=tuple(customs),
        tempo=field_of("tempo", int, 80),
        time_signature=(ts[0], ts[1]),
        tags=str_list("tags"),
        theory_explanation=str(field_of("theory_explanation", str, "")),
        practice=dict(practice),
        variations=str_list("variations"),
        levels=levels,  # type: ignore[arg-type]
        author=field_of("author", (str, type(None)), None),
        source=field_of("source", (str, type(None)), None),
    )


# ------------------------------------------------------------------ lifecycle


@dataclass(frozen=True)
class HistoryEntry:
    revision: int
    at: str  # ISO 8601, UTC
    by: str
    action: str
    note: str = ""
    from_status: str | None = None
    to_status: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "revision": self.revision, "at": self.at, "by": self.by, "action": self.action,
            "note": self.note, "from_status": self.from_status, "to_status": self.to_status,
        }  # fmt: skip


def history_from_dicts(items: Sequence[Mapping[str, Any]]) -> list[HistoryEntry]:
    return [
        HistoryEntry(
            int(i["revision"]), str(i["at"]), str(i["by"]), str(i["action"]),
            str(i.get("note", "")), i.get("from_status"), i.get("to_status"),
        )
        for i in items
    ]  # fmt: skip


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def check_transition(current: str, target: str) -> str:
    """The audit-log action name for a move, or a stable error."""
    if current not in TRANSITIONS or target not in STATUSES:
        raise _bad(f"Unknown status {current!r} -> {target!r}.", "unknown_status")
    if target not in TRANSITIONS[current]:
        allowed = ", ".join(TRANSITIONS[current]) or "none"
        raise _bad(
            f"A {current.replace('_', ' ')} movement cannot become {target.replace('_', ' ')}. "
            f"Allowed: {allowed}.",
            "invalid_transition",
        )
    return ACTION_FOR_MOVE.get((current, target), "archive" if target == "archived" else target)


def publication_blockers(built: BuiltMovement) -> list[str]:
    """Why this movement cannot be published. Empty means it can.

    Publication needs: author, explanation, at least one tag, and every version free of
    validation errors, with the engine's `publication` requirements on each progression.
    """
    problems: list[str] = []
    d = built.definition
    if not d.author:
        problems.append("Add an author.")
    if not d.theory_explanation.strip():
        problems.append("Add a theory explanation.")
    if not d.tags:
        problems.append("Add at least one tag (style, genre or topic).")
    for v in built.versions:
        for msg in v.validation_errors:
            problems.append(f"{v.level}: {msg}")
        pub = validate_progression(
            replace(v.progression, meta=replace(v.progression.meta, author=d.author or "")),
            publication=True,
        )
        for issue in pub.errors:
            text = f"{v.level}: {issue.code}: {issue.message}"
            if text not in problems and not any(issue.message in p for p in problems):
                problems.append(text)
    return problems


# ------------------------------------------------------------------ built output -> JSON


def version_to_dict(v: MovementVersion) -> dict[str, Any]:
    return {
        "level": v.level,
        "voicing_type": v.voicing_type,
        "theory_explanation": v.theory_explanation,
        "practice": v.practice,
        "variations": list(v.variations),
        "total_cost": v.total_cost,
        "method": v.method,
        "warnings": list(v.warnings),
        "validation_errors": list(v.validation_errors),
        "validation_warnings": list(v.validation_warnings),
        "tempo": v.progression.tempo,
        "time_signature": list(v.progression.time_signature),
        "total_beats": v.progression.total_beats,
        "steps": [
            {
                "index": s.index, "symbol": s.symbol, "roman": s.roman, "beat": s.beat,
                "duration": s.duration, "role": s.role, "chord_tones": list(s.chord_tones),
                "bass": s.bass, "inversion": s.inversion, "left": list(s.left),
                "right": list(s.right), "left_names": list(s.left_names),
                "right_names": list(s.right_names), "voicing_type": s.voicing_type,
                "omitted": list(s.omitted), "tensions": list(s.tensions),
                "explanation": list(s.explanation), "cost": s.cost,
            }
            for s in v.steps
        ],
        "playback": [
            {
                "midi": e.midi, "hand": e.hand, "start_beat": e.start_beat,
                "duration_beats": e.duration_beats, "chord_index": e.chord_index,
                "velocity": e.velocity,
            }
            for e in v.playback
        ],
    }  # fmt: skip


def built_to_dict(b: BuiltMovement) -> dict[str, Any]:
    """The frozen form stored at publication. `generator_version` says which engine made it."""
    return {
        "schema_version": MOVEMENT_SCHEMA_VERSION,
        "generator_version": b.generator_version,
        "slug": b.slug,
        "name": b.definition.name,
        "key": {"tonic": str(b.definition.key.tonic), "mode": b.definition.key.mode},
        "tempo": b.definition.tempo,
        "time_signature": list(b.definition.time_signature),
        "tags": list(b.definition.tags),
        "author": b.definition.author,
        "source": b.definition.source,
        "template_id": b.definition.template_id,
        "transposition_options": list(b.transposition_options),
        "versions": [version_to_dict(v) for v in b.versions],
    }  # fmt: skip
