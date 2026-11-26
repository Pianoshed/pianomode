"""Chord progressions as validated, versioned objects.

A progression holds structured chords (not strings), their timing, optional Roman numerals and
voicings. Templates are data (`data/progressions.json`); realising one in a key goes through the
Roman-numeral parser, so spelling is always correct for the key. Transposition re-derives every
chord from its numeral rather than shifting letters, so transposed charts are spelled properly.
"""

from __future__ import annotations

import json
import math
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from functools import cache
from importlib import resources
from typing import Any, Literal

from music_theory.chord_symbols import format_chord, parse_chord
from music_theory.chords import Chord, chord_type
from music_theory.errors import TheoryError
from music_theory.intervals import P5, d5, interval_between_names, m2, transpose_name
from music_theory.key_analysis import ALL_KEYS
from music_theory.keys import Key
from music_theory.notes import NoteName, parse_note_name
from music_theory.roman import analyze_chord, chord_from_roman
from music_theory.voice_leading import (
    STYLE_PROFILES,
    VoicedProgression,
    VoiceLeadingConfig,
    config_for,
    voice_chords,
)
from music_theory.voicings import (
    SKILLS,
    Voicing,
    VoicingConstraints,
    constraints_for_skill,
    playability_issues,
)

SCHEMA_VERSION = 1
Difficulty = Literal["beginner", "intermediate", "advanced", "expert"]
Vocabulary = Literal["triads", "sevenths"]
Role = Literal["main", "passing", "substitution"]
STATUSES = ("draft", "under_review", "approved", "published", "archived")
ROLES = ("main", "passing", "substitution")
_EPS = 1e-9


class ProgressionError(TheoryError):
    code = "invalid_progression"


@dataclass(frozen=True)
class ProgressionChord:
    chord: Chord
    beat: float  # start, in beats from the beginning of the progression
    duration: float  # in beats
    roman: str | None = None
    role: Role = "main"
    substitution_for: str | None = None  # symbol of the chord this one replaces
    voicing: Voicing | None = None  # hands are part of the voicing: left / right
    explanation: str = ""

    @property
    def end(self) -> float:
        return self.beat + self.duration


@dataclass(frozen=True)
class PublicationMeta:
    author: str | None = None
    source: str | None = None
    status: str = "draft"
    revision: int = 1


@dataclass(frozen=True)
class Progression:
    name: str
    key: Key
    chords: tuple[ProgressionChord, ...]
    time_signature: tuple[int, int] = (4, 4)
    tempo: int | None = None
    difficulty: Difficulty = "beginner"
    styles: tuple[str, ...] = ()
    explanation: str = ""
    scale_id: str | None = None  # harmonic context; defaults to the key's own scale
    template_id: str | None = None
    meta: PublicationMeta = PublicationMeta()
    schema_version: int = SCHEMA_VERSION

    @property
    def scale(self) -> str:
        return self.scale_id or ("major" if self.key.mode == "major" else "natural_minor")

    @property
    def total_beats(self) -> float:
        return max((c.end for c in self.chords), default=0.0)

    @property
    def beats_per_bar(self) -> float:
        num, den = self.time_signature
        return num * 4 / den if den else 0.0


# ------------------------------------------------------------------ templates


class TemplateError(TheoryError):
    code = "invalid_progression_template"


@dataclass(frozen=True)
class TemplateChord:
    triads: str
    sevenths: str
    beats: float


@dataclass(frozen=True)
class ProgressionTemplate:
    id: str
    name: str
    mode: str
    difficulty: Difficulty
    styles: tuple[str, ...]
    explanation: str
    practice: str
    time_signature: tuple[int, int]
    chords: tuple[TemplateChord, ...]


def _parse_template(data: Mapping[str, Any]) -> ProgressionTemplate:
    def fail(msg: str) -> TemplateError:
        return TemplateError(f"Template {data.get('id', '?')!r}: {msg}")

    try:
        mode = str(data["mode"])
        if mode not in ("major", "minor"):
            raise fail("mode must be 'major' or 'minor'")
        difficulty = str(data["difficulty"])
        if difficulty not in SKILLS:
            raise fail(f"difficulty must be one of {', '.join(SKILLS)}")
        raw_chords = data["chords"]
        if not isinstance(raw_chords, list) or not raw_chords:
            raise fail("chords must be a non-empty list")
        ref = Key(parse_note_name("C" if mode == "major" else "A"), mode)
        chords = []
        for i, c in enumerate(raw_chords):
            beats = float(c["beats"])
            if not math.isfinite(beats) or beats <= 0:
                raise fail(f"chord {i + 1} needs a positive length in beats")
            for field in ("triads", "sevenths"):
                try:
                    chord_from_roman(str(c[field]), ref)
                except TheoryError as exc:
                    raise fail(f"chord {i + 1} {field}: {exc.message}") from exc
            chords.append(TemplateChord(str(c["triads"]), str(c["sevenths"]), beats))
        ts = data.get("time_signature", [4, 4])
        return ProgressionTemplate(
            id=str(data["id"]),
            name=str(data["name"]),
            mode=mode,
            difficulty=difficulty,  # type: ignore[arg-type]
            styles=tuple(str(s) for s in data.get("styles", [])),
            explanation=str(data.get("explanation", "")),
            practice=str(data.get("practice", "")),
            time_signature=(int(ts[0]), int(ts[1])),
            chords=tuple(chords),
        )
    except KeyError as exc:
        raise fail(f"missing field {exc.args[0]!r}") from exc
    except (TypeError, ValueError, IndexError) as exc:
        raise fail(f"malformed field ({exc})") from exc


def load_templates(json_text: str) -> list[ProgressionTemplate]:
    try:
        payload = json.loads(json_text)
    except json.JSONDecodeError as exc:
        raise TemplateError(f"Invalid JSON: {exc.msg}") from exc
    items = payload.get("progressions") if isinstance(payload, dict) else None
    if not isinstance(items, list):
        raise TemplateError('Expected {"progressions": [...]}')
    return [_parse_template(i) for i in items]


class ProgressionLibrary:
    def __init__(self, templates: Iterable[ProgressionTemplate] = ()) -> None:
        self._by_id: dict[str, ProgressionTemplate] = {}
        for t in templates:
            self.register(t)

    def register(self, template: ProgressionTemplate, *, replace_existing: bool = False) -> None:
        if template.id in self._by_id and not replace_existing:
            raise TemplateError(f"Template {template.id!r} already exists")
        self._by_id[template.id] = template

    def get(self, template_id: str) -> ProgressionTemplate:
        try:
            return self._by_id[template_id]
        except KeyError:
            raise TheoryError(
                f"Unknown progression {template_id!r}", code="unknown_progression"
            ) from None

    def ids(self) -> list[str]:
        return list(self._by_id)

    def search(
        self, *, style: str | None = None, difficulty: str | None = None, mode: str | None = None
    ) -> list[ProgressionTemplate]:
        return [
            t for t in self._by_id.values()
            if (style is None or style in t.styles)
            and (difficulty is None or t.difficulty == difficulty)
            and (mode is None or t.mode == mode)
        ]  # fmt: skip

    def copy(self) -> ProgressionLibrary:
        return ProgressionLibrary(self._by_id.values())


@cache
def default_library() -> ProgressionLibrary:
    """Built-in templates; call `.copy()` before registering extras."""
    text = resources.files("music_theory.data").joinpath("progressions.json").read_text("utf-8")
    return ProgressionLibrary(load_templates(text))


def realize(
    template: ProgressionTemplate,
    key: Key,
    vocabulary: Vocabulary = "triads",
    *,
    tempo: int | None = None,
    difficulty: Difficulty | None = None,
) -> Progression:
    """Turn a template into chords in `key`. The vocabulary picks triads or seventh chords."""
    if key.mode != template.mode:
        raise TheoryError(
            f"{template.name} is a {template.mode}-key progression; got {key}",
            code="key_mode_mismatch",
        )
    if vocabulary not in ("triads", "sevenths"):
        raise TheoryError("Vocabulary must be 'triads' or 'sevenths'", code="invalid_vocabulary")
    beat = 0.0
    out = []
    for tc in template.chords:
        numeral = tc.triads if vocabulary == "triads" else tc.sevenths
        out.append(ProgressionChord(chord_from_roman(numeral, key), beat, tc.beats, roman=numeral))
        beat += tc.beats
    chosen = difficulty or (
        template.difficulty
        if vocabulary == "triads" or template.difficulty != "beginner"
        else "intermediate"
    )
    return Progression(
        name=f"{template.name} in {key}",
        key=key,
        chords=tuple(out),
        time_signature=template.time_signature,
        tempo=tempo,
        difficulty=chosen,
        styles=template.styles,
        explanation=template.explanation,
        template_id=template.id,
    )


def generate_progression(
    template_id: str,
    key: Key,
    vocabulary: Vocabulary = "triads",
    *,
    library: ProgressionLibrary | None = None,
    tempo: int | None = None,
) -> Progression:
    return realize((library or default_library()).get(template_id), key, vocabulary, tempo=tempo)


def make_progression(
    name: str,
    key: Key,
    chords: Sequence[str | Chord],
    *,
    beats: float | Sequence[float] = 4.0,
    **fields: Any,
) -> Progression:
    """Build a custom progression from chord symbols (or Chords); numerals come from analysis."""
    durations = [beats] * len(chords) if isinstance(beats, int | float) else list(beats)
    if len(durations) != len(chords):
        raise TheoryError("One duration per chord", code="length_mismatch")
    out, beat = [], 0.0
    for c, d in zip(chords, durations, strict=True):
        chord = parse_chord(c) if isinstance(c, str) else c
        out.append(ProgressionChord(chord, beat, float(d), roman=analyze_chord(chord, key).figure))
        beat += float(d)
    return Progression(name=name, key=key, chords=tuple(out), **fields)


def with_analysis(prog: Progression) -> Progression:
    """Fill in Roman numerals for chords that do not have one."""
    chords = tuple(
        c if c.roman else replace(c, roman=analyze_chord(c.chord, prog.key).figure)
        for c in prog.chords
    )
    return replace(prog, chords=chords)


# ------------------------------------------------------------------ transposition


@dataclass(frozen=True)
class TranspositionResult:
    progression: Progression
    shift_semitones: int  # shortest signed shift applied to any voicing (-6..+5)
    revoiced: bool
    warnings: tuple[str, ...]


def _respell(pc: int, key: Key) -> NoteName:
    return key.signature.spell(pc)


def _new_root(pc: ProgressionChord, old: Key, new: Key, iv_semis: int, iv: Any) -> NoteName:
    chord = pc.chord
    if pc.roman:
        try:
            if chord_from_roman(pc.roman, old).root == chord.root:
                return chord_from_roman(pc.roman, new).root
        except TheoryError:
            pass  # numeral missing/unparseable/wrong: fall back to interval transposition
    try:
        return transpose_name(chord.root, iv)
    except TheoryError:
        return _respell((chord.root.pitch_class + iv_semis) % 12, new)


def _transposed_chord(pc: ProgressionChord, old: Key, new: Key, iv_semis: int, iv: Any) -> Chord:
    chord = pc.chord
    root = _new_root(pc, old, new, iv_semis, iv)
    bass = None
    if chord.bass is not None:
        rel = interval_between_names(chord.root, chord.bass)
        try:
            bass = transpose_name(root, rel)
        except TheoryError:
            bass = _respell(
                (root.pitch_class + (chord.bass.pitch_class - chord.root.pitch_class)) % 12, new
            )
    return Chord(root, chord.type, bass)


def _shift_symbol(symbol: str, new: Key, iv: Any, iv_semis: int) -> str:
    chord = parse_chord(symbol)
    try:
        root = transpose_name(chord.root, iv)
        bass = None if chord.bass is None else transpose_name(chord.bass, iv)
    except TheoryError:
        root = _respell((chord.root.pitch_class + iv_semis) % 12, new)
        bass = (
            None if chord.bass is None else _respell((chord.bass.pitch_class + iv_semis) % 12, new)
        )
    return format_chord(Chord(root, chord.type, bass))


def transpose_progression(
    prog: Progression,
    target: Key | NoteName | str,
    *,
    constraints: VoicingConstraints | None = None,
    config: VoiceLeadingConfig | None = None,
    on_unplayable: Literal["revoice", "drop", "error"] = "revoice",
) -> TranspositionResult:
    """Move a progression to another key of the same mode.

    Chord quality, Roman numerals, bass relationships, timing, roles and notes are preserved.
    Voicings move by the shortest semitone shift; if any shifted voicing is not playable under
    `constraints`, `on_unplayable` decides: "revoice" regenerates all voicings smoothly,
    "drop" removes the unplayable ones, "error" raises.
    """
    if isinstance(target, str):
        target = parse_note_name(target)
    new_key = Key(target, prog.key.mode) if isinstance(target, NoteName) else target
    if new_key.mode != prog.key.mode:
        raise TheoryError(
            "Transposition keeps the mode; use a key of the same mode", code="mode_change"
        )
    old_key = prog.key
    iv = interval_between_names(old_key.tonic, new_key.tonic)
    iv_semis = iv.semitones % 12
    shift = ((new_key.tonic.pitch_class - old_key.tonic.pitch_class + 6) % 12) - 6
    c = constraints or constraints_for_skill(prog.difficulty)

    chords = []
    warnings: list[str] = []
    unplayable = False
    for i, pc in enumerate(prog.chords):
        chord = _transposed_chord(pc, old_key, new_key, iv_semis, iv)
        voicing = None
        if pc.voicing is not None:
            v = pc.voicing
            moved = replace(
                v, left=tuple(n + shift for n in v.left), right=tuple(n + shift for n in v.right)
            )
            issues = playability_issues(moved, c)
            if issues:
                unplayable = True
                warnings.append(
                    f"Chord {i + 1} ({chord}): shifted voicing not playable ({issues[0]})."
                )
            else:
                voicing = moved
        sub = (
            _shift_symbol(pc.substitution_for, new_key, iv, iv_semis)
            if pc.substitution_for
            else None
        )
        chords.append(replace(pc, chord=chord, voicing=voicing, substitution_for=sub))

    result = replace(prog, key=new_key, chords=tuple(chords))
    revoiced = False
    if unplayable:
        if on_unplayable == "error":
            raise TheoryError(warnings[0], code="unplayable_voicing")
        if on_unplayable == "revoice":
            result, _ = voice_progression(result, c, config)
            revoiced = True
            warnings.append("Voicings were regenerated for the new key.")
        else:
            warnings.append("Unplayable voicings were removed.")
    return TranspositionResult(result, shift, revoiced, tuple(warnings))


def transpose_to_all_keys(prog: Progression) -> dict[str, TranspositionResult]:
    """Transpose into the twelve standard keys of the progression's mode."""
    return {
        str(k.tonic): transpose_progression(prog, k.tonic)
        for k in ALL_KEYS
        if k.mode == prog.key.mode
    }


# ------------------------------------------------------------ substitutions and passing chords

_TRITONE_SUBBABLE = {"dominant7", "dominant9", "dominant13"}
_NO_DOMINANT_TARGET = {"diminished", "diminished7", "half_diminished7"}


def _check_index(prog: Progression, index: int) -> ProgressionChord:
    if not 0 <= index < len(prog.chords):
        raise TheoryError(f"No chord at position {index + 1}", code="invalid_index")
    return prog.chords[index]


def substitute_tritone(prog: Progression, index: int) -> Progression:
    """Replace a dominant chord with the dominant a tritone away (G7 -> Db7). They share the
    third and seventh, so the voice leading into the resolution is the same."""
    pc = _check_index(prog, index)
    if pc.chord.type.id not in _TRITONE_SUBBABLE:
        raise TheoryError(
            f"{pc.chord} is not a dominant chord; only dominants have a tritone substitute",
            code="invalid_substitution",
        )
    new_root = transpose_name(pc.chord.root, d5)
    simpler = _respell(new_root.pitch_class, prog.key)
    if abs(simpler.accidental) < abs(new_root.accidental):
        new_root = simpler  # Ab -> Ebb and Bb -> Fb are right by intervals; charts write D and E
    new = Chord(new_root, pc.chord.type)
    sub = replace(
        pc,
        chord=new,
        roman=analyze_chord(new, prog.key).figure,
        role="substitution",
        substitution_for=format_chord(pc.chord),
        voicing=None,
        explanation=f"Tritone substitution for {pc.chord}: shares its third and seventh.",
    )
    return replace(prog, chords=(*prog.chords[:index], sub, *prog.chords[index + 1 :]))


def insert_secondary_dominant(prog: Progression, index: int) -> Progression:
    """Insert V7 of the chord at `index` in the first half of its time."""
    target = _check_index(prog, index)
    if target.chord.type.id in _NO_DOMINANT_TARGET:
        raise TheoryError(
            f"{target.chord} is not a stable target for a secondary dominant",
            code="invalid_target",
        )
    if target.duration < 1:
        raise TheoryError("The chord is too short to split", code="chord_too_short")
    half = target.duration / 2
    new = Chord(transpose_name(target.chord.root, P5), chord_type("dominant7"))
    inserted = ProgressionChord(
        new, target.beat, half, analyze_chord(new, prog.key).figure, "passing", None, None,
        f"Secondary dominant leading to {target.chord}.",
    )  # fmt: skip
    shortened = replace(target, beat=target.beat + half, duration=half)
    return replace(
        prog, chords=(*prog.chords[:index], inserted, shortened, *prog.chords[index + 1 :])
    )


def insert_passing_diminished(prog: Progression, index: int) -> Progression:
    """Insert a diminished seventh a half step below the next chord's root, in the second half
    of the chord at `index` (C -> C#dim7 -> Dm7)."""
    prev = _check_index(prog, index)
    if index + 1 >= len(prog.chords):
        raise TheoryError("There is no following chord to lead into", code="invalid_index")
    nxt = prog.chords[index + 1]
    if prev.duration < 1:
        raise TheoryError("The chord is too short to split", code="chord_too_short")
    half = prev.duration / 2
    new = Chord(transpose_name(nxt.chord.root, m2, down=True), chord_type("diminished7"))
    shortened = replace(prev, duration=half)
    inserted = ProgressionChord(
        new, prev.beat + half, half, analyze_chord(new, prog.key).figure, "passing", None, None,
        f"Passing diminished chord leading to {nxt.chord}.",
    )  # fmt: skip
    return replace(
        prog, chords=(*prog.chords[:index], shortened, inserted, *prog.chords[index + 1 :])
    )


# ------------------------------------------------------------------ voicing a progression


def voice_progression(
    prog: Progression,
    constraints: VoicingConstraints | None = None,
    config: VoiceLeadingConfig | None = None,
    *,
    preset: str | None = None,
    fixed: Mapping[int, Voicing] | None = None,
) -> tuple[Progression, VoicedProgression]:
    """Assign a smooth sequence of voicings to every chord. Constraints default to the
    progression's difficulty; the style comes from its first recognised style tag."""
    c = constraints or constraints_for_skill(prog.difficulty)
    if config is None:
        style = next((s for s in prog.styles if s in STYLE_PROFILES), "pop")
        config = config_for(style, "smooth")
    voiced = voice_chords(
        [p.chord for p in prog.chords], c, config=config, preset=preset, fixed=fixed
    )
    chords = tuple(
        replace(pc, voicing=item.voicing)
        for pc, item in zip(prog.chords, voiced.items, strict=True)
    )
    return replace(prog, chords=chords), voiced


# ------------------------------------------------------------------ validation


@dataclass(frozen=True)
class ValidationIssue:
    severity: Literal["error", "warning"]
    code: str
    message: str
    index: int | None = None


@dataclass(frozen=True)
class ValidationReport:
    issues: tuple[ValidationIssue, ...]

    @property
    def errors(self) -> tuple[ValidationIssue, ...]:
        return tuple(i for i in self.issues if i.severity == "error")

    @property
    def warnings(self) -> tuple[ValidationIssue, ...]:
        return tuple(i for i in self.issues if i.severity == "warning")

    @property
    def ok(self) -> bool:
        return not self.errors


_HARMONY_CODES = {"chromatic_chord", "roman_mismatch", "invalid_roman"}
_ROOTLESS_PREFIXES = ("rootless", "upper_structure", "altered", "guide_tone_rh")


def validate_progression(
    prog: Progression,
    *,
    constraints: VoicingConstraints | None = None,
    strict_harmony: bool = False,
    publication: bool = False,
    deep: bool = False,
) -> ValidationReport:
    """Check a progression before playback or publication.

    Structure, timing, chord symbols and voicings are errors when wrong. Harmonic conventions
    (a chord outside the key, a numeral that disagrees with the chord) are warnings unless
    `strict_harmony` is set, as a lesson with explicit rules would. `publication` adds the
    requirements for publishing; `deep` also tests transposition into every key.
    """
    issues: list[ValidationIssue] = []

    def add(severity: str, code: str, message: str, index: int | None = None) -> None:
        if severity == "warning" and strict_harmony and code in _HARMONY_CODES:
            severity = "error"
        issues.append(ValidationIssue(severity, code, message, index))  # type: ignore[arg-type]

    if prog.schema_version != SCHEMA_VERSION:
        add("error", "unsupported_schema", f"Schema version {prog.schema_version} is not supported")
    if not prog.name.strip():
        add("error", "missing_name", "The progression needs a name")
    if not prog.chords:
        add("error", "no_chords", "The progression has no chords")
    if prog.difficulty not in SKILLS:
        add("error", "invalid_difficulty", f"Difficulty must be one of {', '.join(SKILLS)}")
    num, den = prog.time_signature
    if num < 1 or num > 32 or den not in (1, 2, 4, 8, 16):
        add("error", "invalid_time_signature", f"{num}/{den} is not a valid time signature")
    if prog.tempo is not None and not 20 <= prog.tempo <= 400:
        add("error", "invalid_tempo", "Tempo must be between 20 and 400 BPM")
    if any(not s.strip() for s in prog.styles):
        add("warning", "empty_style", "A style tag is empty")
    if prog.meta.status not in STATUSES:
        add("error", "invalid_status", f"Status must be one of {', '.join(STATUSES)}")
    if prog.meta.revision < 1:
        add("error", "invalid_revision", "Revision must be at least 1")

    c = constraints or constraints_for_skill(
        prog.difficulty if prog.difficulty in SKILLS else "intermediate"
    )
    prev: ProgressionChord | None = None
    for i, pc in enumerate(prog.chords):
        chord = pc.chord
        if not (math.isfinite(pc.beat) and math.isfinite(pc.duration)):
            add("error", "invalid_timing", "Beat and duration must be finite numbers", i)
            continue
        if pc.beat < 0:
            add("error", "negative_beat", "A chord cannot start before beat 0", i)
        if pc.duration <= 0:
            add("error", "invalid_duration", "A chord must last longer than 0 beats", i)
        if pc.role not in ROLES:
            add("error", "invalid_role", f"Role must be one of {', '.join(ROLES)}", i)
        if prev is None:
            if abs(pc.beat) > _EPS and pc.beat >= 0:
                add("warning", "late_start", "The first chord does not start on beat 0", i)
        elif pc.beat < prev.beat - _EPS:
            add("error", "out_of_order", "Chords must be listed in time order", i)
        elif pc.beat < prev.end - _EPS:
            add(
                "error",
                "timing_overlap",
                f"Overlaps the previous chord by {prev.end - pc.beat:g} beats",
                i,
            )
        elif pc.beat > prev.end + _EPS:
            add(
                "warning",
                "timing_gap",
                f"Gap of {pc.beat - prev.end:g} beats after the previous chord",
                i,
            )
        prev = pc

        try:
            if parse_chord(format_chord(chord)) != chord:
                raise TheoryError("round trip differs")
        except TheoryError:
            add(
                "error",
                "invalid_chord_symbol",
                f"{chord.root} {chord.type.id} has no valid symbol",
                i,
            )

        if pc.roman:
            try:
                expected = chord_from_roman(pc.roman, prog.key)
                same = (expected.root.pitch_class, expected.type.id) == (
                    chord.root.pitch_class,
                    chord.type.id,
                )
                if not same:
                    msg = f"{pc.roman} in {prog.key} is {expected}, but the chord is {chord}"
                    add("warning", "roman_mismatch", msg, i)
            except TheoryError as exc:
                add("warning", "invalid_roman", f"Numeral {pc.roman!r}: {exc.message}", i)
        elif publication:
            add("error", "missing_roman", "Published progressions need Roman numerals", i)
        if (
            analyze_chord(chord, prog.key).category == "chromatic"
            and pc.role == "main"
            and not _blues_dominant(prog, chord)
        ):
            msg = f"{chord} is not diatonic, borrowed or an applied chord in {prog.key}"
            add("warning", "chromatic_chord", msg, i)

        if pc.voicing is not None:
            _check_voicing(pc, i, c, add)

    if prog.chords and prog.beats_per_bar > 0 and math.isfinite(prog.total_beats):
        bars = prog.total_beats / prog.beats_per_bar
        if abs(bars - round(bars)) > 1e-6:
            add(
                "warning",
                "incomplete_bar",
                f"Length is {prog.total_beats:g} beats, not a whole number of bars",
            )

    if publication:
        if not prog.explanation.strip():
            add("error", "missing_explanation", "Published progressions need an explanation")
        if not prog.meta.author:
            add("error", "missing_author", "Published progressions need an author")
        if not prog.styles:
            add("error", "no_styles", "Published progressions need at least one style tag")

    if deep and prog.chords:
        _check_transposition(prog, add)
    return ValidationReport(tuple(issues))


def _blues_dominant(prog: Progression, chord: Chord) -> bool:
    """Blues builds I, IV and V as dominant sevenths; that is idiom, not a harmonic error."""
    return "blues" in prog.styles and chord.type.id in _TRITONE_SUBBABLE


def _check_voicing(
    pc: ProgressionChord, i: int, c: VoicingConstraints, add: Callable[..., None]
) -> None:
    v, chord = pc.voicing, pc.chord
    assert v is not None
    for issue in playability_issues(v, c):
        code = "hand_crossing" if issue.startswith("hands") else "voicing_unplayable"
        add("error", code, f"Voicing for {chord}: {issue}", i)
    chord_pcs = {(chord.root.pitch_class + t.semitones) % 12 for t in chord.type.formula}
    from music_theory.intervals import parse_interval

    allowed = chord_pcs | {
        (chord.root.pitch_class + parse_interval(t).semitones) % 12 for t in v.tensions
    }
    stray = sorted({n % 12 for n in v.notes} - allowed)
    if stray:
        add(
            "error",
            "voicing_not_in_chord",
            f"Voicing for {chord} contains notes that are not chord tones",
            i,
        )
    if v.notes:
        lowest = v.lowest % 12
        rootless = v.rh_style.startswith(_ROOTLESS_PREFIXES) or v.lh_style.startswith("guide_tones")
        if chord.bass is not None and lowest != chord.bass.pitch_class:
            add("error", "bass_mismatch", f"Lowest note should be {chord.bass} for {chord}", i)
        elif chord.bass is None and lowest != chord.root.pitch_class and not rootless:
            add("warning", "bass_not_root", f"Lowest note is not the root of {chord}", i)
        third = next((t for t in chord.type.formula if t.number == 3), None)
        if third is not None and (chord.root.pitch_class + third.semitones) % 12 not in {
            n % 12 for n in v.notes
        }:
            add("warning", "missing_third", f"Voicing for {chord} has no third", i)


def _check_transposition(prog: Progression, add: Callable[..., None]) -> None:
    failed, inconsistent = [], []
    original = [analyze_chord(p.chord, prog.key).figure for p in prog.chords]
    for key in (k for k in ALL_KEYS if k.mode == prog.key.mode):
        try:
            moved = transpose_progression(prog, key.tonic, on_unplayable="drop").progression
        except TheoryError:
            failed.append(str(key.tonic))
            continue
        figures = [analyze_chord(p.chord, moved.key).figure for p in moved.chords]
        if figures != original:
            inconsistent.append(str(key.tonic))
    if failed:
        add("warning", "transposition_unavailable", f"Cannot be spelled in: {', '.join(failed)}")
    if inconsistent:
        add("warning", "transposition_inconsistent",
            f"Roman numerals change when transposed to: {', '.join(inconsistent)}")  # fmt: skip


# ------------------------------------------------------------------ serialisation

_MIGRATIONS: dict[int, Callable[[dict[str, Any]], dict[str, Any]]] = {}


def _bad(path: str, why: str) -> ProgressionError:
    return ProgressionError(f"{path}: {why}", code="invalid_progression_data")


def progression_to_dict(prog: Progression) -> dict[str, Any]:
    return {
        "schema_version": prog.schema_version,
        "name": prog.name,
        "key": {"tonic": str(prog.key.tonic), "mode": prog.key.mode},
        "scale_id": prog.scale_id,
        "time_signature": list(prog.time_signature),
        "tempo": prog.tempo,
        "difficulty": prog.difficulty,
        "styles": list(prog.styles),
        "explanation": prog.explanation,
        "template_id": prog.template_id,
        "meta": {
            "author": prog.meta.author,
            "source": prog.meta.source,
            "status": prog.meta.status,
            "revision": prog.meta.revision,
        },  # fmt: skip
        "chords": [
            {
                "symbol": format_chord(c.chord),
                "root": str(c.chord.root),
                "type": c.chord.type.id,
                "bass": None if c.chord.bass is None else str(c.chord.bass),
                "roman": c.roman,
                "beat": c.beat,
                "duration": c.duration,
                "role": c.role,
                "substitution_for": c.substitution_for,
                "voicing": None if c.voicing is None else c.voicing.to_dict(),
                "explanation": c.explanation,
            }
            for c in prog.chords
        ],
    }


def migrate_progression_data(data: Mapping[str, Any]) -> dict[str, Any]:
    """Bring stored data up to the current schema version, one registered step at a time."""
    out = dict(data)
    version = out.get("schema_version")
    if not isinstance(version, int) or isinstance(version, bool) or version < 0:
        raise _bad("schema_version", "must be a non-negative integer")
    if version > SCHEMA_VERSION:
        raise ProgressionError(
            f"Data is schema version {version}; this build understands up to {SCHEMA_VERSION}",
            code="unsupported_schema_version",
        )
    while version < SCHEMA_VERSION:
        step = _MIGRATIONS.get(version)
        if step is None:
            raise ProgressionError(
                f"No migration from schema version {version}", code="no_migration"
            )
        out = step(out)
        version += 1
        out["schema_version"] = version
    return out


def progression_from_dict(data: Mapping[str, Any]) -> Progression:
    data = migrate_progression_data(data)

    def get(obj: Mapping[str, Any], key: str, path: str, kind: type | tuple[type, ...]) -> Any:
        if key not in obj:
            raise _bad(f"{path}.{key}", "is required")
        value = obj[key]
        if isinstance(value, bool) and bool not in (kind if isinstance(kind, tuple) else (kind,)):
            raise _bad(f"{path}.{key}", "has the wrong type")
        if not isinstance(value, kind):
            raise _bad(f"{path}.{key}", "has the wrong type")
        return value

    try:
        key_data = get(data, "key", "progression", dict)
        key = Key(
            parse_note_name(get(key_data, "tonic", "key", str)), get(key_data, "mode", "key", str)
        )
        chords = []
        for i, raw in enumerate(get(data, "chords", "progression", list)):
            path = f"chords[{i}]"
            if not isinstance(raw, dict):
                raise _bad(path, "must be an object")
            bass = raw.get("bass")
            chord = Chord(
                parse_note_name(get(raw, "root", path, str)),
                chord_type(get(raw, "type", path, str)),
                None if bass is None else parse_note_name(str(bass)),
            )
            symbol = raw.get("symbol")
            if symbol is not None and symbol != format_chord(chord):
                raise _bad(
                    f"{path}.symbol", f"{symbol!r} does not match the chord {format_chord(chord)!r}"
                )
            voicing = raw.get("voicing")
            chords.append(
                ProgressionChord(
                    chord=chord,
                    beat=float(get(raw, "beat", path, (int, float))),
                    duration=float(get(raw, "duration", path, (int, float))),
                    roman=raw.get("roman"),
                    role=raw.get("role", "main"),
                    substitution_for=raw.get("substitution_for"),
                    voicing=None if voicing is None else Voicing.from_dict(voicing),
                    explanation=str(raw.get("explanation", "")),
                )
            )
        meta = data.get("meta") or {}
        ts = get(data, "time_signature", "progression", list)
        return Progression(
            name=get(data, "name", "progression", str),
            key=key,
            chords=tuple(chords),
            time_signature=(int(ts[0]), int(ts[1])),
            tempo=data.get("tempo"),
            difficulty=get(data, "difficulty", "progression", str),
            styles=tuple(str(s) for s in data.get("styles", [])),
            explanation=str(data.get("explanation", "")),
            scale_id=data.get("scale_id"),
            template_id=data.get("template_id"),
            meta=PublicationMeta(
                meta.get("author"),
                meta.get("source"),
                meta.get("status", "draft"),
                int(meta.get("revision", 1)),
            ),  # fmt: skip
            schema_version=int(data["schema_version"]),
        )
    except ProgressionError:
        raise
    except (TheoryError, TypeError, ValueError, IndexError) as exc:
        raise _bad("progression", str(exc)) from exc


# ------------------------------------------------------------------ walking bass


@dataclass(frozen=True)
class BassNote:
    beat: float
    midi: int
    role: str  # root, third, fifth, seventh, approach


def _nearest(pc: int, ref: int, low: int, high: int) -> int:
    options = [m for m in range(low, high + 1) if m % 12 == pc]
    if not options:
        raise TheoryError("Bass range is too narrow for this chord", code="range_too_narrow")
    return min(options, key=lambda m: (abs(m - ref), m))


def walking_bass(prog: Progression, *, low: int = 28, high: int = 55) -> list[BassNote]:
    """A simple quarter-note walking line: the root on each chord's first beat, chord tones in
    between, and a chromatic approach note into the next chord's root on its last beat.
    Needs whole-beat chord lengths. Deterministic; always stays inside [low, high]."""
    if low >= high:
        raise TheoryError("low must be below high", code="invalid_range")
    out: list[BassNote] = []
    ref = (low + high) // 2
    for ci, pc in enumerate(prog.chords):
        n = round(pc.duration)
        if abs(pc.duration - n) > _EPS or n < 1:
            raise TheoryError(
                "Walking bass needs chord lengths that are whole numbers of beats",
                code="walking_bass_unsupported",
            )
        chord = pc.chord
        by_num = {
            t.number: (chord.root.pitch_class + t.semitones) % 12
            for t in reversed(chord.type.formula)
        }
        bass_pc = chord.bass_name.pitch_class
        cycle = [
            ("root", bass_pc),
            ("third", by_num.get(3, by_num.get(4, bass_pc))),
            ("fifth", by_num.get(5, bass_pc)),
            ("seventh", by_num.get(7, by_num.get(6, by_num.get(3, bass_pc)))),
        ]
        next_pc = (
            prog.chords[ci + 1].chord.bass_name.pitch_class if ci + 1 < len(prog.chords) else None
        )
        for k in range(n):
            beat = pc.beat + k
            if k == 0:
                role, target = "root", bass_pc
            elif k % 4 == 0:
                role, target = "root", bass_pc
            elif k == n - 1 and next_pc is not None:
                goal = _nearest(next_pc, ref, low, high)
                options = [m for m in (goal - 1, goal + 1) if low <= m <= high]
                midi = min(options, key=lambda m: (abs(m - ref), m)) if options else goal
                out.append(BassNote(beat, midi, "approach"))
                ref = midi
                continue
            else:
                role, target = cycle[k % 4]
            midi = _nearest(target, ref, low, high)
            out.append(BassNote(beat, midi, role))
            ref = midi
    return out


__all__ = [
    "BassNote", "PublicationMeta", "Progression", "ProgressionChord", "ProgressionLibrary",
    "ProgressionTemplate", "TranspositionResult", "ValidationIssue", "ValidationReport",
    "default_library", "generate_progression", "insert_passing_diminished",
    "insert_secondary_dominant", "make_progression", "migrate_progression_data",
    "progression_from_dict", "progression_to_dict", "realize", "substitute_tritone",
    "transpose_progression", "transpose_to_all_keys", "validate_progression", "voice_progression",
    "walking_bass", "with_analysis",
]  # fmt: skip
