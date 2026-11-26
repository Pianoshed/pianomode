"""Scoring voicings and choosing a smooth sequence of them.

All scores are *costs*: lower is better. Each cost is split into named components so a result can
be explained. Weights and style profiles are configurable; nothing here is a universal rule. In
particular, parallel fifths/octaves only cost something in styles (or strict counterpoint
exercises) where they are unwanted.

Sequence choice is exact dynamic programming over per-chord candidate lists when the problem is
small, and a deterministic beam search otherwise. Candidate lists are sorted and ties are broken by
list position, so identical input always gives identical output.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from functools import cache
from typing import Literal

from music_theory.chords import Chord, inversion_name
from music_theory.errors import TheoryError
from music_theory.intervals import parse_interval
from music_theory.notes import note_with_spelling
from music_theory.voicings import (
    Voicing,
    VoicingConstraints,
    constraints_for_skill,
    generate_voicings,
    playability_issues,
    voiced_notes,
)

SKIP_PENALTY = 4  # semitones charged for a voice that appears or disappears between chords
_ROOTLESS_STYLES = ("rootless", "upper_structure", "altered", "guide_tone_rh")


@dataclass(frozen=True)
class StyleProfile:
    parallels: float  # cost per parallel fifth/octave
    dissonance: float  # multiplier for minor-second / minor-ninth clashes
    tension: float  # cost per added tension tone
    clustering: float  # multiplier for clusters and muddy low intervals


STYLE_PROFILES: dict[str, StyleProfile] = {
    "classical": StyleProfile(10.0, 1.0, 1.0, 1.0),
    "pop": StyleProfile(0.5, 0.6, 0.3, 0.7),
    "worship": StyleProfile(0.3, 0.5, 0.1, 0.6),
    "gospel": StyleProfile(0.0, 0.25, 0.0, 0.4),
    "jazz": StyleProfile(0.0, 0.25, 0.0, 0.4),
}


@dataclass(frozen=True)
class VoiceLeadingWeights:
    movement: float = 1.0  # per semitone of total voice motion
    max_leap: float = 0.5  # per semitone of the largest single leap beyond a whole step
    common_tones: float = 1.5  # reward per note held over
    bass_motion: float = 0.3  # per semitone the lowest note moves
    completeness: float = 4.0  # scales the cost of leaving out chord tones
    dissonance: float = 1.0
    parallels: float = 1.0
    span: float = 0.2  # per semitone a hand stretches beyond a ninth
    register: float = 0.15  # per octave away from the preferred register
    clustering: float = 1.0
    inversion: float = 1.0  # not matching the preferred inversion
    root_position: float = 0.0  # extra push toward root-position right hands
    ease: float = 0.5  # fewer notes, smaller shapes


WEIGHT_PRESETS: dict[str, VoiceLeadingWeights] = {
    "balanced": VoiceLeadingWeights(),
    "smooth": VoiceLeadingWeights(movement=2.5, common_tones=3.0, max_leap=1.0, bass_motion=0.1),
    "complete": VoiceLeadingWeights(completeness=10.0, movement=0.7),
    "root_position": VoiceLeadingWeights(root_position=4.0, movement=0.5),
    "easy": VoiceLeadingWeights(ease=3.0, span=0.8, movement=1.5, clustering=2.0),
}


@dataclass(frozen=True)
class VoiceLeadingConfig:
    style: str = "pop"
    weights: VoiceLeadingWeights = VoiceLeadingWeights()
    strict_counterpoint: bool = (
        False  # forbid parallel fifths/octaves as in a counterpoint exercise
    )

    def __post_init__(self) -> None:
        if self.style not in STYLE_PROFILES:
            raise TheoryError(
                f"Unknown style {self.style!r}; choose from {', '.join(STYLE_PROFILES)}",
                code="unknown_style",
            )

    @property
    def profile(self) -> StyleProfile:
        return (
            STYLE_PROFILES["classical"] if self.strict_counterpoint else STYLE_PROFILES[self.style]
        )


def config_for(
    style: str = "pop", weights: str = "balanced", *, strict: bool = False
) -> VoiceLeadingConfig:
    if weights not in WEIGHT_PRESETS:
        raise TheoryError(f"Unknown weight preset {weights!r}", code="unknown_preset")
    return VoiceLeadingConfig(style, WEIGHT_PRESETS[weights], strict)


@dataclass(frozen=True)
class CostBreakdown:
    parts: tuple[tuple[str, float], ...]

    @property
    def total(self) -> float:
        return round(sum(v for _, v in self.parts), 6)

    def as_dict(self) -> dict[str, float]:
        return dict(self.parts)


@dataclass(frozen=True)
class TransitionInfo:
    movement: int  # semitones of total voice motion, including appearing/disappearing voices
    largest_leap: int
    common_tones: int
    bass_motion: int
    parallel_fifths: int
    parallel_octaves: int


@dataclass(frozen=True)
class TransitionEvaluation:
    cost: CostBreakdown
    info: TransitionInfo
    leap_excess: int  # how far the largest leap exceeds constraints.max_leap (0 = fine)


# ------------------------------------------------------------------ alignment


@cache
def _align(a: tuple[int, ...], b: tuple[int, ...]) -> tuple[int, tuple[tuple[int, int], ...]]:
    """Cheapest order-preserving pairing of two note lists. Every note of the shorter list is
    paired; each surplus note of the longer list is unpaired and costs SKIP_PENALTY. With equal
    note counts every voice is paired, so a hand that jumps registers shows up as large leaps
    instead of being disguised as voices vanishing and reappearing.
    Returns (total cost, matched index pairs)."""
    m, n = len(a), len(b)
    inf = 10**9
    skip_a = m > n  # surplus notes can only be dropped from the longer list
    dp = [[inf] * (n + 1) for _ in range(m + 1)]
    dp[0][0] = 0
    for i in range(m + 1):
        for j in range(n + 1):
            if i == j == 0:
                continue
            best = inf
            if i > 0 and j > 0:
                best = dp[i - 1][j - 1] + abs(a[i - 1] - b[j - 1])
            if skip_a and i > 0:
                best = min(best, dp[i - 1][j] + SKIP_PENALTY)
            if not skip_a and m != n and j > 0:
                best = min(best, dp[i][j - 1] + SKIP_PENALTY)
            dp[i][j] = best
    pairs = []
    i, j = m, n
    while i > 0 and j > 0:
        if dp[i][j] == dp[i - 1][j - 1] + abs(a[i - 1] - b[j - 1]):
            pairs.append((i - 1, j - 1))
            i, j = i - 1, j - 1
        elif skip_a:
            i -= 1
        else:
            j -= 1
    return dp[m][n], tuple(reversed(pairs))


def _parallels(a: tuple[int, ...], b: tuple[int, ...]) -> tuple[int, int]:
    _, pairs = _align(a, b)
    fifths = octaves = 0
    for x in range(len(pairs)):
        for y in range(x + 1, len(pairs)):
            (ax, bx), (ay, by) = pairs[x], pairs[y]
            before, after = a[ay] - a[ax], b[by] - b[bx]
            dx, dy = b[bx] - a[ax], b[by] - a[ay]
            if dx == 0 or dy == 0 or (dx > 0) != (dy > 0):
                continue
            if before % 12 == 7 and after % 12 == 7:
                fifths += 1
            elif before > 0 and before % 12 == 0 and after > 0 and after % 12 == 0:
                octaves += 1
    return fifths, octaves


# ------------------------------------------------------------------ evaluation


def _mean(notes: Sequence[int]) -> float:
    return sum(notes) / len(notes)


def _centres(c: VoicingConstraints) -> tuple[float, float]:
    lh = c.lh_center if c.lh_center is not None else sum(c.lh_range) / 2
    rh = c.rh_center if c.rh_center is not None else sum(c.rh_range) / 2
    return lh, rh


def static_cost(
    chord: Chord, v: Voicing, c: VoicingConstraints, cfg: VoiceLeadingConfig
) -> CostBreakdown:
    """Cost of a voicing on its own: completeness, clashes, clusters, comfort, register."""
    w, prof = cfg.weights, cfg.profile
    rootless_style = v.rh_style.startswith(_ROOTLESS_STYLES) or v.lh_style.startswith("guide_tones")
    simplified = v.rh_style in ("triad_close", "triad_open")
    omitted_cost = 0.0
    for name in v.omitted:
        iv = parse_interval(name)
        if iv.number == 1:
            omitted_cost += 0.1 if rootless_style else 0.5
        elif iv.number in (3, 7):
            omitted_cost += 0.4 if (iv.number == 7 and simplified) else 1.0
        elif iv in chord.type.omissible:
            omitted_cost += 0.1
        else:
            omitted_cost += 0.5
    clash = 0.0
    cluster = 0.0
    for notes in (v.left, v.right):
        for x, y in zip(notes, notes[1:], strict=False):
            clash += 1.0 if y - x == 1 else 0.0
            if notes is v.left and x < 48 and y - x < 7:
                cluster += 0.5  # low-interval limit: close intervals are muddy low down
        clash += 0.7 * sum(1 for i in range(len(notes)) for j in range(i + 1, len(notes))
                           if notes[j] - notes[i] == 13)  # fmt: skip
        cluster += sum(1.0 for i in range(len(notes) - 2) if notes[i + 2] - notes[i] <= 4)
    if v.left and v.right:
        gap = v.right[0] - v.left[-1]
        clash += 1.0 if gap == 1 else 0.0
        cluster += max(0, 5 - gap) * 0.25
    span_over = sum(max(0, (n[-1] - n[0]) - 9) for n in (v.left, v.right) if n)
    lh_c, rh_c = _centres(c)
    register = 0.0
    if v.left:
        register += abs(_mean(v.left) - lh_c) / 12
    if v.right:
        register += abs(_mean(v.right) - rh_c) / 12
    inversion = 0.0
    if c.preferred_inversion is not None and v.rh_inversion != c.preferred_inversion:
        inversion = 1.0
    root_pos = 1.0 if v.rh_inversion not in (0, None) else 0.0
    size = len(v.left) + len(v.right)
    spans = max((n[-1] - n[0] for n in (v.left, v.right) if n), default=0)
    parts = (
        ("completeness", w.completeness * omitted_cost),
        ("tension", w.dissonance * prof.tension * len(v.tensions)),
        ("dissonance", w.dissonance * prof.dissonance * clash),
        ("clustering", w.clustering * prof.clustering * cluster),
        ("span", w.span * span_over),
        ("register", w.register * register),
        ("inversion", w.inversion * inversion),
        ("root_position", w.root_position * root_pos),
        ("ease", w.ease * (0.15 * size + 0.05 * spans)),
    )
    return CostBreakdown(tuple((k, round(x, 6)) for k, x in parts))


def evaluate_transition(
    prev: Voicing, nxt: Voicing, c: VoicingConstraints | None = None,
    cfg: VoiceLeadingConfig | None = None,
) -> TransitionEvaluation:  # fmt: skip
    """Cost of moving from one voicing to the next (motion, leaps, held notes, bass, parallels)."""
    c = c or constraints_for_skill("intermediate")
    cfg = cfg or VoiceLeadingConfig()
    w, prof = cfg.weights, cfg.profile
    cost_l, pairs_l = _align(prev.left, nxt.left)
    cost_r, pairs_r = _align(prev.right, nxt.right)
    movement = cost_l + cost_r
    leaps = [abs(nxt.left[j] - prev.left[i]) for i, j in pairs_l]
    leaps += [abs(nxt.right[j] - prev.right[i]) for i, j in pairs_r]
    largest = max(leaps, default=0)
    common = len(set(prev.left) & set(nxt.left)) + len(set(prev.right) & set(nxt.right))
    bass = abs(nxt.lowest - prev.lowest)
    fifths, octaves = _parallels(prev.notes, nxt.notes)
    excess = max(0, largest - c.max_leap) if c.max_leap is not None else 0
    parts = (
        ("movement", w.movement * movement),
        ("leap", w.max_leap * max(0, largest - 2)),
        ("common_tones", -w.common_tones * common),
        ("bass_motion", w.bass_motion * bass),
        ("parallels", w.parallels * prof.parallels * (fifths + octaves)),
    )
    info = TransitionInfo(movement, largest, common, bass, fifths, octaves)
    return TransitionEvaluation(
        CostBreakdown(tuple((k, round(x, 6)) for k, x in parts)), info, excess
    )


# ------------------------------------------------------------------ explanation


def _note_text(chord: Chord, v: Voicing, midis: Sequence[int]) -> str:
    spelled = {n.midi: n for n in voiced_notes(chord, v)}
    return " ".join(
        str(note_with_spelling(m, spelled[m].name)) if m in spelled else str(m) for m in midis
    )


_STYLE_TEXT = {
    "bass": "bass note", "octave_root": "octave bass", "root_fifth": "root and fifth",
    "open_fifth": "open fifth with octave", "guide_tones_3_7": "guide tones (3rd below 7th)",
    "guide_tones_7_3": "guide tones (7th below 3rd)", "shell_r37": "shell (root, 3rd, 7th)",
    "shell_r73": "shell (root, 7th, 3rd)", "tenth": "root and tenth",
    "triad_close": "close triad", "triad_open": "open triad",
    "seventh_close": "close seventh chord",
    "extended_close": "extended chord", "drop2": "drop-2 voicing", "spread": "spread voicing",
    "rootless_a": "rootless voicing (type A: 3-5-7-9)",
    "rootless_b": "rootless voicing (type B: 7-9-3-5)",
    "guide_tone_rh": "guide tones", "altered": "altered-dominant voicing",
}  # fmt: skip


def explain(
    chord: Chord, v: Voicing, static: CostBreakdown, transition: TransitionEvaluation | None = None,
    cfg: VoiceLeadingConfig | None = None,
) -> tuple[str, ...]:  # fmt: skip
    cfg = cfg or VoiceLeadingConfig()
    rh = _STYLE_TEXT.get(
        v.rh_style, v.rh_style.replace("upper_structure_", "upper-structure triad ")
    )
    lines = []
    left = (
        f"LH {_STYLE_TEXT.get(v.lh_style, v.lh_style)} ({_note_text(chord, v, v.left)})"
        if v.left
        else "LH silent"
    )
    inv = f", {inversion_name(v.rh_inversion)}" if v.rh_inversion is not None and v.right else ""
    right = f"RH {rh}{inv} ({_note_text(chord, v, v.right)})" if v.right else "RH silent"
    lines.append(f"{chord}: {left}; {right}.")
    if v.omitted:
        names = ", ".join(parse_interval(o).long for o in v.omitted)
        lines.append(f"Leaves out: {names}.")
    if v.tensions:
        names = ", ".join(parse_interval(t).long for t in v.tensions)
        lines.append(f"Adds colour tone(s): {names}.")
    if transition is not None:
        i = transition.info
        lines.append(
            f"Moves {i.movement} semitones in total (largest single move {i.largest_leap}); "
            f"holds {i.common_tones} note(s); bass moves {i.bass_motion}."
        )
        if i.parallel_fifths or i.parallel_octaves:
            kinds = []
            if i.parallel_fifths:
                kinds.append(f"{i.parallel_fifths} parallel fifth(s)")
            if i.parallel_octaves:
                kinds.append(f"{i.parallel_octaves} parallel octave(s)")
            allowed = cfg.profile.parallels < 1.0
            lines.append(
                f"Has {' and '.join(kinds)}"
                + (
                    f", which the {cfg.style} style tolerates."
                    if allowed
                    else ", penalised in this style."
                )
            )
    return tuple(lines)


# ------------------------------------------------------------------ sequence choice


@dataclass(frozen=True)
class ChosenVoicing:
    chord: Chord
    voicing: Voicing
    static: CostBreakdown
    transition: TransitionEvaluation | None
    cost: float  # static + transition for this step
    explanation: tuple[str, ...]


@dataclass(frozen=True)
class VoicedProgression:
    items: tuple[ChosenVoicing, ...]
    total_cost: float
    method: Literal["dp", "beam"]
    relaxed_leap_limit: bool
    warnings: tuple[str, ...]


def _candidates(
    chord: Chord, c: VoicingConstraints, cfg: VoiceLeadingConfig, preset: str | None, limit: int
) -> list[tuple[float, Voicing]]:
    scored = [
        (static_cost(chord, v, c, cfg).total, v) for v in generate_voicings(chord, c, preset=preset)
    ]
    scored.sort(key=lambda t: (t[0], t[1].left, t[1].right, t[1].lh_style, t[1].rh_style))
    return scored[:limit]


def _transition_total(ev: TransitionEvaluation, relaxed: bool) -> float:
    if ev.leap_excess == 0:
        return ev.cost.total
    return ev.cost.total + 5.0 * ev.leap_excess if relaxed else math.inf


def voice_chords(
    chords: Sequence[Chord],
    constraints: VoicingConstraints | None = None,
    *,
    config: VoiceLeadingConfig | None = None,
    preset: str | None = None,
    fixed: Mapping[int, Voicing] | None = None,
    max_candidates: int = 60,
    method: Literal["auto", "dp", "beam"] = "auto",
    beam_width: int = 30,
) -> VoicedProgression:
    """Choose one voicing per chord so the whole sequence is smooth, not each chord alone.

    `fixed` pins chosen voicings by chord index (e.g. ones the user selected). If a
    `max_leap` limit makes the sequence impossible, the limit is relaxed with a penalty and
    reported in the result rather than failing silently.
    """
    if not chords:
        raise TheoryError("Give at least one chord", code="no_chords")
    if max_candidates < 1 or beam_width < 1:
        raise TheoryError("max_candidates and beam_width must be at least 1", code="invalid_search")
    c = constraints or constraints_for_skill("intermediate")
    cfg = config or VoiceLeadingConfig()
    fixed = fixed or {}

    cache: dict[Chord, list[tuple[float, Voicing]]] = {}
    cands: list[list[tuple[float, Voicing]]] = []
    for i, chord in enumerate(chords):
        if i in fixed:
            issues = playability_issues(fixed[i], c)
            if issues:
                raise TheoryError(
                    f"Pinned voicing for chord {i + 1} ({chord}) is not playable: {issues[0]}",
                    code="unplayable_voicing",
                )
            cands.append([(static_cost(chord, fixed[i], c, cfg).total, fixed[i])])
            continue
        if chord not in cache:
            cache[chord] = _candidates(chord, c, cfg, preset, max_candidates)
        if not cache[chord]:
            raise TheoryError(
                f"No playable voicing for chord {i + 1} ({chord}) under these constraints",
                code="no_playable_voicing",
            )
        cands.append(cache[chord])

    sizes = [len(x) for x in cands]
    work = sum(a * b for a, b in zip(sizes, sizes[1:], strict=False))
    use = method if method != "auto" else ("dp" if work <= 2_500_000 else "beam")
    memo: dict[tuple[int, int, int], TransitionEvaluation] = {}

    def trans(i: int, p: int, k: int) -> TransitionEvaluation:
        key = (i, p, k)
        if key not in memo:
            memo[key] = evaluate_transition(cands[i - 1][p][1], cands[i][k][1], c, cfg)
        return memo[key]

    def solve(relaxed: bool) -> tuple[float, list[int]] | None:
        if use == "dp":
            cost = [s for s, _ in cands[0]]
            back: list[list[int]] = []
            for i in range(1, len(cands)):
                cur, bp = [], []
                for k, (static, _) in enumerate(cands[i]):
                    best, bi = math.inf, -1
                    for p, base in enumerate(cost):
                        if base == math.inf:
                            continue
                        t = _transition_total(trans(i, p, k), relaxed)
                        if base + t < best - 1e-9:
                            best, bi = base + t, p
                    cur.append(best + static if bi >= 0 else math.inf)
                    bp.append(bi)
                back.append(bp)
                cost = cur
            best_k = min(range(len(cost)), key=lambda k: (round(cost[k], 9), k))
            if cost[best_k] == math.inf:
                return None
            path = [best_k]
            for bp in reversed(back):
                path.append(bp[path[-1]])
            return cost[best_k], path[::-1]
        beam: list[tuple[float, tuple[int, ...]]] = [(s, (k,)) for k, (s, _) in enumerate(cands[0])]
        beam = sorted(beam, key=lambda t: (round(t[0], 9), t[1]))[:beam_width]
        for i in range(1, len(cands)):
            nxt = []
            for base, prefix in beam:
                for k, (static, _) in enumerate(cands[i]):
                    t = _transition_total(trans(i, prefix[-1], k), relaxed)
                    if t != math.inf:
                        nxt.append((base + t + static, (*prefix, k)))
            if not nxt:
                return None
            beam = sorted(nxt, key=lambda t: (round(t[0], 9), t[1]))[:beam_width]
        best_total, best_path = beam[0]
        return best_total, list(best_path)

    relaxed = False
    result = solve(False)
    if result is None:
        relaxed = True
        result = solve(True)
    if result is None:  # cannot happen with a relaxed pass, but fail loudly if it ever does
        raise TheoryError("Could not find a voicing sequence", code="no_playable_voicing")
    total, path = result

    items = []
    warnings = []
    for i, k in enumerate(path):
        chord, voicing = chords[i], cands[i][k][1]
        st = static_cost(chord, voicing, c, cfg)
        tr = trans(i, path[i - 1], k) if i > 0 else None
        step = st.total + (_transition_total(tr, relaxed) if tr else 0.0)
        if tr is not None and tr.leap_excess:
            warnings.append(
                f"Chord {i + 1} ({chord}): largest move {tr.info.largest_leap} exceeds the "
                f"max leap of {c.max_leap}; the limit was relaxed."
            )
        items.append(
            ChosenVoicing(
                chord, voicing, st, tr, round(step, 6), explain(chord, voicing, st, tr, cfg)
            )
        )
    return VoicedProgression(tuple(items), round(total, 6), use, relaxed, tuple(warnings))


@dataclass(frozen=True)
class SequenceEvaluation:
    total_cost: float
    items: tuple[ChosenVoicing, ...]


def evaluate_sequence(
    chords: Sequence[Chord], voicings: Sequence[Voicing],
    constraints: VoicingConstraints | None = None, config: VoiceLeadingConfig | None = None,
) -> SequenceEvaluation:  # fmt: skip
    """Score voicings someone else chose (e.g. a lesson's published voicings)."""
    if len(chords) != len(voicings) or not chords:
        raise TheoryError("Need one voicing per chord", code="length_mismatch")
    c = constraints or constraints_for_skill("intermediate")
    cfg = config or VoiceLeadingConfig()
    items = []
    total = 0.0
    for i, (chord, v) in enumerate(zip(chords, voicings, strict=True)):
        st = static_cost(chord, v, c, cfg)
        tr = evaluate_transition(voicings[i - 1], v, c, cfg) if i > 0 else None
        step = st.total + (tr.cost.total if tr else 0.0)
        total += step
        items.append(
            ChosenVoicing(chord, v, st, tr, round(step, 6), explain(chord, v, st, tr, cfg))
        )
    return SequenceEvaluation(round(total, 6), tuple(items))
