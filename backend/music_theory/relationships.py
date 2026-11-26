"""Relationships between successive chords: common tones, root motion, chromatic links.

These are descriptive facts about two chords (shared pitch classes, how the roots move, whether
the pair is a recognised chromatic relationship). They do not claim intent: a chromatic mediant
or a tritone substitution is a *description of the pair*, not proof of how it was composed.
Slash-chord basses are ignored: only the chord's own tones are compared.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import permutations

from music_theory.chords import Chord
from music_theory.notes import NoteName
from music_theory.roman import RomanNumeral

_TRIADS = frozenset({"major", "minor"})
_DOMINANT_SEVENTHS = frozenset({"dominant7", "dominant9", "dominant13"})

# ascending semitones from the first root to the second root -> wording
_MOTION = {
    0: "root stays",
    1: "root up a semitone",
    2: "root up a whole step",
    3: "root up a minor third",
    4: "root up a major third",
    5: "root up a fourth (down a fifth)",
    6: "root moves a tritone",
    7: "root up a fifth (down a fourth)",
    8: "root down a major third",
    9: "root down a minor third",
    10: "root down a whole step",
    11: "root down a semitone",
}
_MOTION_KIND = {
    0: "same_root", 1: "step_motion", 2: "step_motion", 3: "third_motion", 4: "third_motion",
    5: "falling_fifth", 6: "tritone_motion", 7: "rising_fifth", 8: "third_motion",
    9: "third_motion", 10: "step_motion", 11: "step_motion",
}  # fmt: skip

# Neo-Riemannian transforms between a major and a minor triad: (first quality, root step) -> name
_TRANSFORMS = {
    ("major", 0): "P", ("minor", 0): "P",
    ("major", 9): "R", ("minor", 3): "R",
    ("major", 4): "L", ("minor", 8): "L",
}  # fmt: skip
_TRANSFORM_TEXT = {
    "P": "parallel (same root, major/minor swap)",
    "R": "relative (major and its relative minor)",
    "L": "leading-tone exchange (major and the minor a third above)",
}


@dataclass(frozen=True)
class ChordRelationship:
    start: int  # index of the first chord
    end: int  # index of the second chord (start + 1)
    common_tones: tuple[NoteName, ...]  # spelled as in the first chord
    root_semitones: int  # ascending distance from first root to second root, 0-11
    root_motion: str
    kinds: tuple[str, ...]  # stable ids, see module tests
    transform: str | None  # "P", "R" or "L" for a major/minor triad pair sharing two tones
    voice_leading_distance: int  # least total semitone motion between the two chords' tones
    unmatched_tones: int  # tones with no partner when the chords differ in size
    non_diatonic: bool | None  # None when no Roman numerals were supplied
    note: str


def _circ(a: int, b: int) -> int:
    d = (a - b) % 12
    return min(d, 12 - d)


def minimal_motion(first: tuple[int, ...], second: tuple[int, ...]) -> tuple[int, int]:
    """Least total semitone motion matching every tone of the smaller chord to a distinct tone of
    the larger one (circular distance, octave ignored), and how many tones are left unmatched.
    This is a pitch-class measure: it ignores register and which voice moves."""
    a, b = sorted(set(first)), sorted(set(second))
    small, large = (a, b) if len(a) <= len(b) else (b, a)
    best = min(
        sum(_circ(x, y) for x, y in zip(small, pick, strict=True))
        for pick in permutations(large, len(small))
    )
    return best, len(large) - len(small)


def chord_relationship(
    first: Chord, second: Chord, *, start: int = 0, non_diatonic: bool | None = None
) -> ChordRelationship:
    second_pcs = set(second.pitch_classes())
    common = tuple(t for t in first.tones() if t.pitch_class in second_pcs)
    r = (second.root.pitch_class - first.root.pitch_class) % 12
    kinds: list[str] = [_MOTION_KIND[r], "shares_tones" if common else "no_common_tones"]
    notes = [f"{_MOTION[r].capitalize()}."]
    notes.append(
        f"Shared tones: {', '.join(str(t) for t in common)}."
        if common
        else "No tone is shared, so every voice has to move."
    )

    transform: str | None = None
    qa, qb = first.type.id, second.type.id
    both_triads = qa in _TRIADS and qb in _TRIADS
    if both_triads and qa != qb and len(common) == 2:
        transform = _TRANSFORMS.get((qa, r))
        if transform is not None:
            kinds.append(f"transform_{transform}")
            notes.append(f"Triad transform {transform}: {_TRANSFORM_TEXT[transform]}.")
    if both_triads and qa == qb and r in (3, 4, 8, 9) and len(common) == 1:
        kinds.append("chromatic_mediant")
        notes.append(
            "Chromatic mediant: same-quality triads a third apart that share exactly one tone."
        )
    if qa in _DOMINANT_SEVENTHS and qb in _DOMINANT_SEVENTHS and r == 6:
        kinds.append("tritone_substitution")
        notes.append(
            "Tritone substitution relationship: dominant chords a tritone apart share the "
            "tritone between their third and seventh."
        )

    distance, unmatched = minimal_motion(first.pitch_classes(), second.pitch_classes())
    if distance <= 2 and unmatched == 0:
        kinds.append("smooth")
        notes.append(f"Very smooth: the chords differ by {distance} semitone(s) in total.")
    return ChordRelationship(
        start=start, end=start + 1, common_tones=common, root_semitones=r,
        root_motion=_MOTION[r], kinds=tuple(kinds), transform=transform,
        voice_leading_distance=distance, unmatched_tones=unmatched,
        non_diatonic=non_diatonic, note=" ".join(notes),
    )  # fmt: skip


def analyze_relationships(
    chords: list[Chord], numerals: list[RomanNumeral] | None = None
) -> list[ChordRelationship]:
    """One relationship per adjacent pair. `numerals` (same length) marks pairs that involve a
    non-diatonic chord."""
    if numerals is not None and len(numerals) != len(chords):
        raise ValueError("numerals and chords must have the same length")
    out: list[ChordRelationship] = []
    for i in range(len(chords) - 1):
        flag: bool | None = None
        if numerals is not None:
            flag = numerals[i].category != "diatonic" or numerals[i + 1].category != "diatonic"
        out.append(chord_relationship(chords[i], chords[i + 1], start=i, non_diatonic=flag))
    return out
