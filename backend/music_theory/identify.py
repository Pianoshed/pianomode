"""Chord identification: from a set of notes to ranked chord interpretations.

Scores are heuristic ranking values, not probabilities. See `docs/music-theory.md` for the rules.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Literal

from music_theory.chord_symbols import format_chord
from music_theory.chords import CHORD_TYPES, Chord, ChordType
from music_theory.errors import TheoryError
from music_theory.intervals import Interval, interval_class, transpose_name
from music_theory.keys import Key
from music_theory.notes import (
    Note,
    NoteName,
    Preference,
    check_midi,
    parse_note,
    parse_note_name,
    spell_pitch_class,
)

NoteLike = int | str | NoteName | Note
Status = Literal["identified", "ambiguous", "no_reliable_label"]

# Small ranking nudges: rarer or less standard readings lose ties to common ones.
_PRIOR = {
    "altered": -1.5, "quartal3": -1.5, "quartal4": -1.5, "major7_flat5": -1.0, "major11": -1.0,
    "six_nine": -0.7, "add11": -0.5, "minor_add11": -0.5, "dominant11": -0.5,
    "dominant7_flat5": -0.3, "sus2": -0.2, "sus4": -0.2, "major6": -0.2, "minor6": -0.2,
    "power": 0.0, "add9": -0.3, "minor_add9": -0.3,
}  # fmt: skip
_ADDED = {
    "add9": ("M9",), "minor_add9": ("M9",), "add11": ("P11",), "minor_add11": ("P11",),
    "major6": ("M6",), "minor6": ("M6",), "six_nine": ("M6", "M9"),
}  # fmt: skip
_NATURAL = {5: "P", 9: "M", 11: "P", 13: "M"}  # quality an extension has when unaltered
_INTRINSIC_FIFTH = {"diminished", "diminished7", "half_diminished7", "augmented"}


@dataclass(frozen=True)
class ChordCandidate:
    chord: Chord
    symbol: str
    score: float  # ranking heuristic, NOT a probability
    required_tones: tuple[NoteName, ...]
    detected_tones: tuple[NoteName, ...]
    missing_tones: tuple[NoteName, ...]  # chord tones left out of the voicing
    extra_tones: tuple[NoteName, ...]  # notes added beyond the chord type
    bass: NoteName
    inversion: int | None  # None when the bass is not a chord tone (slash chord)
    rootless: bool
    added_tones: tuple[str, ...]  # e.g. ("M9",) for Cadd9
    altered_tones: tuple[str, ...]  # e.g. ("m9", "A9") for C7alt
    enharmonic_symbol: str | None
    assumptions: tuple[str, ...]


@dataclass(frozen=True)
class Identification:
    status: Status
    candidates: tuple[ChordCandidate, ...]
    pitch_classes: tuple[int, ...]
    bass: NoteName | None
    reason: str | None = None

    @property
    def best(self) -> ChordCandidate | None:
        return self.candidates[0] if self.candidates else None


def altered_tones(chord_type: ChordType) -> tuple[Interval, ...]:
    """Fifths and extensions that are not in their natural form (b9, #11, b13, ...)."""
    if chord_type.family != "tertian":
        return ()
    out = []
    for i in chord_type.formula:
        natural = _NATURAL.get(i.number)
        if natural is None or i.quality == natural:
            continue
        if i.number == 5 and chord_type.id in _INTRINSIC_FIFTH:
            continue
        out.append(i)
    return tuple(out)


@dataclass(frozen=True)
class _Input:
    pcs: tuple[int, ...]  # distinct pitch classes in first-seen order
    bass_pc: int
    bass_name: NoteName | None
    spelling: dict[int, NoteName]


def _parse_item(item: NoteLike) -> tuple[NoteName | None, int | None]:
    if isinstance(item, bool):
        raise TheoryError("Notes must be MIDI numbers, names or Note objects", code="invalid_note")
    if isinstance(item, int):
        return None, check_midi(item)
    if isinstance(item, Note):
        return item.name, item.midi
    if isinstance(item, NoteName):
        return item, None
    try:
        n = parse_note(item)
        return n.name, n.midi
    except TheoryError:
        return parse_note_name(item), None


def _normalize(notes: Sequence[NoteLike], bass: NoteName | str | None) -> _Input:
    if not notes:
        raise TheoryError("Give at least one note", code="no_notes")
    parsed = [_parse_item(n) for n in notes]
    with_octave = [m is not None for _, m in parsed]
    if any(with_octave) and not all(with_octave):
        raise TheoryError("Mix of notes with and without octaves", code="mixed_input")
    spelling: dict[int, NoteName] = {}
    pcs: list[int] = []
    for name, midi in parsed:
        pc = name.pitch_class if name is not None else (midi or 0) % 12
        if name is not None:
            spelling.setdefault(pc, name)
        if pc not in pcs:
            pcs.append(pc)
    bass_name: NoteName | None
    if bass is not None:
        bass_name = parse_note_name(bass) if isinstance(bass, str) else bass
        bass_pc = bass_name.pitch_class
        spelling.setdefault(bass_pc, bass_name)
        if bass_pc not in pcs:
            raise TheoryError("The bass note must be one of the notes", code="invalid_bass")
    elif all(with_octave):
        lowest = min(range(len(parsed)), key=lambda i: (parsed[i][1] or 0, i))
        name, midi = parsed[lowest]
        bass_pc = name.pitch_class if name is not None else (midi or 0) % 12
        bass_name = name
    else:
        bass_name, _ = parsed[0]
        bass_pc = bass_name.pitch_class if bass_name is not None else 0
    return _Input(tuple(pcs), bass_pc, bass_name, spelling)


def identify_chord(
    notes: Sequence[NoteLike],
    *,
    bass: NoteName | str | None = None,
    key: Key | None = None,
    prefer: Preference = "sharps",
    allow_rootless: bool = False,
    max_extra_tones: int = 0,
    max_candidates: int = 5,
    ambiguity_margin: float = 1.0,
    min_score: float = 0.0,
) -> Identification:
    """Name the chord(s) a set of notes could be.

    - MIDI numbers / `Note`s: the lowest note is the bass. Names without octaves: the first listed
      note is the bass unless `bass` is given.
    - Spelling comes from the input names when given, otherwise from `key`, otherwise `prefer`.
    - `allow_rootless` also offers rooted-elsewhere readings (e.g. F A C E as Dm9 without D).
    - Rooted readings scoring below `min_score` are dropped rather than ranked last, so a weak
      stretch (e.g. a whole-tone cluster as an altered chord) is not offered as a label.
      Rootless readings are opt-in and exempt.
    - `max_extra_tones` lets a reading include that many notes beyond the chord type, flagged as
      extra. The default (0) never forces a label onto an unexplained note.
    """
    data = _normalize(notes, bass)
    pcs = set(data.pcs)
    if len(pcs) < 2:
        return Identification(
            "no_reliable_label",
            (),
            data.pcs,
            data.bass_name,
            "A single pitch class is not a chord.",
        )

    def name_for(pc: int) -> NoteName:
        if pc in data.spelling:
            return data.spelling[pc]
        if key is not None:
            return key.signature.spell(pc)
        return spell_pitch_class(pc, prefer)

    candidates: list[ChordCandidate] = []
    roots = sorted(pcs) + (sorted(set(range(12)) - pcs) if allow_rootless else [])
    for root_pc in roots:
        root_present = root_pc in pcs
        rel = frozenset((p - root_pc) % 12 for p in pcs)
        for ctype in CHORD_TYPES.values():
            cand = _try_type(ctype, root_pc, root_present, rel, data, name_for, max_extra_tones)
            if cand is not None and (cand.rootless or cand.score >= min_score):
                candidates.append(cand)

    candidates.sort(key=lambda c: (-c.score, c.rootless, len(c.chord.type.formula), c.symbol))
    top = tuple(candidates[:max_candidates])
    if not top:
        if len(pcs) == 2:
            a, b = sorted(pcs)
            reason = (
                f"Two notes ({_interval_word(interval_class(a, b))}) are too few to name a chord "
                "reliably."
            )
        else:
            reason = f"No supported chord type explains all {len(pcs)} pitch classes."
        return Identification("no_reliable_label", (), data.pcs, data.bass_name, reason)
    ambiguous = len(top) > 1 and top[0].score - top[1].score < ambiguity_margin
    return Identification("ambiguous" if ambiguous else "identified", top, data.pcs, data.bass_name)


def _interval_word(semitones: int) -> str:
    return {
        1: "a minor second", 2: "a major second", 3: "a minor third", 4: "a major third",
        5: "a perfect fourth", 6: "a tritone", 7: "a perfect fifth",
    }.get(semitones, f"{semitones} semitones")  # fmt: skip


def _try_type(
    ctype: ChordType,
    root_pc: int,
    root_present: bool,
    rel: frozenset[int],
    data: _Input,
    namer: Callable[[int], NoteName],
    max_extra: int,
) -> ChordCandidate | None:
    formula_pcs = [i.semitones % 12 for i in ctype.formula]
    fset = set(formula_pcs)
    omit_pcs = {i.semitones % 12 for i in ctype.omissible}
    rootless = not root_present
    bass_rel = (data.bass_pc - root_pc) % 12

    if rootless:
        if (
            len(rel) < 3
            or ctype.family != "tertian"
            or not any(i.number == 7 for i in ctype.formula)
        ):
            return None
        guide = {i.semitones % 12 for i in ctype.formula if i.number in (3, 7)}
        if not guide <= rel or not rel <= fset - {0}:
            return None
        required = fset - omit_pcs - {0}
    else:
        required = fset - omit_pcs

    if not required <= rel:
        return None
    extras = set(rel - fset)
    slash = bass_rel in extras
    if slash:
        extras.discard(bass_rel)
    if len(extras) > max_extra:
        return None

    # The caller's own spelling of the root wins. Otherwise pick the spelling with the fewest
    # accidentals across the chord (Ebm6 over D#m6), preferring the key/preference choice on ties.
    if root_pc in data.spelling:
        options = [data.spelling[root_pc]]
    else:
        options = list(
            dict.fromkeys(
                [namer(root_pc), spell_pitch_class(root_pc, "flats"), spell_pitch_class(root_pc)]
            )
        )
    chord_root: NoteName | None = None
    tones: tuple[NoteName, ...] = ()
    best_cost = 10**6
    for option in options:
        try:
            spelled = tuple(transpose_name(option, i) for i in ctype.formula)
        except TheoryError:
            continue
        cost = sum(abs(t.accidental) for t in spelled)
        if cost < best_cost:
            chord_root, tones, best_cost = option, spelled, cost
    if chord_root is None:
        return None

    tone_by_pc = {t.pitch_class: t for t in tones}
    if bass_rel in fset:
        bass_name = tone_by_pc[data.bass_pc]
    else:
        bass_name = data.spelling.get(data.bass_pc) or namer(data.bass_pc)
    chord = Chord(chord_root, ctype, None if data.bass_pc == root_pc else bass_name)
    inversion = chord.inversion()

    detected = tuple(t for t in tones if (t.pitch_class - root_pc) % 12 in rel)
    missing = tuple(t for t in tones if (t.pitch_class - root_pc) % 12 not in rel)
    required_tones = tuple(t for t in tones if (t.pitch_class - root_pc) % 12 in required)
    extra_names = tuple(
        data.spelling.get((root_pc + e) % 12) or namer((root_pc + e) % 12) for e in sorted(extras)
    )

    score = 4.0 * len(detected) / len(tones)
    score -= 0.6 * len([m for m in missing if (m.pitch_class - root_pc) % 12 in omit_pcs])
    score -= 2.5 * len(extras)
    score += _PRIOR.get(ctype.id, 0.0)
    assumptions: list[str] = []
    if rootless:
        score -= 4.0
        assumptions.append("Root is not played; assumes a rootless voicing.")
    elif slash:
        score -= 2.0
        assumptions.append("Bass note is not a chord tone, so this reads as a slash chord.")
    elif inversion == 0:
        score += 2.0
    elif inversion is not None and inversion <= 2:
        score += 0.5
    elif inversion is not None:
        score -= 0.3
    for m in missing:
        if (m.pitch_class - root_pc) % 12 in omit_pcs and not rootless:
            iv = next(
                i for i in ctype.formula if i.semitones % 12 == (m.pitch_class - root_pc) % 12
            )
            assumptions.append(f"{iv.long.capitalize()} ({m}) is omitted.")
    for nm in extra_names:
        assumptions.append(
            f"{nm} is not part of {ctype.name.lower()} and is treated as an extra tone."
        )

    alt_root = spell_pitch_class(root_pc, "flats" if chord_root.accidental > 0 else "sharps")
    enharmonic: str | None = None
    if chord_root.accidental != 0 and alt_root != chord_root:
        try:
            alt_bass = (
                None
                if chord.bass is None
                else spell_pitch_class(
                    chord.bass.pitch_class, "flats" if chord_root.accidental > 0 else "sharps"
                )
            )
            enharmonic = format_chord(Chord(alt_root, ctype, alt_bass))
        except TheoryError:
            enharmonic = None

    added = tuple(_ADDED.get(ctype.id, ()))
    return ChordCandidate(
        chord=chord,
        symbol=format_chord(chord),
        score=round(score, 3),
        required_tones=required_tones,
        detected_tones=detected,
        missing_tones=missing,
        extra_tones=extra_names,
        bass=bass_name,
        inversion=inversion,
        rootless=rootless,
        added_tones=added,
        altered_tones=tuple(i.short for i in altered_tones(ctype)),
        enharmonic_symbol=enharmonic,
        assumptions=tuple(assumptions),
    )
