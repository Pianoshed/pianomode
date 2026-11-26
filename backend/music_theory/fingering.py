"""Curated scale fingering.

Fingering is *curated metadata*, not computed: a scale has fingering only if it is listed in
`data/fingering.json`. Anything else returns None, and callers must say "no curated fingering"
instead of inventing one. Fingerings are one octave, tonic to tonic, finger 1 = thumb.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from importlib import resources
from typing import Literal

from music_theory.errors import TheoryError
from music_theory.scales import Scale

Direction = Literal["ascending", "descending"]
_BLACK = frozenset({1, 3, 6, 8, 10})


class FingeringDataError(TheoryError):
    code = "invalid_fingering_data"


@dataclass(frozen=True)
class ScaleFingering:
    """Fingers for the notes of `Scale.notes(direction)` plus the closing tonic octave."""

    right_hand: tuple[int, ...]
    left_hand: tuple[int, ...]
    direction: Direction
    note: str


def _check(label: str, fingers: object, size: int) -> tuple[int, ...]:
    if not isinstance(fingers, list) or len(fingers) != size + 1:
        raise FingeringDataError(
            f"{label}: expected {size + 1} fingers (one octave, tonic to tonic)"
        )
    if not all(isinstance(f, int) and not isinstance(f, bool) and 1 <= f <= 5 for f in fingers):
        raise FingeringDataError(f"{label}: fingers must be whole numbers 1-5")
    if any(a == b for a, b in zip(fingers, fingers[1:], strict=False)):
        raise FingeringDataError(f"{label}: the same finger cannot play two notes in a row")
    return tuple(int(f) for f in fingers)


@lru_cache
def _table() -> dict[tuple[str, int], tuple[tuple[int, ...], tuple[int, ...]]]:
    text = resources.files("music_theory.data").joinpath("fingering.json").read_text("utf-8")
    payload = json.loads(text)
    out: dict[tuple[str, int], tuple[tuple[int, ...], tuple[int, ...]]] = {}
    for scale_id, by_pc in payload["scales"].items():
        for pc_text, hands in by_pc.items():
            pc = int(pc_text)
            if not 0 <= pc <= 11:
                raise FingeringDataError(f"{scale_id}: pitch class {pc} out of range")
            label = f"{scale_id}/{pc}"
            out[(scale_id, pc)] = (
                _check(label + " rh", hands["rh"], 7),
                _check(label + " lh", hands["lh"], 7),
            )
    return out


def curated_scale_ids() -> list[str]:
    return sorted({scale_id for scale_id, _ in _table()})


def scale_fingering(scale: Scale, direction: Direction = "ascending") -> ScaleFingering | None:
    """Curated fingering for `scale`, or None when none is curated. Enharmonic roots share one
    fingering (F-sharp and G-flat major use the same keys)."""
    found = _table().get((scale.definition.id, scale.root.pitch_class))
    if found is None:
        return None
    rh, lh = found
    if direction == "descending":
        rh, lh = rh[::-1], lh[::-1]
    return ScaleFingering(
        rh,
        lh,
        direction,
        "Standard one-octave fingering. Thumb passes under after the third or fourth finger.",
    )


def thumb_on_black_key(scale: Scale, fingering: ScaleFingering) -> bool:
    """Sanity check used by tests: curated fingerings never put the thumb on a black key."""
    pcs = [n.pitch_class for n in scale.notes("ascending")]
    pcs.append(pcs[0])
    if fingering.direction == "descending":
        pcs = pcs[::-1]
    return any(
        f == 1 and pc in _BLACK
        for hand in (fingering.right_hand, fingering.left_hand)
        for f, pc in zip(hand, pcs, strict=True)
    )
