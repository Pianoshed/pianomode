"""Playable two-hand voicings for a chord.

A voicing is a set of sounding MIDI notes split between the hands. Generation is deterministic:
for every left-hand style and right-hand style in a preset it enumerates placements, then keeps
only those that satisfy the configured ranges, hand span, note counts, tone requirements and bass.
Choosing *between* voicings (smoothness, style) is the job of `voice_leading.py`.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from music_theory.chords import Chord
from music_theory.errors import TheoryError
from music_theory.intervals import Interval, parse_interval, transpose_name
from music_theory.notes import NoteName

Skill = Literal["beginner", "intermediate", "advanced", "expert"]
SKILLS: tuple[Skill, ...] = ("beginner", "intermediate", "advanced", "expert")
PIANO_LO, PIANO_HI = 21, 108
_ROLES = {"root": 1, "third": 3, "fifth": 5, "seventh": 7}

LH_STYLES = (
    "bass", "octave_root", "root_fifth", "open_fifth", "guide_tones_3_7", "guide_tones_7_3",
    "shell_r37", "shell_r73", "tenth",
)  # fmt: skip
RH_STYLES = (
    "triad_close", "triad_open", "seventh_close", "extended_close", "drop2", "spread",
    "rootless_a", "rootless_b", "guide_tone_rh", "upper_structure", "altered",
)  # fmt: skip

_SKILL_DEFAULTS: dict[str, dict[str, Any]] = {
    "beginner": dict(max_span=9, max_notes_per_hand=3, lh_range=(36, 60), rh_range=(55, 79)),
    "intermediate": dict(max_span=12, max_notes_per_hand=4, lh_range=(36, 62), rh_range=(55, 84)),
    "advanced": dict(max_span=14, max_notes_per_hand=4, lh_range=(33, 64), rh_range=(53, 88)),
    "expert": dict(max_span=16, max_notes_per_hand=5, lh_range=(28, 67), rh_range=(48, 91)),
}  # fmt: skip


@dataclass(frozen=True)
class VoicingConstraints:
    """Everything configurable about what counts as playable. Nothing here is a fixed universal
    range: defaults come from the skill level and every field can be overridden.

    - `max_span`: widest stretch (semitones, highest minus lowest) within one hand.
    - `required_tones` / `forbidden_tones`: role words (root, third, fifth, seventh) or interval
      names (M9, m7). A tone the chord does not contain is ignored.
    - `tensions`: optional extensions (interval names) that styles may add.
    - `bass_pc`: force the lowest sounding note to this pitch class.
    - `max_leap`: largest single-voice move allowed between consecutive voicings.
    - `lh_center` / `rh_center`: preferred register (soft preference used when scoring).
    """

    lh_range: tuple[int, int] = (36, 62)
    rh_range: tuple[int, int] = (55, 84)
    max_span: int = 12
    max_notes_per_hand: int = 4
    preferred_inversion: int | None = None
    bass_pc: int | None = None
    required_tones: frozenset[str] = frozenset()
    forbidden_tones: frozenset[str] = frozenset()
    tensions: tuple[str, ...] = ()
    skill: Skill = "intermediate"
    max_leap: int | None = None
    lh_center: int | None = None
    rh_center: int | None = None
    min_hand_gap: int = 1

    def __post_init__(self) -> None:
        def bad(msg: str) -> TheoryError:
            return TheoryError(msg, code="invalid_constraints")

        for label, (lo, hi) in (("lh_range", self.lh_range), ("rh_range", self.rh_range)):
            if not 0 <= lo < hi <= 127:
                raise bad(f"{label} must be two MIDI notes 0-127 with min < max")
        if self.max_span < 0 or self.max_span > 36:
            raise bad("max_span must be between 0 and 36 semitones")
        if not 1 <= self.max_notes_per_hand <= 8:
            raise bad("max_notes_per_hand must be between 1 and 8")
        if self.skill not in SKILLS:
            raise bad(f"skill must be one of {', '.join(SKILLS)}")
        if self.max_leap is not None and self.max_leap < 0:
            raise bad("max_leap must be non-negative")
        if self.bass_pc is not None and not 0 <= self.bass_pc <= 11:
            raise bad("bass_pc must be 0-11")
        if self.min_hand_gap < 0:
            raise bad("min_hand_gap must be non-negative")
        for name in (*self.required_tones, *self.forbidden_tones, *self.tensions):
            if name not in _ROLES:
                try:
                    parse_interval(name)
                except TheoryError:
                    raise bad(f"{name!r} is not a role word or interval name") from None
        for name in self.tensions:
            if name in _ROLES:
                raise bad("tensions must be interval names such as M9 or M13")


def constraints_for_skill(skill: Skill, **overrides: Any) -> VoicingConstraints:
    if skill not in SKILLS:
        raise TheoryError(f"Unknown skill {skill!r}", code="invalid_constraints")
    return VoicingConstraints(**{**_SKILL_DEFAULTS[skill], "skill": skill, **overrides})


@dataclass(frozen=True)
class VoicingPreset:
    name: str
    description: str
    lh_styles: tuple[str, ...]
    rh_styles: tuple[str, ...]
    tensions: tuple[str, ...] = ()


PRESETS: dict[str, VoicingPreset] = {
    p.name: p
    for p in (
        VoicingPreset(
            "beginner", "Bass note below, close triads (any inversion) above.",
            ("bass", "root_fifth"), ("triad_close",),
        ),
        VoicingPreset(
            "intermediate", "Bass or octave root below; seventh chords and triads in inversions.",
            ("bass", "root_fifth", "octave_root"), ("triad_close", "seventh_close", "triad_open"),
        ),
        VoicingPreset(
            "advanced", "Shells and guide tones below; rootless and drop-2 voicings above.",
            ("bass", "root_fifth", "shell_r37", "guide_tones_3_7", "guide_tones_7_3"),
            ("triad_close", "seventh_close", "drop2", "rootless_a", "rootless_b", "guide_tone_rh",
             "triad_open", "extended_close"),
        ),
        VoicingPreset(
            "expert", "Everything: tenths, spread, upper-structure triads and altered dominants.",
            ("bass", "root_fifth", "open_fifth", "shell_r37", "shell_r73", "guide_tones_3_7",
             "guide_tones_7_3", "tenth"),
            ("triad_close", "seventh_close", "extended_close", "drop2", "spread", "rootless_a",
             "rootless_b", "guide_tone_rh", "upper_structure", "altered", "triad_open"),
        ),
        VoicingPreset(
            "jazz", "Shell and guide-tone left hand, rootless and upper-structure right hand.",
            ("shell_r37", "guide_tones_3_7", "guide_tones_7_3", "bass"),
            ("rootless_a", "rootless_b", "drop2", "upper_structure", "altered", "guide_tone_rh",
             "seventh_close", "triad_close"),
        ),
        VoicingPreset(
            "gospel", "Octave and open-fifth bass with open triads and added ninths.",
            ("octave_root", "open_fifth", "bass"),
            ("triad_open", "triad_close", "seventh_close", "extended_close"), ("M9",),
        ),
        VoicingPreset(
            "worship", "Octave or fifth bass with open and close triads, added ninth.",
            ("octave_root", "bass", "root_fifth"), ("triad_open", "triad_close"), ("M9",),
        ),
    )
}  # fmt: skip
SKILL_PRESET = {s: s for s in SKILLS}


@dataclass(frozen=True)
class Voicing:
    left: tuple[int, ...]
    right: tuple[int, ...]
    lh_style: str
    rh_style: str
    tensions: tuple[str, ...] = ()  # interval names used that are not part of the chord
    omitted: tuple[str, ...] = ()  # chord tones that are not sounding
    rh_inversion: int | None = None  # chord-tone index of the lowest right-hand note

    @property
    def notes(self) -> tuple[int, ...]:
        return tuple(sorted((*self.left, *self.right)))

    @property
    def lowest(self) -> int:
        return self.notes[0]

    def to_dict(self) -> dict[str, Any]:
        return {
            "left": list(self.left), "right": list(self.right), "lh_style": self.lh_style,
            "rh_style": self.rh_style, "tensions": list(self.tensions),
            "omitted": list(self.omitted), "rh_inversion": self.rh_inversion,
        }  # fmt: skip

    @staticmethod
    def from_dict(data: dict[str, Any]) -> Voicing:
        try:
            return Voicing(
                left=tuple(int(n) for n in data["left"]),
                right=tuple(int(n) for n in data["right"]),
                lh_style=str(data["lh_style"]),
                rh_style=str(data["rh_style"]),
                tensions=tuple(str(t) for t in data.get("tensions", ())),
                omitted=tuple(str(t) for t in data.get("omitted", ())),
                rh_inversion=data.get("rh_inversion"),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise TheoryError(f"Invalid voicing data: {exc}", code="invalid_voicing") from exc


@dataclass(frozen=True)
class VoicedNote:
    midi: int
    hand: Literal["L", "R"]
    name: NoteName
    role: str  # root, third, fifth, seventh, sixth, ninth, ... or "tension"
    is_bass: bool


# ------------------------------------------------------------------ chord helpers


def _pc(chord: Chord, interval: Interval) -> int:
    return (chord.root.pitch_class + interval.semitones) % 12


def _by_number(chord: Chord, number: int) -> Interval | None:
    return next((i for i in chord.type.formula if i.number == number), None)


def _resolve(
    chord: Chord, names: Sequence[str] | frozenset[str], *, chord_only: bool
) -> frozenset[int]:
    """Pitch classes named by role words or interval names. With `chord_only`, tones the chord
    does not contain are dropped (a requirement the chord cannot meet is ignored); without it, a
    named tone is resolved even if it is only a possible tension (so it can be forbidden)."""
    chord_pcs = {_pc(chord, i) for i in chord.type.formula}
    out = set()
    for name in names:
        iv = _by_number(chord, _ROLES[name]) if name in _ROLES else parse_interval(name)
        if iv is None:
            continue
        pc = _pc(chord, iv)
        if not chord_only or pc in chord_pcs:
            out.add(pc)
    return frozenset(out)


def _role_name(interval: Interval, in_chord: bool) -> str:
    if not in_chord:
        return "tension"
    return {
        1: "root", 2: "second", 3: "third", 4: "fourth", 5: "fifth", 6: "sixth", 7: "seventh",
        9: "ninth", 11: "eleventh", 13: "thirteenth", 10: "tenth",
    }.get(interval.number, f"{interval.number}th")  # fmt: skip


def voiced_notes(chord: Chord, voicing: Voicing) -> list[VoicedNote]:
    """Label every sounding note with its hand, spelling and role in the chord."""
    by_pc: dict[int, tuple[NoteName, str]] = {}
    for iv in chord.type.formula:
        by_pc.setdefault(_pc(chord, iv), (transpose_name(chord.root, iv), _role_name(iv, True)))
    for tension in voicing.tensions:
        iv = parse_interval(tension)
        by_pc.setdefault(_pc(chord, iv), (transpose_name(chord.root, iv), "tension"))
    out = []
    lowest = voicing.lowest
    for hand, notes in (("L", voicing.left), ("R", voicing.right)):
        for midi in notes:
            name, role = by_pc.get(midi % 12, (chord.root, "unknown"))
            out.append(VoicedNote(midi, hand, name, role, midi == lowest))  # type: ignore[arg-type]
    return sorted(out, key=lambda n: n.midi)


def playability_issues(voicing: Voicing, c: VoicingConstraints) -> list[str]:
    """Why a voicing is not playable under `c` (empty list = playable)."""
    issues = []
    for label, notes, (lo, hi) in (
        ("left", voicing.left, c.lh_range),
        ("right", voicing.right, c.rh_range),
    ):
        if list(notes) != sorted(set(notes)):
            issues.append(f"{label} hand notes must be ascending and distinct")
        if notes and (min(notes) < lo or max(notes) > hi):
            issues.append(f"{label} hand leaves its range {lo}-{hi}")
        if notes and max(notes) - min(notes) > c.max_span:
            issues.append(
                f"{label} hand spans {max(notes) - min(notes)} semitones (max {c.max_span})"
            )
        if len(notes) > c.max_notes_per_hand:
            issues.append(f"{label} hand plays {len(notes)} notes (max {c.max_notes_per_hand})")
    allnotes = (*voicing.left, *voicing.right)
    if any(not 0 <= n <= 127 for n in allnotes):
        issues.append("a note is outside MIDI 0-127")
    elif any(not PIANO_LO <= n <= PIANO_HI for n in allnotes):
        issues.append("a note is outside the 88-key piano (A0-C8)")
    if set(voicing.left) & set(voicing.right):
        issues.append("both hands play the same note")
    if voicing.left and voicing.right and voicing.right[0] - voicing.left[-1] < c.min_hand_gap:
        issues.append("hands cross or collide")
    if not allnotes:
        issues.append("no notes")
    return issues


# ------------------------------------------------------------------ generation


@dataclass(frozen=True)
class _Plan:
    style: str
    tones: tuple[Interval, ...]
    transform: str = "close"  # close | open | drop2 | spread
    lowest: tuple[int, ...] | None = None  # indexes into tones that may be the lowest note
    needs_guides: bool = False  # LH/RH together must still carry the third and seventh
    simplified: bool = False  # deliberately leaves out the seventh and above


_ROOTLESS = {
    "major7": ("M3", "P5", "M7", "M9"), "major9": ("M3", "P5", "M7", "M9"),
    "minor7": ("m3", "P5", "m7", "M9"), "minor9": ("m3", "P5", "m7", "M9"),
    "dominant7": ("M3", "M13", "m7", "M9"), "dominant9": ("M3", "M13", "m7", "M9"),
    "dominant13": ("M3", "M13", "m7", "M9"),
    "half_diminished7": ("m3", "d5", "m7", "M9"),
}  # fmt: skip
_UST = {
    "dominant7": (("II", ("M9", "A11", "M13")), ("bIII", ("A9", "P5", "m7")),
                  ("bV", ("d5", "m7", "m9"))),
    "major7": (("V", ("P5", "M7", "M9")), ("II", ("M9", "A11", "M13"))),
}  # fmt: skip
_ALTERED_PAIRS = (("m9", "m13"), ("A9", "m13"), ("m9", "A9"))
_ACCEPTS_TENSIONS = {"triad_close", "triad_open", "seventh_close", "extended_close"}


def _reduce(chord: Chord, tones: list[Interval], limit: int) -> list[Interval] | None:
    """Drop tones until at most `limit` remain: omissible tones first, then the root. The third
    and seventh are never dropped. Returns None if that is not enough."""
    tones = list(tones)
    order = [i for i in chord.type.omissible if i in tones]
    order += [i for i in tones if i.number == 1 and i not in order]
    for drop in order:
        if len(tones) <= limit:
            break
        tones.remove(drop)
    return tones if len(tones) <= limit else None


def _plans(chord: Chord, style: str, c: VoicingConstraints, tensions: Sequence[str]) -> list[_Plan]:
    f = list(chord.type.formula)
    third, seventh = _by_number(chord, 3), _by_number(chord, 7)
    tid = chord.type.id
    chord_pcs = {_pc(chord, i) for i in f}
    limit = c.max_notes_per_hand

    def with_tensions(tones: list[Interval]) -> list[Interval]:
        out = list(tones)
        for name in tensions:
            iv = parse_interval(name)
            pc = _pc(chord, iv)
            if pc in chord_pcs or pc in {_pc(chord, t) for t in out} or len(out) >= limit:
                continue
            out.append(iv)
        return out

    if style in ("triad_close", "triad_open"):
        basic = [i for i in f if i.number <= 5]
        if len(basic) < 2 or (style == "triad_open" and len(basic) != 3):
            return []
        tones = with_tensions(basic) if style == "triad_close" else basic
        simplified = any(i.number >= 6 for i in f)
        if len(tones) > limit:
            return []
        return [_Plan(style, tuple(tones), "open" if style == "triad_open" else "close",
                      simplified=simplified)]  # fmt: skip
    if style == "seventh_close":
        seventh_set = [i for i in f if i.number <= 7]
        if len(seventh_set) < 4:
            return []
        tones = with_tensions(seventh_set)
        reduced = _reduce(chord, tones, limit)
        return (
            [_Plan(style, tuple(reduced), simplified=any(i.number > 7 for i in f))]
            if reduced
            else []
        )
    if style == "extended_close":
        if not any(i.number > 7 for i in f):
            return []
        reduced = _reduce(chord, f, limit)
        return [_Plan(style, tuple(with_tensions(reduced) if reduced else []))] if reduced else []
    if style == "drop2":
        if any(i.number > 7 for i in f):
            base = _reduce(chord, f, 4) or []  # keep the defining extension, drop the fifth
        else:
            base = f if len(f) == 4 else []
        return [_Plan(style, tuple(base), "drop2")] if len(base) == 4 else []
    if style == "spread":
        reduced = _reduce(chord, f, limit)
        return [_Plan(style, tuple(reduced), "spread")] if reduced and len(reduced) >= 3 else []
    if style in ("rootless_a", "rootless_b"):
        names = _ROOTLESS.get(tid)
        if names is None:
            return []
        return [_Plan(style, tuple(parse_interval(n) for n in names), "close",
                      (0,) if style == "rootless_a" else (2,), needs_guides=True)]  # fmt: skip
    if style == "guide_tone_rh":
        if third is None or seventh is None:
            return []
        return [_Plan(style, (third, seventh), "close", None, needs_guides=True)]
    if style == "upper_structure":
        return [
            _Plan(f"upper_structure_{label}", tuple(parse_interval(n) for n in names), "close",
                  None, needs_guides=True)
            for label, names in _UST.get(tid, ())
        ]  # fmt: skip
    if style == "altered":
        if third is None or seventh is None or tid not in ("dominant7", "altered"):
            return []
        return [
            _Plan("altered", (third, seventh, parse_interval(a), parse_interval(b)), "close",
                  None, needs_guides=True)
            for a, b in _ALTERED_PAIRS
        ]  # fmt: skip
    raise TheoryError(f"Unknown right-hand style {style!r}", code="unknown_style")


def _bases(pc: int, lo_edge: int, hi_edge: int) -> Iterator[int]:
    for midi in range(max(0, lo_edge), min(127, hi_edge) + 1):
        if midi % 12 == pc:
            yield midi


def _rh_arrangements(
    chord: Chord, plan: _Plan, c: VoicingConstraints
) -> Iterator[tuple[tuple[int, ...], int | None]]:
    root_pc = chord.root.pitch_class
    pcs = [(root_pc + t.semitones) % 12 for t in plan.tones]
    if len(set(pcs)) != len(pcs):
        return
    lo, hi = c.rh_range
    formula_pcs = [_pc(chord, i) for i in chord.type.formula]
    for idx in plan.lowest if plan.lowest is not None else range(len(pcs)):
        low_pc = pcs[idx]
        order = sorted(range(len(pcs)), key=lambda j: ((pcs[j] - low_pc) % 12, j))
        rel = [(pcs[j] - low_pc) % 12 for j in order]
        if plan.transform == "open":
            if len(rel) != 3:
                continue
            rel = [rel[0], rel[2], rel[1] + 12]
        elif plan.transform == "drop2":
            if len(rel) != 4:
                continue
            rel = sorted([rel[2] - 12, rel[0], rel[1], rel[3]])
        elif plan.transform == "spread":
            rel = sorted([r + 12 if k % 2 == 1 else r for k, r in enumerate(rel)])
        rel = [r - min(rel) for r in rel]  # lowest note at 0
        low_idx_pc = _lowest_pc(pcs, order, low_pc, plan.transform)
        for base in _bases(low_idx_pc, lo, hi):
            notes = tuple(base + r for r in rel)
            if (
                notes[-1] > hi
                or notes[-1] - notes[0] > c.max_span
                or len(notes) > c.max_notes_per_hand
            ):
                continue
            inv = formula_pcs.index(notes[0] % 12) if notes[0] % 12 in formula_pcs else None
            yield notes, inv


def _lowest_pc(pcs: list[int], order: list[int], low_pc: int, transform: str) -> int:
    """Pitch class of the lowest note after the transform (drop-2 lowers the 3rd-highest)."""
    if transform == "drop2":
        return pcs[order[2]]
    return low_pc


def _left_arrangements(
    chord: Chord, style: str, c: VoicingConstraints
) -> Iterator[tuple[int, ...]]:
    third, seventh, fifth = _by_number(chord, 3), _by_number(chord, 7), _by_number(chord, 5)
    root_pc = chord.root.pitch_class
    bass_pc = chord.bass_name.pitch_class
    offsets: list[int]
    base_pc: int
    if style == "bass":
        base_pc, offsets = bass_pc, [0]
    elif style == "octave_root":
        base_pc, offsets = bass_pc, [0, 12]
    elif chord.bass is not None:
        return  # slash chords and inversions keep their stated bass
    elif style == "root_fifth" and fifth is not None:
        base_pc, offsets = root_pc, [0, fifth.semitones]
    elif style == "open_fifth" and fifth is not None:
        base_pc, offsets = root_pc, [0, fifth.semitones, 12]
    elif style == "guide_tones_3_7" and third and seventh:
        base_pc, offsets = _pc(chord, third), [0, seventh.semitones - third.semitones]
    elif style == "guide_tones_7_3" and third and seventh:
        base_pc, offsets = _pc(chord, seventh), [0, third.semitones + 12 - seventh.semitones]
    elif style == "shell_r37" and third and seventh:
        base_pc, offsets = root_pc, [0, third.semitones, seventh.semitones]
    elif style == "shell_r73" and third and seventh:
        base_pc, offsets = root_pc, [0, seventh.semitones, third.semitones + 12]
    elif style == "tenth" and third:
        base_pc, offsets = root_pc, [0, third.semitones + 12]
    elif style in LH_STYLES:
        return
    else:
        raise TheoryError(f"Unknown left-hand style {style!r}", code="unknown_style")
    if offsets[-1] > c.max_span or len(offsets) > c.max_notes_per_hand:
        return
    lo, hi = c.lh_range
    for base in _bases(base_pc, lo, hi):
        notes = tuple(base + o for o in offsets)
        if notes[-1] <= hi:
            yield notes


def _accept(
    chord: Chord, c: VoicingConstraints, left: tuple[int, ...], right: tuple[int, ...],
    plan: _Plan | None,
) -> bool:  # fmt: skip
    notes = (*left, *right)
    pcs = {n % 12 for n in notes}
    lowest_pc = min(notes) % 12
    if chord.bass is not None and lowest_pc != chord.bass.pitch_class:
        return False
    if c.bass_pc is not None and lowest_pc != c.bass_pc:
        return False
    if _resolve(chord, c.required_tones, chord_only=True) - pcs:
        return False
    if _resolve(chord, c.forbidden_tones, chord_only=False) & pcs:
        return False
    third, seventh = _by_number(chord, 3), _by_number(chord, 7)
    if third is not None and _pc(chord, third) not in pcs:
        return False
    simplified = plan.simplified if plan is not None else False
    if seventh is not None and not simplified and _pc(chord, seventh) not in pcs:
        return False
    return True


def generate_voicings(
    chord: Chord,
    constraints: VoicingConstraints | None = None,
    *,
    preset: str | None = None,
    lh_styles: Sequence[str] | None = None,
    rh_styles: Sequence[str] | None = None,
) -> list[Voicing]:
    """All playable voicings of `chord` under `constraints`, in a stable order.

    Styles come from the named preset (default: the constraints' skill level) unless given.
    Every returned voicing passes `playability_issues`, contains the chord's third (and seventh
    unless a beginner triad deliberately leaves it out), respects the chord's own bass, and
    satisfies the required/forbidden tones. Possibly empty if the constraints are too tight.
    """
    c = constraints or constraints_for_skill("intermediate")
    name = preset or SKILL_PRESET[c.skill]
    if name not in PRESETS:
        raise TheoryError(f"Unknown voicing preset {name!r}", code="unknown_preset")
    p = PRESETS[name]
    lh = tuple(p.lh_styles if lh_styles is None else lh_styles)
    rh = tuple(p.rh_styles if rh_styles is None else rh_styles)
    tensions = c.tensions or p.tensions
    chord_pcs = {_pc(chord, i) for i in chord.type.formula}
    formula_pcs = [_pc(chord, i) for i in chord.type.formula]

    lefts: list[tuple[str, tuple[int, ...]]] = [("", ())] if not lh else []
    for style in lh:
        lefts += [(style, n) for n in _left_arrangements(chord, style, c)]
    rights: list[tuple[_Plan, tuple[int, ...], int | None]] = []
    for style in rh:
        for plan in _plans(chord, style, c, tensions):
            rights += [(plan, n, inv) for n, inv in _rh_arrangements(chord, plan, c)]

    found: dict[tuple[tuple[int, ...], tuple[int, ...]], Voicing] = {}
    for lh_style, left in lefts:
        for plan, right, inv in rights:
            if left and right[0] - left[-1] < c.min_hand_gap:
                continue
            if set(left) & set(right) or not _accept(chord, c, left, right, plan):
                continue
            used = {n % 12 for n in (*left, *right)}
            tension_names = tuple(i.short for i in plan.tones if _pc(chord, i) not in chord_pcs)
            omitted = tuple(
                i.short for i, pc in zip(chord.type.formula, formula_pcs, strict=True)
                if pc not in used
            )  # fmt: skip
            key = (left, right)
            candidate = Voicing(left, right, lh_style, plan.style, tension_names, omitted, inv)
            old = found.get(key)
            if old is None or (candidate.lh_style, candidate.rh_style) < (
                old.lh_style,
                old.rh_style,
            ):
                found[key] = candidate
    return sorted(found.values(), key=lambda v: (v.left, v.right, v.lh_style, v.rh_style))
