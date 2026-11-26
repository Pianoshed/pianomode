"""Generated theory and ear-training exercises, with answer checking by the theory engine.

Design
- **Stateless and deterministic.** An exercise id is ``v<version>:<kind>:<difficulty>:<seed>``.
  The same id always regenerates the same exercise, so the server never has to store the answer
  and never trusts the client for it: checking an answer rebuilds the exercise from its id.
- **The engine decides what is right.** Expected answers come from the same notes, intervals,
  scales, chords, Roman-numeral and cadence code used everywhere else. Where a generated
  example could be read two ways (Am7 and C6/A hold the same notes) the generator rejects it
  and draws again, so a learner is never marked wrong for a legitimate reading.
- **Three levels of "right".** A correct answer with the wrong spelling (Db for C#) is graded
  ``enharmonic``: it counts as correct where the exercise cannot tell spellings apart (a
  highlighted piano key) and as not correct where spelling is the point (spell a scale).
- **No language model is involved** in generating or grading.

Bumping ``GENERATOR_VERSION`` is required whenever a generator would produce a different exercise
for the same seed; old ids then fail with ``unsupported_exercise_version`` instead of silently
changing meaning.
"""

from __future__ import annotations

import random
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from music_theory.chord_symbols import ChordSymbolError, parse_chord
from music_theory.chords import CHORD_TYPES, Chord, inversion_name, make_chord
from music_theory.errors import TheoryError
from music_theory.harmony import diatonic_chords
from music_theory.identify import identify_chord
from music_theory.intervals import (
    Interval,
    parse_interval,
    transpose_name,
    transpose_note,
)
from music_theory.keys import Key
from music_theory.notes import (
    Note,
    NoteName,
    note_from_midi,
    parse_note,
    parse_note_name,
    spell_pitch_class,
)
from music_theory.progressions import default_library, realize
from music_theory.roman import analyze_chord, analyze_progression, chord_from_roman, find_cadences
from music_theory.scales import make_scale
from music_theory.voice_leading import evaluate_transition
from music_theory.voicings import Voicing

GENERATOR_VERSION = 1
Difficulty = Literal["beginner", "intermediate", "advanced", "expert"]
DIFFICULTIES: tuple[str, ...] = ("beginner", "intermediate", "advanced", "expert")
Status = Literal["correct", "enharmonic", "partial", "incorrect", "unreadable"]
AnswerFormat = Literal["choice", "text", "note_names", "note_set", "chord_symbols"]
MAX_ANSWER_ITEMS = 32
MAX_ANSWER_LENGTH = 64
_MAX_SEED = 2**31 - 1
_ID_RE = re.compile(r"^v(\d+):([a-z][a-z0-9_]*):([a-z]+):(\d{1,10})$")


class ExerciseError(TheoryError):
    code = "invalid_exercise"


# ------------------------------------------------------------------ public types


@dataclass(frozen=True)
class PlayEvent:
    """Notes to sound together, positioned in beats (render at ``Exercise.tempo``)."""

    notes: tuple[int, ...]
    start: float
    duration: float


@dataclass(frozen=True)
class Exercise:
    """What the learner sees. Contains nothing that gives the answer away: ear-training
    exercises have an empty ``show`` and a prompt that does not name the answer."""

    id: str
    kind: str
    difficulty: str
    seed: int
    topic: str
    prompt: str
    answer_format: AnswerFormat
    answer_help: str
    choices: tuple[str, ...]
    show: tuple[int, ...]  # MIDI notes to highlight on the keyboard
    play: tuple[PlayEvent, ...]  # audio to play; empty when there is none
    tempo: int
    hint: str


@dataclass(frozen=True)
class ItemResult:
    index: int
    given: str
    correct: bool
    expected: str


@dataclass(frozen=True)
class Grade:
    exercise_id: str
    status: Status
    correct: bool
    feedback: str
    correct_answer: str  # shown only after answering
    explanation: str
    items: tuple[ItemResult, ...] = ()


@dataclass(frozen=True)
class KindInfo:
    kind: str
    title: str
    topic: str
    objective: str
    prerequisites: tuple[str, ...]
    ear_training: bool = False


# ------------------------------------------------------------------ internal plumbing


class _Retry(Exception):
    """Raised by a generator when the random draw is unusable; the next draw is tried."""


@dataclass(frozen=True)
class _Built:
    prompt: str
    format: AnswerFormat
    check: str
    data: dict[str, Any]
    reference: Any  # an answer that grades as correct (used by tests and administrators)
    correct_display: str
    explanation: str
    hint: str = ""
    help: str = ""
    choices: tuple[str, ...] = ()
    show: tuple[int, ...] = ()
    play: tuple[PlayEvent, ...] = ()
    tempo: int = 80
    spelling: bool = False  # does spelling matter for this exercise?


_Generator = Callable[[random.Random, str], _Built]


def _ordinal(n: int) -> str:
    words = {1: "first", 2: "second", 3: "third", 4: "fourth", 5: "fifth", 6: "sixth", 7: "seventh"}
    return words.get(n, f"{n}th")


def _level(d: str) -> int:
    return DIFFICULTIES.index(d)


def _names(names: Sequence[NoteName]) -> str:
    return " ".join(str(n) for n in names)


# Pools grow with difficulty. Accidental-heavy roots are held back for later levels.
_NATURALS = ["C", "D", "E", "F", "G", "A", "B"]
_ALL_ROOTS = ["C", "C#", "Db", "D", "Eb", "E", "F", "F#", "Gb", "G", "Ab", "A", "Bb", "B"]
_ROOTS: dict[str, list[str]] = {
    "beginner": _NATURALS,
    "intermediate": [*_NATURALS, "F#", "Bb", "Eb", "Ab"],
    "advanced": _ALL_ROOTS,
    "expert": [*_ALL_ROOTS, "Cb", "E#"],
}
_MAJOR_KEYS: dict[str, list[str]] = {
    "beginner": ["C", "G", "D", "F", "Bb"],
    "intermediate": ["C", "G", "D", "A", "E", "F", "Bb", "Eb", "Ab"],
    "advanced": ["C", "G", "D", "A", "E", "B", "F", "Bb", "Eb", "Ab", "Db", "F#", "Gb"],
    "expert": ["C", "G", "D", "A", "E", "B", "F", "Bb", "Eb", "Ab", "Db", "F#", "Gb", "C#", "Cb"],
}
_MINOR_KEYS: dict[str, list[str]] = {
    "beginner": ["A", "E", "D"],
    "intermediate": ["A", "E", "D", "B", "G", "C", "F#", "F"],
    "advanced": ["A", "E", "D", "B", "G", "C", "F", "F#", "C#", "G#", "Bb", "Eb"],
    "expert": ["A", "E", "D", "B", "G", "C", "F", "F#", "C#", "G#", "Bb", "Eb", "D#", "A#", "Ab"],
}


def _describe_fifths(fifths: int) -> str:
    if fifths == 0:
        return "no sharps or flats"
    unit = "sharp" if fifths > 0 else "flat"
    n = abs(fifths)
    return f"{n} {unit}{'' if n == 1 else 's'}"


def _midi_name(midi: int) -> str:
    return note_from_midi(midi).format()


def _sharp_flat_name(midi: int, octave: bool = True) -> str:
    sharp, flat = note_from_midi(midi, "sharps"), note_from_midi(midi, "flats")
    s, f = (sharp.format(), flat.format()) if octave else (str(sharp.name), str(flat.name))
    return s if s == f else f"{s} / {f}"


def _close_voicing(chords: Sequence[Chord], octave: int = 4) -> list[tuple[int, ...]]:
    """Each chord in the inversion nearest the previous one (smooth, easy to hear)."""
    out: list[tuple[int, ...]] = []
    for chord in chords:
        options = [tuple(chord.midi_notes(octave, i)) for i in range(len(chord.tones()))]
        if out:
            prev = sum(out[-1]) / len(out[-1])
            options.sort(key=lambda o: (abs(sum(o) / len(o) - prev), o))
        out.append(options[0])
    return out


def _events(voicings: Sequence[tuple[int, ...]], beats: float = 2.0) -> tuple[PlayEvent, ...]:
    return tuple(PlayEvent(v, i * beats, beats) for i, v in enumerate(voicings))


# ------------------------------------------------------------------ interval names


def _interval_lookup() -> dict[str, Interval]:
    table: dict[str, Interval] = {}
    for number in range(1, 16):
        for quality in ("P", "M", "m", "A", "d"):
            try:
                iv = Interval.of(quality, number)
            except TheoryError:
                continue
            table[iv.long.lower()] = iv
            table[iv.short.lower() if quality in "Ad" else iv.short] = iv
    for word, letter in (("aug", "A"), ("dim", "d")):
        for number in range(1, 16):
            try:
                iv = Interval.of(letter, number)
            except TheoryError:
                continue
            table[f"{word}{number}"] = iv
            table[f"{word} {number}"] = iv
    table["tritone"] = Interval.of("A", 4)
    return table


_INTERVAL_NAMES = _interval_lookup()


_GLOSS_RE = re.compile(r"^(?P<short>[^()]+?)\s*\((?P<long>[^()]+)\)$")


def parse_interval_answer(text: str) -> Interval:
    """Short names (M3, A4, d5) and long names (major third, perfect fifth). The form shown after
    a wrong answer, `m3 (minor third)`, is accepted too; if its two halves name different
    intervals the answer is refused rather than guessed."""
    cleaned = " ".join(text.strip().split())
    gloss = _GLOSS_RE.match(cleaned)
    if gloss:
        short, long = parse_interval_answer(gloss["short"]), parse_interval_answer(gloss["long"])
        if short != long:
            raise ExerciseError(
                f"{text!r} names two different intervals ({short.short} and {long.short}).",
                code="unreadable_interval",
            )
        return short
    try:
        return parse_interval(cleaned)
    except TheoryError:
        pass
    found = _INTERVAL_NAMES.get(cleaned) or _INTERVAL_NAMES.get(cleaned.lower())
    if found is None:
        raise ExerciseError(
            f"{text!r} is not an interval name. Use M3, P5, A4 or d5, or write it out "
            "(major third).",
            code="unreadable_interval",
        )
    return found


# ------------------------------------------------------------------ generators: notes, intervals


def _g_note_name(rng: random.Random, d: str) -> _Built:
    lvl = _level(d)
    white = [m for m in range(48, 85) if m % 12 in (0, 2, 4, 5, 7, 9, 11)]
    midi = (
        rng.choice(white)
        if lvl == 0
        else rng.randrange(48 if lvl < 2 else 36, 85 if lvl < 2 else 97)
    )
    octave = lvl >= 2
    black = midi % 12 not in (0, 2, 4, 5, 7, 9, 11)
    prompt = "Name the highlighted key" + (
        " with its octave number (for example C#4)." if octave else "."
    )
    if black:
        prompt += " Black keys have two names; either one is accepted."
    reference = note_from_midi(midi).format() if octave else str(note_from_midi(midi).name)
    return _Built(
        prompt,
        "text",
        "note",
        {"midi": midi, "octave": octave},
        reference,
        _sharp_flat_name(midi, octave),
        "Middle C is C4 (MIDI 60). Each step up the keyboard, white or black, is one semitone; "
        "the pattern of notes repeats every 12 semitones.",
        "Find the nearest group of two or three black keys: C is just left of the group of two.",
        "A note name, for example F or C#" + (" with octave, for example C#4" if octave else ""),
        show=(midi,),
        play=(PlayEvent((midi,), 0, 2),),
    )


_INTERVAL_POOLS: dict[str, list[str]] = {
    "beginner": ["M2", "M3", "P4", "P5", "M6", "M7", "P8"],
    "intermediate": ["m2", "M2", "m3", "M3", "P4", "P5", "m6", "M6", "m7", "M7", "P8"],
    "advanced": [
        "m2",
        "M2",
        "m3",
        "M3",
        "P4",
        "A4",
        "d5",
        "P5",
        "m6",
        "M6",
        "m7",
        "M7",
        "P8",
        "m9",
        "M9",
        "m10",
        "M10",
        "P11",
        "M13",
    ],
    "expert": [
        "m2",
        "M2",
        "A2",
        "d3",
        "m3",
        "M3",
        "A3",
        "d4",
        "P4",
        "A4",
        "d5",
        "P5",
        "A5",
        "d6",
        "m6",
        "M6",
        "A6",
        "d7",
        "m7",
        "M7",
        "m9",
        "M9",
        "A9",
        "m10",
        "M10",
        "P11",
        "A11",
        "m13",
        "M13",
    ],
}


def _g_interval_identify(rng: random.Random, d: str) -> _Built:
    pool = _INTERVAL_POOLS[d]
    iv = parse_interval(rng.choice(pool))
    low = Note(parse_note_name(rng.choice(_ROOTS[d])), rng.choice((3, 4)))
    high = transpose_note(low, iv)
    if high.midi > 108:
        raise _Retry
    choices: tuple[str, ...] = ()
    fmt: AnswerFormat = "text"
    if _level(d) <= 1:
        others = [s for s in pool if s != iv.short]
        picked = rng.sample(others, 3)
        picked.append(iv.short)
        rng.shuffle(picked)
        choices, fmt = tuple(picked), "choice"
    return _Built(
        f"What is the interval from {low.format()} up to {high.format()}?",
        fmt,
        "interval",
        {"interval": iv, "low": low, "high": high},
        iv.short,
        f"{iv.short} ({iv.long})",
        f"{low.name} to {high.name} spans {iv.number} letter names ({_ordinal(iv.number)}) and "
        f"{iv.semitones} semitones, which makes it a {iv.long}. The letter count gives the number; "
        "the semitone count gives the quality.",
        "Count letter names for the number, then semitones for the quality.",
        "For example M3, P5, m7, A4 or d5",
        choices,
        (low.midi, high.midi),
        (PlayEvent((low.midi,), 0, 1), PlayEvent((high.midi,), 1, 1)),
        spelling=True,
    )


def _g_interval_build(rng: random.Random, d: str) -> _Built:
    lvl = _level(d)
    pool = [s for s in _INTERVAL_POOLS[d] if parse_interval(s).number <= 8]
    iv = parse_interval(rng.choice(pool))
    root = parse_note_name(rng.choice(_ROOTS[d]))
    down = lvl >= 2 and rng.random() < 0.4
    answer = transpose_name(root, iv, down=down)
    way = "below" if down else "above"
    return _Built(
        f"What note is a {iv.long} {way} {root}?",
        "text",
        "note_spelled",
        {"name": answer},
        str(answer),
        str(answer),
        f"A {iv.long} {way} {root} uses the letter {_ordinal(iv.number)} {way} {root.letter} and "
        f"spans {iv.semitones} semitones, so the note is {answer}. Spelling matters: the letter is "
        "fixed by the interval number, the accidental by its size.",
        "Choose the letter first, then add the sharp or flat that makes the size right.",
        "A note name such as Bb or F#",
        spelling=True,
    )


# ------------------------------------------------------------------ generators: scales, keys

_SCALES_BY_LEVEL: dict[str, list[str]] = {
    "beginner": ["major"],
    "intermediate": [
        "major",
        "natural_minor",
        "harmonic_minor",
        "melodic_minor",
        "major_pentatonic",
        "minor_pentatonic",
    ],
    "advanced": [
        "major",
        "natural_minor",
        "harmonic_minor",
        "melodic_minor",
        "dorian",
        "phrygian",
        "lydian",
        "mixolydian",
        "locrian",
        "major_pentatonic",
        "minor_pentatonic",
        "blues",
    ],
    "expert": [
        "harmonic_major",
        "whole_tone",
        "diminished_whole_half",
        "diminished_half_whole",
        "dorian",
        "phrygian",
        "lydian",
        "mixolydian",
        "locrian",
        "melodic_minor",
        "blues",
    ],
}


def _g_scale_construct(rng: random.Random, d: str) -> _Built:
    scale_id = rng.choice(_SCALES_BY_LEVEL[d])
    root = rng.choice(_MAJOR_KEYS[d] if scale_id == "major" else _ROOTS[d])
    scale = make_scale(root, scale_id)
    notes = scale.notes("ascending")
    return _Built(
        f"Spell the {scale.definition.name} scale starting on {root}, going up one octave "
        "(do not repeat the top note).",
        "note_names",
        "note_list",
        {"names": notes},
        [str(n) for n in notes],
        _names(notes),
        f"{scale.definition.name} on {root}: {_names(notes)}."
        + (
            " A seven-note scale uses each letter name once, in alphabetical order."
            if len(notes) == 7
            else ""
        ),
        "Write the letters in order first, then fix each accidental from the scale formula.",
        "Notes in order, for example C D E F G A B",
        spelling=True,
    )


def _g_key_signature(rng: random.Random, d: str) -> _Built:
    lvl = _level(d)
    minor = lvl >= 1 and rng.random() < 0.4
    tonic = rng.choice(_MINOR_KEYS[d] if minor else _MAJOR_KEYS[d])
    key = Key(parse_note_name(tonic), "minor" if minor else "major")
    fifths = key.signature.fifths
    if rng.random() < 0.5:
        return _Built(
            f"How many sharps or flats are in the key signature of {key}?",
            "text",
            "keysig",
            {"fifths": fifths},
            _describe_fifths(fifths),
            _describe_fifths(fifths),
            f"{key} has {key.signature.describe()}. Sharps are added in the order F C G D A E B "
            "and flats in the reverse order.",
            "Relate the key to C major or A minor (no accidentals) by counting steps round the "
            "circle of fifths.",
            "For example '3 sharps', '2 flats' or 'none'",
            spelling=True,
        )
    mode = "minor" if minor else "major"
    return _Built(
        f"Which {mode} key has {_describe_fifths(fifths)}?",
        "text",
        "note_spelled",
        {"name": key.tonic, "mode": mode},
        str(key.tonic),
        f"{key.tonic} {mode}",
        f"{_describe_fifths(fifths)} belongs to {key.tonic} {mode} (its relative "
        f"{key.relative().mode} is {key.relative().tonic}).",
        "Count round the circle of fifths from C major (or A minor).",
        f"The tonic note of the {mode} key, for example Eb",
        spelling=True,
    )


_KEYSIG_RE = re.compile(r"^(\d+)\s*(sharps?|flats?|#|♯|b|♭)$", re.IGNORECASE)
_NONE_RE = re.compile(
    r"^(0|no|none|zero|natural)(\s+(sharps|flats|accidentals)(\s+(or|and)\s+(sharps|flats))?)?$",
    re.IGNORECASE,
)


def _parse_keysig(text: str) -> int:
    cleaned = " ".join(text.strip().split())
    if _NONE_RE.match(cleaned):
        return 0
    m = _KEYSIG_RE.match(cleaned)
    if not m:
        raise ExerciseError(
            f"Could not read {text!r}. Write a number with sharps or flats (3 sharps) or 'none'.",
            code="unreadable_key_signature",
        )
    count = int(m.group(1))
    if count == 0:
        return 0
    flats = m.group(2).lower() in ("flat", "flats", "b", "♭")
    return -count if flats else count


# ------------------------------------------------------------------ generators: chords

_TRIAD_POOLS: dict[str, list[str]] = {
    "beginner": ["major", "minor"],
    "intermediate": ["major", "minor", "diminished", "augmented", "sus2", "sus4"],
    "advanced": ["major", "minor", "diminished", "augmented", "sus2", "sus4"],
    "expert": ["major", "minor", "diminished", "augmented", "sus2", "sus4"],
}
_SEVENTH_POOLS: dict[str, list[str]] = {
    "beginner": ["major7", "minor7", "dominant7"],
    "intermediate": ["major7", "minor7", "dominant7", "half_diminished7", "major6", "minor6"],
    "advanced": [
        "major7",
        "minor7",
        "dominant7",
        "half_diminished7",
        "diminished7",
        "minor_major7",
        "major6",
        "minor6",
        "dominant7_flat5",
        "dominant7_sharp5",
    ],
    "expert": [
        "major7",
        "minor7",
        "dominant7",
        "half_diminished7",
        "diminished7",
        "minor_major7",
        "major6",
        "minor6",
        "dominant7_flat5",
        "dominant7_sharp5",
        "major7_sharp5",
    ],
}
_EXTENSION_POOLS: dict[str, list[str]] = {
    "beginner": ["add9", "dominant9", "major9"],
    "intermediate": ["add9", "dominant9", "major9", "minor9", "minor_add9", "six_nine"],
    "advanced": [
        "add9",
        "dominant9",
        "major9",
        "minor9",
        "dominant7_flat9",
        "dominant7_sharp9",
        "dominant7_sharp11",
        "dominant7_flat13",
        "minor11",
        "dominant13",
    ],
    "expert": [
        "dominant9",
        "major9",
        "minor9",
        "minor_major9",
        "dominant7_flat9",
        "dominant7_sharp9",
        "dominant7_sharp11",
        "dominant7_flat13",
        "minor11",
        "dominant13",
        "major13",
        "minor13",
        "altered",
    ],
}


def _chord_root_pool(d: str) -> list[str]:
    return _ROOTS[d]


def _build_chord_exercise(rng: random.Random, d: str, pools: dict[str, list[str]]) -> _Built:
    type_id = rng.choice(pools[d])
    root = rng.choice(_chord_root_pool(d))
    chord = make_chord(root, type_id)
    tones = chord.tones()
    return _Built(
        f"Spell {chord} ({chord.type.name.lower()}): which notes does it contain?",
        "note_set",
        "note_set",
        {"names": tones},
        [str(t) for t in tones],
        _names(tones),
        f"{chord} = "
        + " + ".join(f"{t} ({i.short})" for t, i in zip(tones, chord.type.formula, strict=True))
        + ".",
        "Stack the intervals from the root: "
        + ", ".join(i.short for i in chord.type.formula)
        + ".",
        "Note names in any order (F# A C#), or press the keys on the piano",
        spelling=True,
    )


def _g_triad_build(rng: random.Random, d: str) -> _Built:
    return _build_chord_exercise(rng, d, _TRIAD_POOLS)


def _g_seventh_build(rng: random.Random, d: str) -> _Built:
    return _build_chord_exercise(rng, d, _SEVENTH_POOLS)


def _same_chord_reading(chord: Chord, notes: list[Note]) -> bool:
    """Is `chord` the unique best reading of `notes`? Rejects ambiguous examples."""
    result = identify_chord(notes, max_candidates=4)
    best = result.best
    if result.status != "identified" or best is None:
        return False
    return (
        best.chord.root.pitch_class == chord.root.pitch_class
        and best.chord.type.id == chord.type.id
        and best.chord.bass_name.pitch_class == chord.bass_name.pitch_class
    )


def _build_identify(rng: random.Random, d: str, pools: dict[str, list[str]]) -> _Built:
    lvl = _level(d)
    type_id = rng.choice(pools[d])
    root = parse_note_name(rng.choice(_chord_root_pool(d)))
    base = make_chord(root, type_id)
    size = len(base.tones())
    inversion = 0 if lvl == 0 else rng.randrange(min(size, 4))
    chord = base.with_inversion(inversion)
    notes = chord.notes(rng.choice((3, 4)), inversion)
    if not _same_chord_reading(chord, notes) or max(n.midi for n in notes) > 105:
        raise _Retry
    show = tuple(n.midi for n in notes)
    names_in_prompt = lvl == 0
    prompt = "Name this chord"
    prompt += f" (notes: {' '.join(str(n.name) for n in notes)})." if names_in_prompt else "."
    if inversion:
        prompt += " The lowest note is not the root, so use a slash chord such as C/E."
    return _Built(
        prompt,
        "text",
        "chord",
        {"chord": chord},
        str(chord),
        str(chord),
        f"The notes {' '.join(str(n.name) for n in notes)} form {base} "
        f"({base.type.name.lower()}): "
        + " ".join(str(t) for t in base.tones())
        + (
            f". {inversion_name(inversion).capitalize()}: {chord.bass_name} is in the bass, "
            f"written {chord}."
            if inversion
            else "."
        ),
        "Look for notes a third apart, stacked; the bottom of the stack is the root.",
        "A chord symbol such as Dm7, Bb or Cmaj7/E",
        show=show,
        play=(PlayEvent(show, 0, 3),),
        spelling=False,
    )


def _g_triad_identify(rng: random.Random, d: str) -> _Built:
    return _build_identify(rng, d, _TRIAD_POOLS)


def _g_seventh_identify(rng: random.Random, d: str) -> _Built:
    return _build_identify(rng, d, _SEVENTH_POOLS)


def _g_extension_identify(rng: random.Random, d: str) -> _Built:
    return _build_identify(rng, d, _EXTENSION_POOLS)


def _g_inversion_identify(rng: random.Random, d: str) -> _Built:
    lvl = _level(d)
    pool = (_TRIAD_POOLS if lvl < 2 else _SEVENTH_POOLS)[d]
    base = make_chord(rng.choice(_chord_root_pool(d)), rng.choice(pool))
    size = len(base.tones())
    inversion = rng.randrange(size)
    notes = base.notes(rng.choice((3, 4)), inversion)
    choices = tuple(inversion_name(i) for i in range(size))
    chosen = inversion_name(inversion)
    reason = f"{base.tones()[inversion]} is the lowest note" + (
        ", the root" if inversion == 0 else f", the {_ordinal(inversion * 2 + 1)} of the chord"
    )
    show = tuple(n.midi for n in notes)
    return _Built(
        f"Which inversion of {base} is shown?",
        "choice",
        "choice",
        {},
        chosen,
        chosen,
        f"{reason}, so this is {chosen}. The inversion is named by which chord tone is lowest, "
        "not by the order of the other notes.",
        "Find the lowest note and ask which chord tone it is: root, third, fifth or seventh.",
        "",
        choices,
        show,
        (PlayEvent(show, 0, 3),),
    )


# ------------------------------------------------------------------ generators: harmony


def _key_text(key: Key) -> str:
    return f"{key.tonic} {'natural minor' if key.mode == 'minor' else key.mode}"


def _g_diatonic_chord(rng: random.Random, d: str) -> _Built:
    lvl = _level(d)
    if lvl == 3 and rng.random() < 0.7:
        scale_id = rng.choice(["harmonic_minor", "dorian", "mixolydian", "lydian"])
        root = rng.choice(_ROOTS["advanced"])
        scale, label = make_scale(root, scale_id), f"{root} {scale_id.replace('_', ' ')}"
    else:
        minor = lvl >= 1 and rng.random() < 0.5
        tonic = rng.choice(_MINOR_KEYS[d] if minor else _MAJOR_KEYS[d])
        key = Key(parse_note_name(tonic), "minor" if minor else "major")
        scale, label = key.scale(), _key_text(key)
    size: Literal[3, 4] = 4 if lvl >= 2 or (lvl == 1 and rng.random() < 0.4) else 3
    degree = rng.randrange(1, 8)
    found = diatonic_chords(scale, size)[degree - 1]
    if found.chord is None:
        raise _Retry
    kind = "seventh chord" if size == 4 else "triad"
    tones = found.tones
    return _Built(
        f"In {label}, what is the diatonic {kind} built on the {_ordinal(degree)} degree?",
        "text",
        "chord",
        {"chord": found.chord},
        str(found.chord),
        str(found.chord),
        f"Stack thirds on degree {degree} using only notes of {label}: {_names(tones)}, which is "
        f"{found.chord}.",
        "Write the scale, then take every other note starting on the chosen degree.",
        "A chord symbol such as Em7 or F#dim",
        spelling=True,
    )


_NUMERAL_POOLS: dict[str, dict[str, list[str]]] = {
    "beginner": {"major": ["I", "ii", "iii", "IV", "V", "vi", "vii°"], "minor": []},
    "intermediate": {
        "major": ["I", "ii", "IV", "V", "vi", "V7", "ii7", "Imaj7", "IVmaj7", "vi7", "I6", "V6"],
        "minor": ["i", "iv", "v", "VI", "VII", "III", "i6", "iv6", "V", "V7"],
    },
    "advanced": {
        "major": [
            "ii7",
            "V7",
            "V/V",
            "V7/V",
            "V7/ii",
            "V7/vi",
            "V7/IV",
            "bVI",
            "bVII",
            "iv",
            "bIII",
            "viiø7",
            "IV6",
            "iii7",
        ],
        "minor": ["iv7", "V7", "V7/iv", "V7/III", "VI", "VII", "III", "iiø7", "i7", "V7/VI"],
    },
    "expert": {
        "major": [
            "V7/V",
            "V7/ii",
            "V7/iii",
            "V7/vi",
            "viio7/V",
            "viio7/ii",
            "bVI",
            "bVII",
            "iv7",
            "bIII",
            "bII6",
            "bVImaj7",
            "iiø7",
            "Imaj7",
        ],
        "minor": ["V7/iv", "V7/III", "V7/VI", "viio7/V", "iv7", "iiø7", "bII6", "VImaj7", "IVmaj7"],
    },
}


def _numeral_case(rng: random.Random, d: str) -> tuple[Key, Chord, Any]:
    pools = _NUMERAL_POOLS[d]
    minor = bool(pools["minor"]) and rng.random() < 0.45
    tonic = rng.choice(_MINOR_KEYS[d] if minor else _MAJOR_KEYS[d])
    key = Key(parse_note_name(tonic), "minor" if minor else "major")
    chord = chord_from_roman(rng.choice(pools["minor" if minor else "major"]), key)
    analysis = analyze_chord(chord, key)
    if analysis.alternatives or max(n.midi for n in chord.notes(4)) > 100:
        raise _Retry  # an ambiguous reading would make "the" numeral arguable
    return key, chord, analysis


def _numeral_equal(a: Chord, b: Chord) -> bool:
    return (
        a.root.pitch_class == b.root.pitch_class
        and a.type.id == b.type.id
        and a.bass_name.pitch_class == b.bass_name.pitch_class
    )


def _g_roman_numeral(rng: random.Random, d: str) -> _Built:
    key, chord, analysis = _numeral_case(rng, d)
    show = tuple(chord.midi_notes(4))
    extra = f" ({analysis.function})" if analysis.function else ""
    return _Built(
        f"In {_key_text(key)}, give the Roman numeral for {chord}.",
        "text",
        "numeral",
        {"key": key, "chord": chord, "figure": analysis.figure},
        analysis.figure,
        analysis.figure,
        f"{chord} in {_key_text(key)} is {analysis.figure}{extra}"
        + (
            f"; it is {analysis.category.replace('_', ' ')}"
            if analysis.category != "diatonic"
            else ""
        )
        + (f", {analysis.note}" if analysis.note else "")
        + ".",
        "Find the chord root's scale degree; capitals are major, lower case minor; add ° for "
        "diminished, b for a lowered degree, and /X for a chord that points to degree X.",
        "For example V7, ii, bVI, vii° or V7/V",
        show=show,
        play=(PlayEvent(show, 0, 3),),
    )


def _g_roman_to_chord(rng: random.Random, d: str) -> _Built:
    key, chord, analysis = _numeral_case(rng, d)
    return _Built(
        f"In {_key_text(key)}, write the chord for {analysis.figure}.",
        "text",
        "chord",
        {"chord": chord},
        str(chord),
        str(chord),
        f"{analysis.figure} in {_key_text(key)} is {chord}: " + _names(chord.tones()) + ".",
        "Find the scale degree, then apply the quality shown by the numeral.",
        "A chord symbol such as Bb or A7",
        spelling=True,
        show=tuple(chord.midi_notes(4)),
    )


def _g_progression_build(rng: random.Random, d: str) -> _Built:
    lvl = _level(d)
    library = default_library()
    templates = [t for t in library.search() if _level(t.difficulty) <= lvl]
    if not templates:
        raise _Retry
    template = rng.choice(sorted(templates, key=lambda t: t.id))
    minor = template.mode == "minor"
    tonic = rng.choice(_MINOR_KEYS[d] if minor else _MAJOR_KEYS[d])
    key = Key(parse_note_name(tonic), template.mode)
    vocab: Literal["triads", "sevenths"] = (
        "triads" if lvl == 0 or (lvl == 1 and rng.random() < 0.5) else "sevenths"
    )
    prog = realize(template, key, vocab)
    chords = [c.chord for c in prog.chords]
    if len(chords) > 16:
        raise _Retry
    numerals = [c.roman or "?" for c in prog.chords]
    return _Built(
        f"Write {template.name} in {_key_text(key)} as chord symbols ({' '.join(numerals)}).",
        "chord_symbols",
        "chord_list",
        {"chords": chords},
        [str(c) for c in chords],
        " ".join(str(c) for c in chords),
        f"{template.name} in {_key_text(key)}: "
        + " – ".join(f"{n} = {c}" for n, c in zip(numerals, chords, strict=True))
        + ".",
        "Turn each Roman numeral into a chord one at a time.",
        "One chord symbol per chord, in order",
        spelling=True,
    )


_CADENCE_PLANS: dict[str, dict[str, list[list[str]]]] = {
    # kind -> level group -> chord-numeral sequences (major key; minor key via capital rules)
    "authentic": {
        "basic": [["V", "I"], ["I", "V", "I"], ["IV", "V", "I"]],
        "rich": [["ii7", "V7", "Imaj7"], ["IV", "V7", "I"], ["vi", "ii7", "V7", "I"], ["V7", "I6"]],
    },
    "plagal": {
        "basic": [["IV", "I"], ["I", "IV", "I"]],
        "rich": [["IVmaj7", "Imaj7"], ["IV6", "I"]],
    },
    "half": {
        "basic": [["I", "V"], ["IV", "V"], ["vi", "V"]],
        "rich": [["ii7", "V7"], ["Imaj7", "V7"], ["IV", "V"], ["vi", "ii", "V"]],
    },
    "deceptive": {
        "basic": [["V", "vi"], ["IV", "V", "vi"]],
        "rich": [["ii7", "V7", "vi"], ["V7", "vi"]],
    },
}
_MINOR_FIX = {
    "V": "V",
    "I": "i",
    "IV": "iv",
    "vi": "VI",
    "ii7": "iiø7",
    "Imaj7": "i7",
    "V7": "V7",
    "I6": "i6",
    "ii": "iio",
    "IV6": "iv6",
    "IVmaj7": "iv7",
}
CADENCE_LABELS = {
    "authentic": "authentic cadence (V–I)",
    "plagal": "plagal cadence (IV–I)",
    "half": "half cadence (ends on V)",
    "deceptive": "deceptive cadence (V–vi)",
}
_CADENCE_CHOICES = tuple(CADENCE_LABELS.values())


def _cadence_case(rng: random.Random, d: str) -> tuple[Key, str, list[Chord]]:
    lvl = _level(d)
    kinds = ["authentic", "plagal", "half"] + (["deceptive"] if lvl >= 1 else [])
    kind = rng.choice(kinds)
    group = "basic" if lvl == 0 or (lvl == 1 and rng.random() < 0.5) else "rich"
    minor = lvl >= 2 and rng.random() < 0.4
    tonic = rng.choice(_MINOR_KEYS[d] if minor else _MAJOR_KEYS[d])
    key = Key(parse_note_name(tonic), "minor" if minor else "major")
    plan = rng.choice(_CADENCE_PLANS[kind][group])
    numerals = [_MINOR_FIX.get(n, n) for n in plan] if minor else plan
    chords = [chord_from_roman(n, key) for n in numerals]
    cadences = [
        c for c in find_cadences(analyze_progression(chords, key)) if c.end == len(chords) - 1
    ]
    if [c.kind for c in cadences] != [kind]:
        raise _Retry  # the engine does not read the phrase ending as intended
    return key, kind, chords


def _g_cadence_identify(rng: random.Random, d: str) -> _Built:
    key, kind, chords = _cadence_case(rng, d)
    voicings = _close_voicing(chords)
    answer = CADENCE_LABELS[kind]
    return _Built(
        f"In {_key_text(key)}, a phrase ends {' – '.join(str(c) for c in chords)}. "
        "Which cadence is this?",
        "choice",
        "choice",
        {},
        answer,
        answer,
        f"The last two chords, {chords[-2]} then {chords[-1]}, are an example of this: {answer}. "
        "A cadence is named by the chords that end the phrase.",
        "Look at the final two chords only.",
        "",
        _CADENCE_CHOICES,
        voicings[-1],
        _events(voicings),
    )


def _g_ear_cadence(rng: random.Random, d: str) -> _Built:
    key, kind, chords = _cadence_case(rng, d)
    voicings = _close_voicing(chords)
    answer = CADENCE_LABELS[kind]
    return _Built(
        f"Listen to the chord phrase in {_key_text(key)}. Which cadence ends it?",
        "choice",
        "choice",
        {},
        answer,
        answer,
        f"The phrase was {' – '.join(str(c) for c in chords)}; its ending is a {answer}.",
        "Does the phrase sound finished (authentic, plagal), unfinished (half) or surprising "
        "(deceptive)?",
        "",
        _CADENCE_CHOICES,
        (),
        _events(voicings),
    )


_SECONDARY_TARGETS = {
    "major": ["ii", "iii", "IV", "V", "vi"],
    "minor": ["III", "iv", "V", "VI", "VII"],
}


def _g_secondary_dominant(rng: random.Random, d: str) -> _Built:
    lvl = _level(d)
    minor = lvl >= 2 and rng.random() < 0.4
    tonic = rng.choice(_MINOR_KEYS[d] if minor else _MAJOR_KEYS[d])
    key = Key(parse_note_name(tonic), "minor" if minor else "major")
    targets = _SECONDARY_TARGETS[key.mode]
    target = rng.choice(targets[3:4] + targets[4:] if lvl == 0 else targets)
    leading = lvl >= 3 and rng.random() < 0.4
    base = "viio7" if leading else ("V" if lvl == 0 and rng.random() < 0.5 else "V7")
    figure = f"{base}/{target}"
    chord = chord_from_roman(figure, key)
    target_chord = chord_from_roman(target, key)
    return _Built(
        f"In {_key_text(key)}, which chord is {figure}?",
        "text",
        "chord",
        {"chord": chord},
        str(chord),
        str(chord),
        f"{figure} is the {'leading-tone' if leading else 'dominant'} chord of {target} "
        f"({target_chord}) in {_key_text(key)}: {chord}. It borrows a note from outside the key "
        "to point strongly at its target.",
        "First find the target chord, then build the dominant (a fifth above) or leading-tone "
        "(a half step below) chord of that root.",
        "A chord symbol such as A7",
        spelling=True,
    )


def _diatonic_by_numeral(key: Key) -> list[tuple[str, Chord]]:
    numerals = ["I", "II", "III", "IV", "V", "VI", "VII"]
    out = []
    for i, found in enumerate(diatonic_chords(key.scale(), 3)):
        if found.chord is None:
            continue
        text = numerals[i]
        if found.chord.type.id in ("minor", "diminished"):
            text = text.lower()
        out.append((text, found.chord))
    return out


_BORROWED = {"major": ["iv", "bVI", "bVII", "bIII", "iio"], "minor": ["IV", "I", "II"]}
_BORROWED_MINOR_CHECK = {"IV": "IV", "I": "I"}


def _g_modal_interchange(rng: random.Random, d: str) -> _Built:
    lvl = _level(d)
    minor = lvl >= 2 and rng.random() < 0.3
    tonic = rng.choice(_MINOR_KEYS[d] if minor else _MAJOR_KEYS[d])
    key = Key(parse_note_name(tonic), "minor" if minor else "major")
    pool = _BORROWED["minor"][:2] if minor else _BORROWED["major"]
    figure = rng.choice(pool if lvl > 0 else pool[:3])
    borrowed = chord_from_roman(figure, key)
    result = analyze_chord(borrowed, key)
    if result.category != "borrowed":
        raise _Retry
    diatonic = [
        c for _, c in _diatonic_by_numeral(key) if c.type.id in ("major", "minor", "diminished")
    ]
    diatonic = [c for c in diatonic if analyze_chord(c, key).category == "diatonic"]
    distractors = rng.sample([c for c in diatonic if c != borrowed], 3)
    options = [str(borrowed), *(str(c) for c in distractors)]
    if len(set(options)) != 4:
        raise _Retry
    rng.shuffle(options)
    return _Built(
        f"In {_key_text(key)}, one of these chords is borrowed from the parallel "
        f"{key.parallel().mode} key. Which one?",
        "choice",
        "choice",
        {},
        str(borrowed),
        str(borrowed),
        f"{borrowed} is {result.figure} borrowed from {result.borrowed_from}: its notes are not "
        f"all in {_key_text(key)}, but they all belong to the parallel {key.parallel().mode}. "
        "Borrowing chords this way is called modal interchange.",
        "Spell each chord and look for a note that is not in the key.",
        "",
        tuple(options),
    )


def _spell_flat(pc: int) -> NoteName:
    return spell_pitch_class(pc % 12, "flats")


def _g_substitution(rng: random.Random, d: str) -> _Built:
    lvl = _level(d)
    variant = rng.choice(["tritone", "related_ii"])
    type_id = rng.choice(["dominant7"] if lvl < 2 else ["dominant7", "dominant9", "dominant13"])
    root = parse_note_name(rng.choice(_ROOTS[d]))
    dom = make_chord(root, type_id)
    if variant == "tritone":
        sub = Chord(_spell_flat(root.pitch_class + 6), dom.type)
        prompt = f"What is the tritone substitution for {dom}?"
        why = (
            f"The tritone substitute of {dom} is {sub}: its root is a tritone (6 semitones) away, "
            f"and {dom} and {sub} share the same third and seventh (as the seventh and third)."
        )
        hint = "Move the root up or down 6 semitones and keep the chord type."
    else:
        ii_type = "minor9" if type_id == "dominant9" else "minor7"
        sub = Chord(transpose_name(root, parse_interval("P5")), chord_type_by_id(ii_type))
        prompt = f"Which chord is the related ii of {dom}, played before it as a ii–V?"
        why = (
            f"The related ii of {dom} is built a perfect fifth above (or fourth below) its root: "
            f"{sub} – {dom}."
        )
        hint = "In a ii–V the ii chord's root is a fifth above the V chord's root."
    return _Built(
        prompt,
        "text",
        "chord",
        {"chord": sub},
        str(sub),
        str(sub),
        why,
        hint,
        "A chord symbol such as Db7",
        spelling=False,
    )


def chord_type_by_id(type_id: str) -> Any:
    return CHORD_TYPES[type_id]


def _g_voice_leading_choice(rng: random.Random, d: str) -> _Built:
    lvl = _level(d)
    key = Key(parse_note_name(rng.choice(_MAJOR_KEYS[d] if lvl else ["C"])), "major")
    size: Literal[3, 4] = 4 if lvl >= 2 else 3
    chords = [c for c in diatonic_chords(key.scale(), size) if c.chord is not None]
    first, second = rng.sample(chords, 2)
    a, b = first.chord, second.chord
    assert a is not None and b is not None  # noqa: S101 - narrowed above
    start = Voicing((), tuple(a.midi_notes(4, rng.randrange(len(a.tones())))), "", "triad_close")
    centre = sum(start.right) / len(start.right)
    options: list[tuple[int, str, Voicing]] = []
    for inv in range(len(b.tones())):
        notes = b.midi_notes(4, inv)
        shift = round((centre - sum(notes) / len(notes)) / 12) * 12
        moved = tuple(n + shift for n in notes)
        v = Voicing((), moved, "", "triad_close")
        movement = evaluate_transition(start, v).info.movement
        label = f"{inversion_name(inv)}: {' '.join(_midi_name(n) for n in moved)}"
        options.append((movement, label, v))
    best = min(o[0] for o in options)
    if sum(1 for o in options if o[0] == best) != 1:
        raise _Retry
    answer = next(o[1] for o in options if o[0] == best)
    choices = [o[1] for o in options]
    rng.shuffle(choices)
    detail = "; ".join(f"{o[1].split(':')[0]} moves {o[0]} semitones" for o in options)
    return _Built(
        f"You are playing {a} as {' '.join(_midi_name(n) for n in start.right)}. Which voicing of "
        f"{b} comes next with the least movement?",
        "choice",
        "choice",
        {},
        answer,
        answer,
        f"Total movement (sum of each voice's move in semitones): {detail}. Keeping common notes "
        "and moving the other voices by step gives the smoothest result.",
        "Keep any note the two chords share and move the others the shortest way.",
        "",
        tuple(choices),
        start.right,
        (PlayEvent(start.right, 0, 2),),
    )


# ------------------------------------------------------------------ generators: ear training

_EAR_INTERVALS: dict[str, list[str]] = {
    "beginner": ["m3", "M3", "P5", "P8"],
    "intermediate": ["m2", "M2", "m3", "M3", "P4", "P5", "m6", "M6", "m7", "M7", "P8"],
    "advanced": ["m2", "M2", "m3", "M3", "P4", "A4", "P5", "m6", "M6", "m7", "M7", "P8"],
    "expert": ["m2", "M2", "m3", "M3", "P4", "A4", "P5", "m6", "M6", "m7", "M7", "P8"],
}


def _ear_name(iv: Interval) -> str:
    return "tritone" if iv.semitones == 6 else iv.long


def _g_ear_interval(rng: random.Random, d: str) -> _Built:
    lvl = _level(d)
    pool = _EAR_INTERVALS[d]
    iv = parse_interval(rng.choice(pool))
    low = rng.randrange(48, 73)
    high = low + iv.semitones
    if lvl >= 2:
        mode = rng.choice(["up", "down", "together"])
    elif lvl == 1:
        mode = rng.choice(["up", "together"])
    else:
        mode = "up"
    events: tuple[PlayEvent, ...]
    if mode == "together":
        events = (PlayEvent((low, high), 0, 2),)
    elif mode == "up":
        events = (PlayEvent((low,), 0, 1), PlayEvent((high,), 1, 1))
    else:
        events = (PlayEvent((high,), 0, 1), PlayEvent((low,), 1, 1))
    names = sorted({_ear_name(parse_interval(s)) for s in pool})
    picked = {_ear_name(iv)}
    others = [n for n in names if n not in picked]
    count = 3 if lvl == 0 else min(5, len(names) - 1)
    choices = [_ear_name(iv), *rng.sample(others, min(count, len(others)))]
    rng.shuffle(choices)
    answer = _ear_name(iv)
    way = {
        "up": "played one note after the other, going up",
        "down": "played going down",
        "together": "played together",
    }[mode]
    return _Built(
        f"Listen to the interval ({way}). What is it?",
        "choice",
        "choice",
        {},
        answer,
        answer,
        f"The interval was a {answer}: {iv.semitones} semitones apart.",
        "Compare the size of the gap: smaller gaps are seconds and thirds, larger ones sixths "
        "and sevenths.",
        "",
        tuple(choices),
        (),
        events,
    )


_EAR_CHORDS: dict[str, list[str]] = {
    "beginner": ["major", "minor"],
    "intermediate": ["major", "minor", "diminished", "augmented"],
    "advanced": ["major7", "minor7", "dominant7", "half_diminished7", "diminished7"],
    "expert": [
        "major7",
        "minor7",
        "dominant7",
        "half_diminished7",
        "diminished7",
        "minor_major7",
        "major9",
        "minor9",
        "dominant9",
    ],
}


def _g_ear_chord_quality(rng: random.Random, d: str) -> _Built:
    pool = _EAR_CHORDS[d]
    type_id = rng.choice(pool)
    root = rng.choice(["C", "D", "E", "F", "G", "A", "Bb", "Eb"])
    chord = make_chord(root, type_id)
    notes = tuple(chord.midi_notes(3 if _level(d) < 2 else 4))
    events = tuple(PlayEvent((n,), i * 0.5, 0.5) for i, n in enumerate(notes))
    events += (PlayEvent(notes, len(notes) * 0.5 + 0.5, 3),)
    names = [CHORD_TYPES[t].name for t in pool]
    answer = chord.type.name
    return _Built(
        "Listen to the chord (broken, then together). What is its quality?",
        "choice",
        "choice",
        {},
        answer,
        answer,
        f"It was {chord} ({answer.lower()}): the notes are "
        + " ".join(i.short for i in chord.type.formula)
        + " above the root.",
        "Is it bright or dark? Is there a seventh? Is it tense and unresolved?",
        "",
        tuple(names),
        (),
        events,
    )


# ------------------------------------------------------------------ registry

_KIND_TABLE: tuple[tuple[str, str, str, str, tuple[str, ...], bool, _Generator], ...] = (
    (
        "note_name",
        "Note identification",
        "notes",
        "Name notes on the keyboard, including enharmonic names and octave numbers.",
        (),
        False,
        _g_note_name,
    ),
    (
        "interval_identify",
        "Name the interval",
        "intervals",
        "Name the interval between two notes by size and quality.",
        ("note_name",),
        False,
        _g_interval_identify,
    ),
    (
        "interval_build",
        "Build an interval",
        "intervals",
        "Spell the note a given interval above or below another note.",
        ("interval_identify",),
        False,
        _g_interval_build,
    ),
    (
        "scale_construct",
        "Spell a scale",
        "scales",
        "Construct major, minor, modal and other scales with correct spelling.",
        ("interval_build",),
        False,
        _g_scale_construct,
    ),
    (
        "key_signature",
        "Key signatures",
        "key_signatures",
        "Relate keys to their sharps and flats.",
        ("scale_construct",),
        False,
        _g_key_signature,
    ),
    (
        "triad_build",
        "Spell a triad",
        "triads",
        "Spell major, minor, diminished, augmented and suspended triads.",
        ("interval_build",),
        False,
        _g_triad_build,
    ),
    (
        "triad_identify",
        "Identify a triad",
        "triads",
        "Name a triad from the notes on the keyboard, including slash chords.",
        ("triad_build",),
        False,
        _g_triad_identify,
    ),
    (
        "inversion_identify",
        "Chord inversions",
        "inversions",
        "Tell which chord tone is in the bass.",
        ("triad_identify",),
        False,
        _g_inversion_identify,
    ),
    (
        "seventh_build",
        "Spell a seventh chord",
        "seventh_chords",
        "Spell seventh and sixth chords, including half- and fully diminished.",
        ("triad_build",),
        False,
        _g_seventh_build,
    ),
    (
        "seventh_identify",
        "Identify a seventh chord",
        "seventh_chords",
        "Name seventh chords and their inversions from the keyboard.",
        ("seventh_build", "triad_identify"),
        False,
        _g_seventh_identify,
    ),
    (
        "diatonic_chord",
        "Diatonic chords",
        "diatonic_harmony",
        "Build triads and sevenths on each degree of a scale.",
        ("scale_construct", "triad_build"),
        False,
        _g_diatonic_chord,
    ),
    (
        "roman_numeral",
        "Roman numeral analysis",
        "roman_numerals",
        "Label a chord with its Roman numeral in a key.",
        ("diatonic_chord",),
        False,
        _g_roman_numeral,
    ),
    (
        "roman_to_chord",
        "Numerals to chords",
        "roman_numerals",
        "Write the chord a Roman numeral stands for in a key.",
        ("diatonic_chord",),
        False,
        _g_roman_to_chord,
    ),
    (
        "progression_build",
        "Spell a progression",
        "progressions",
        "Write common progressions in any key.",
        ("roman_to_chord",),
        False,
        _g_progression_build,
    ),
    (
        "voice_leading_choice",
        "Smooth voice leading",
        "voice_leading",
        "Choose the inversion that moves the least.",
        ("triad_identify", "diatonic_chord"),
        False,
        _g_voice_leading_choice,
    ),
    (
        "cadence_identify",
        "Identify cadences",
        "cadences",
        "Recognise authentic, plagal, half and deceptive cadences.",
        ("roman_numeral",),
        False,
        _g_cadence_identify,
    ),
    (
        "secondary_dominant",
        "Secondary dominants",
        "secondary_dominants",
        "Build applied dominant and leading-tone chords.",
        ("roman_to_chord",),
        False,
        _g_secondary_dominant,
    ),
    (
        "modal_interchange",
        "Borrowed chords",
        "modal_interchange",
        "Spot chords borrowed from the parallel mode.",
        ("roman_numeral",),
        False,
        _g_modal_interchange,
    ),
    (
        "extension_identify",
        "Extended chords",
        "extensions",
        "Name ninth, eleventh, thirteenth and altered chords.",
        ("seventh_identify",),
        False,
        _g_extension_identify,
    ),
    (
        "substitution",
        "Harmonic substitution",
        "substitutions",
        "Find tritone substitutes and related ii chords for dominant chords.",
        ("seventh_build", "secondary_dominant"),
        False,
        _g_substitution,
    ),
    (
        "ear_interval",
        "Ear training: intervals",
        "ear_training",
        "Recognise intervals by ear.",
        (),
        True,
        _g_ear_interval,
    ),
    (
        "ear_chord_quality",
        "Ear training: chord quality",
        "ear_training",
        "Recognise chord qualities by ear.",
        ("ear_interval",),
        True,
        _g_ear_chord_quality,
    ),
    (
        "ear_cadence",
        "Ear training: cadences",
        "ear_training",
        "Recognise cadences by ear.",
        ("ear_chord_quality", "cadence_identify"),
        True,
        _g_ear_cadence,
    ),
)

_GENERATORS: dict[str, _Generator] = {row[0]: row[6] for row in _KIND_TABLE}
KINDS: dict[str, KindInfo] = {
    row[0]: KindInfo(row[0], row[1], row[2], row[3], row[4], row[5]) for row in _KIND_TABLE
}


def list_kinds() -> list[KindInfo]:
    """The catalogue of exercise kinds, with topics and optional prerequisites."""
    return list(KINDS.values())


# ------------------------------------------------------------------ generation


def exercise_id(kind: str, difficulty: str, seed: int) -> str:
    return f"v{GENERATOR_VERSION}:{kind}:{difficulty}:{seed}"


def parse_exercise_id(text: str) -> tuple[str, str, int]:
    m = _ID_RE.match(text.strip()) if isinstance(text, str) else None
    if not m:
        raise ExerciseError(
            "Exercise ids look like 'v1:interval_identify:beginner:12345'.",
            code="invalid_exercise_id",
        )
    version, kind, difficulty, seed = int(m.group(1)), m.group(2), m.group(3), int(m.group(4))
    if version != GENERATOR_VERSION:
        raise ExerciseError(
            f"This exercise was made by generator version {version}; this server uses "
            f"version {GENERATOR_VERSION}. Ask for a new exercise.",
            code="unsupported_exercise_version",
        )
    _check_kind(kind, difficulty, seed)
    return kind, difficulty, seed


def _check_kind(kind: str, difficulty: str, seed: int) -> None:
    if kind not in KINDS:
        raise ExerciseError(
            f"Unknown exercise kind {kind!r}. Choose from: {', '.join(KINDS)}.",
            code="unknown_exercise_kind",
        )
    if difficulty not in DIFFICULTIES:
        raise ExerciseError(
            f"Difficulty must be one of {', '.join(DIFFICULTIES)}.", code="unknown_difficulty"
        )
    if isinstance(seed, bool) or not isinstance(seed, int) or not 0 <= seed <= _MAX_SEED:
        raise ExerciseError(f"Seed must be an integer from 0 to {_MAX_SEED}.", code="invalid_seed")


def _build(kind: str, difficulty: str, seed: int) -> tuple[Exercise, _Built]:
    _check_kind(kind, difficulty, seed)
    rng = random.Random(f"{GENERATOR_VERSION}:{kind}:{difficulty}:{seed}")
    last: Exception | None = None
    for _ in range(80):
        try:
            built = _GENERATORS[kind](rng, difficulty)
        except _Retry:
            continue
        except TheoryError as exc:  # e.g. a spelling that needs a triple accidental
            last = exc
            continue
        info = KINDS[kind]
        return (
            Exercise(
                exercise_id(kind, difficulty, seed),
                kind,
                difficulty,
                seed,
                info.topic,
                built.prompt,
                built.format,
                built.help,
                built.choices,
                built.show,
                built.play,
                built.tempo,
                built.hint,
            ),
            built,
        )
    raise ExerciseError(
        f"Could not generate a {kind} exercise for seed {seed}" + (f": {last}" if last else "."),
        code="generation_failed",
    )


def generate_exercise(kind: str, difficulty: str = "beginner", seed: int | None = None) -> Exercise:
    """Make an exercise. Give a seed for a reproducible one; without it a seed is drawn."""
    if seed is None:
        seed = random.SystemRandom().randrange(_MAX_SEED + 1)
    return _build(kind, difficulty, seed)[0]


def generate_set(
    kind: str, difficulty: str = "beginner", count: int = 5, seed: int = 0
) -> list[Exercise]:
    """`count` different exercises with consecutive seeds, for a practice session."""
    if not 1 <= count <= 50:
        raise ExerciseError("count must be between 1 and 50", code="invalid_count")
    return [generate_exercise(kind, difficulty, seed + i) for i in range(count)]


def reference_answer(exercise: str | Exercise) -> Any:
    """An answer that grades as correct. For tests and administrators; the learner-facing
    API only reveals the answer after grading."""
    ident = exercise if isinstance(exercise, str) else exercise.id
    kind, difficulty, seed = parse_exercise_id(ident)
    return _build(kind, difficulty, seed)[1].reference


# ------------------------------------------------------------------ answer checking

Answer = str | list[str] | list[int]


def _clean_text(text: str) -> str:
    return text.strip().replace("♯", "#").replace("♭", "b").replace("−", "-")


def _expect_text(answer: Any) -> str:
    if not isinstance(answer, str):
        raise ExerciseError("This exercise takes a single text answer.", code="invalid_answer")
    if len(answer) > MAX_ANSWER_LENGTH:
        raise ExerciseError("The answer is too long.", code="invalid_answer")
    return answer


def _expect_list(answer: Any, *, allow_ints: bool = False) -> list[Any]:
    if not isinstance(answer, list) or isinstance(answer, str):
        raise ExerciseError("This exercise takes a list as its answer.", code="invalid_answer")
    if not 1 <= len(answer) <= MAX_ANSWER_ITEMS:
        raise ExerciseError(f"Give between 1 and {MAX_ANSWER_ITEMS} items.", code="invalid_answer")
    for item in answer:
        if isinstance(item, bool):
            raise ExerciseError("Answer items must be text or MIDI numbers.", code="invalid_answer")
        if isinstance(item, int) and allow_ints:
            if not 0 <= item <= 127:
                raise ExerciseError("MIDI notes are 0 to 127.", code="invalid_answer")
        elif not isinstance(item, str) or len(item) > MAX_ANSWER_LENGTH:
            raise ExerciseError("Answer items must be short text.", code="invalid_answer")
    return answer


_Result = tuple[Status, str, tuple[ItemResult, ...]]


def _note_name_from_text(text: str) -> NoteName:
    stripped = re.sub(r"-?\d+$", "", _clean_text(text))
    return parse_note_name(stripped)


def _check_choice(b: _Built, answer: Any) -> _Result:
    text = _expect_text(answer)
    if text not in b.choices:
        raise ExerciseError("Choose one of the listed options.", code="invalid_answer")
    if text == b.reference:
        return "correct", "Correct.", ()
    return "incorrect", f"Not quite. The answer is {b.correct_display}.", ()


def _check_note(b: _Built, answer: Any) -> _Result:
    text = _clean_text(_expect_text(answer))
    if "/" in text:  # the form shown for a black key, "D# / Eb": every name given must fit
        results = [_check_note(b, part.strip()) for part in text.split("/") if part.strip()]
        for status in ("unreadable", "incorrect"):
            for r in results:
                if r[0] == status:
                    return r
        return results[0] if results else ("unreadable", "Give a note name.", ())
    need_octave = b.data["octave"]
    try:
        note = parse_note(text)
        if need_octave and not re.search(r"-?\d+$", text):
            raise TheoryError("octave missing")
    except TheoryError:
        try:
            name = _note_name_from_text(text)
        except TheoryError:
            return "unreadable", f"Could not read {answer!r} as a note name (try C#4 or Eb).", ()
        if need_octave:
            return "unreadable", "Include the octave number, for example C#4.", ()
        same = name.pitch_class == b.data["midi"] % 12
        return (
            ("correct", f"Correct: this key is {b.correct_display}.", ())
            if same
            else ("incorrect", f"That is {name}; the highlighted key is {b.correct_display}.", ())
        )
    if need_octave:
        if note.midi == b.data["midi"]:
            return "correct", f"Correct: {b.correct_display}.", ()
        if note.pitch_class == b.data["midi"] % 12:
            return "incorrect", f"Right note name, wrong octave. It is {b.correct_display}.", ()
        return "incorrect", f"That is {note.format()}; the key is {b.correct_display}.", ()
    if note.pitch_class == b.data["midi"] % 12:
        return "correct", f"Correct: this key is {b.correct_display}.", ()
    return "incorrect", f"That is {note.name}; the highlighted key is {b.correct_display}.", ()


def _check_interval(b: _Built, answer: Any) -> _Result:
    text = _expect_text(answer)
    try:
        given = parse_interval_answer(text)
    except TheoryError as exc:
        return "unreadable", exc.message, ()
    want: Interval = b.data["interval"]
    if given == want:
        return "correct", f"Correct: {want.short} ({want.long}).", ()
    if given.semitones == want.semitones:
        return (
            "enharmonic",
            f"{given.short} sounds the same size ({want.semitones} semitones), but these notes "
            f"are {want.number} letters apart, so the interval is written {want.short}.",
            (),
        )
    if given.simple_number == want.simple_number and given.number != want.number:
        return "incorrect", f"Right interval class, but this one is {want.short} ({want.long}).", ()
    return (
        "incorrect",
        f"{given.short} spans {given.semitones} semitones, but these notes are {want.semitones} "
        f"semitones and {want.number} letters apart: {want.short} ({want.long}).",
        (),
    )


_MODE_WORD_RE = re.compile(r"^(?P<note>\S+)\s+(?P<mode>major|minor|maj|min)$", re.IGNORECASE)


def _check_note_spelled(b: _Built, answer: Any) -> _Result:
    text = _clean_text(_expect_text(answer))
    asked_mode = b.data.get("mode")  # set by "which key" questions only
    word = _MODE_WORD_RE.match(text) if asked_mode else None
    if word:
        said = "major" if word["mode"].lower().startswith("maj") else "minor"
        if said != asked_mode:
            return (
                "incorrect",
                f"That names a {said} key, but the question asks for a {asked_mode} key. "
                f"The answer is {b.data['name']}.",
                (),
            )
        text = word["note"]
    try:
        given = parse_note_name(text)
    except TheoryError:
        return "unreadable", f"Could not read {answer!r} as a note name (try Bb or F#).", ()
    want: NoteName = b.data["name"]
    if given == want:
        return "correct", f"Correct: {want}.", ()
    if given.pitch_class == want.pitch_class:
        return (
            "enharmonic",
            f"{given} sounds the same as {want}, but the letter name is fixed by the interval or "
            f"key, so the correct spelling is {want}.",
            (),
        )
    return "incorrect", f"Not quite. The answer is {want}.", ()


def _check_note_list(b: _Built, answer: Any) -> _Result:
    given = _expect_list(answer)
    want: tuple[NoteName, ...] = b.data["names"]
    items: list[ItemResult] = []
    parsed: list[NoteName | None] = []
    for text in given:
        try:
            parsed.append(_note_name_from_text(text))
        except TheoryError:
            parsed.append(None)
    if any(p is None for p in parsed):
        bad = next(g for g, p in zip(given, parsed, strict=True) if p is None)
        return "unreadable", f"Could not read {bad!r} as a note name.", ()
    for i, w in enumerate(want):
        g = parsed[i] if i < len(parsed) else None
        items.append(ItemResult(i, "" if g is None else str(g), g == w, str(w)))
    if len(given) != len(want):
        return (
            "incorrect",
            f"This answer needs {len(want)} notes; you gave {len(given)}.",
            tuple(items),
        )
    if all(it.correct for it in items):
        return "correct", "Correct.", tuple(items)
    wrong = [it for it in items if not it.correct]
    only_spelling = all(
        p is not None and p.pitch_class == w.pitch_class for p, w in zip(parsed, want, strict=True)
    )
    if only_spelling:
        return (
            "enharmonic",
            "Every note sounds right but "
            + str(len(wrong))
            + " "
            + ("is" if len(wrong) == 1 else "are")
            + f" spelled differently. Check degree {wrong[0].index + 1}: use {wrong[0].expected}.",
            tuple(items),
        )
    first = wrong[0]
    return (
        "incorrect",
        f"Degree {first.index + 1} should be {first.expected}, not {first.given}.",
        tuple(items),
    )


def _check_note_set(b: _Built, answer: Any) -> _Result:
    given = _expect_list(answer, allow_ints=True)
    want: tuple[NoteName, ...] = b.data["names"]
    want_pcs = {n.pitch_class for n in want}
    if all(isinstance(g, int) for g in given):
        got = {g % 12 for g in given}
        if got == want_pcs:
            return "correct", "Correct.", ()
        missing = sorted(want_pcs - got)
        extra = sorted(got - want_pcs)
        return (
            "incorrect",
            _set_feedback(
                [spell_pitch_class(p) for p in missing], [spell_pitch_class(p) for p in extra]
            ),
            (),
        )
    if any(isinstance(g, int) for g in given):
        raise ExerciseError("Give note names or MIDI numbers, not both.", code="invalid_answer")
    try:
        names = [_note_name_from_text(g) for g in given]
    except TheoryError:
        return "unreadable", "Could not read one of the notes. Use names like F# or Bb.", ()
    if set(names) == set(want):
        return "correct", "Correct.", ()
    got_pcs = {n.pitch_class for n in names}
    if got_pcs == want_pcs:
        wrong = sorted(str(n) for n in set(names) - set(want))
        right = sorted(str(n) for n in set(want) - set(names))
        return (
            "enharmonic",
            f"These notes sound right, but the spelling is off: write {', '.join(right)} instead "
            f"of {', '.join(wrong)}.",
            (),
        )
    missing_names = [n for n in want if n.pitch_class not in got_pcs]
    extra_names = [n for n in names if n.pitch_class not in want_pcs]
    return "incorrect", _set_feedback(missing_names, extra_names), ()


def _set_feedback(missing: Sequence[NoteName], extra: Sequence[NoteName]) -> str:
    parts = []
    if missing:
        parts.append("missing " + ", ".join(str(n) for n in missing))
    if extra:
        parts.append("not in the chord: " + ", ".join(str(n) for n in extra))
    return "Not quite — " + "; ".join(parts) + "."


def _chord_relation(want: Chord, given: Chord) -> str:
    same_pcs = set(want.pitch_classes()) == set(given.pitch_classes())
    if (
        given.root == want.root
        and given.type.id == want.type.id
        and given.bass_name == want.bass_name
    ):
        return "exact"
    if (
        given.root.pitch_class == want.root.pitch_class
        and given.type.id == want.type.id
        and given.bass_name.pitch_class == want.bass_name.pitch_class
    ):
        return "enharmonic"
    if same_pcs and given.bass_name.pitch_class == want.bass_name.pitch_class:
        return "same_notes"
    if given.root.pitch_class == want.root.pitch_class and given.type.id == want.type.id:
        return "bass"
    return "different"


def _chord_feedback(want: Chord, given: Chord, relation: str, spelling: bool) -> _Result:
    if relation == "exact":
        return "correct", f"Correct: {want}.", ()
    if relation == "enharmonic":
        return (
            "enharmonic",
            f"{given} has the same sound as {want}, but in this key or context the spelling is "
            f"{want}."
            if spelling
            else f"Correct: {want} (also written {given}).",
            (),
        )
    if relation == "same_notes":
        return (
            "correct",
            f"{given} holds the same notes with the same bass note, so it is a valid reading. "
            f"The expected reading is {want}.",
            (),
        )
    if relation == "bass":
        return (
            "partial",
            f"Right chord ({want.root} {want.type.name.lower()}), but the lowest note is "
            f"{want.bass_name}, so write it as {want}.",
            (),
        )
    have = {n.pitch_class for n in given.tones()}
    need = {n.pitch_class for n in want.tones()}
    detail = ""
    if given.root.pitch_class == want.root.pitch_class:
        detail = f" The root is right but {given} has the wrong quality."
    elif have & need:
        detail = (
            f" {given} contains {_names(given.tones())}; "
            f"the chord needed has {_names(want.tones())}."
        )
    return "incorrect", f"Not quite. The answer is {want}.{detail}", ()


def _check_chord(b: _Built, answer: Any) -> _Result:
    text = _expect_text(answer)
    try:
        given = parse_chord(text)
    except ChordSymbolError as exc:
        return "unreadable", f"Could not read {answer!r}: {exc.message}", ()
    want: Chord = b.data["chord"]
    return _chord_feedback(want, given, _chord_relation(want, given), b.spelling)


def _check_chord_list(b: _Built, answer: Any) -> _Result:
    given = _expect_list(answer)
    want: list[Chord] = b.data["chords"]
    if len(given) != len(want):
        return "incorrect", f"This progression has {len(want)} chords; you gave {len(given)}.", ()
    items: list[ItemResult] = []
    statuses: list[str] = []
    for i, (w, text) in enumerate(zip(want, given, strict=True)):
        try:
            g = parse_chord(text)
        except ChordSymbolError as exc:
            return "unreadable", f"Chord {i + 1}: could not read {text!r}: {exc.message}", ()
        rel = _chord_relation(w, g)
        st = "correct" if rel in ("exact", "same_notes") else rel
        statuses.append(st)
        items.append(ItemResult(i, str(g), st == "correct", str(w)))
    if all(s == "correct" for s in statuses):
        return "correct", "Correct.", tuple(items)
    first = next(i for i, s in enumerate(statuses) if s != "correct")
    if all(s in ("correct", "enharmonic") for s in statuses):
        return (
            "enharmonic",
            f"Chord {first + 1} sounds right but is spelled differently: use {want[first]}.",
            tuple(items),
        )
    return "incorrect", f"Chord {first + 1} should be {want[first]}.", tuple(items)


def _check_numeral(b: _Built, answer: Any) -> _Result:
    text = _clean_text(_expect_text(answer))
    want_figure: str = b.data["figure"]
    if text == want_figure:
        return "correct", f"Correct: {want_figure}.", ()
    key: Key = b.data["key"]
    try:
        chord = chord_from_roman(text, key)
    except TheoryError as exc:
        return "unreadable", f"Could not read {answer!r} as a Roman numeral: {exc.message}", ()
    if _numeral_equal(chord, b.data["chord"]):
        return "correct", f"Correct. The usual way to write it is {want_figure}.", ()
    return (
        "incorrect",
        f"{text} would be {chord} in {_key_text(key)}. The chord given is {b.data['chord']}, "
        f"which is {want_figure}.",
        (),
    )


def _check_keysig(b: _Built, answer: Any) -> _Result:
    text = _expect_text(answer)
    try:
        fifths = _parse_keysig(text)
    except TheoryError as exc:
        return "unreadable", exc.message, ()
    if fifths == b.data["fifths"]:
        return "correct", f"Correct: {_describe_fifths(fifths)}.", ()
    return "incorrect", f"Not quite. The key signature has {b.correct_display}.", ()


_CHECKERS: dict[str, Callable[[_Built, Any], _Result]] = {
    "choice": _check_choice,
    "note": _check_note,
    "interval": _check_interval,
    "note_spelled": _check_note_spelled,
    "note_list": _check_note_list,
    "note_set": _check_note_set,
    "chord": _check_chord,
    "chord_list": _check_chord_list,
    "numeral": _check_numeral,
    "keysig": _check_keysig,
}


def validate_answer(exercise_id_text: str, answer: Any) -> Grade:
    """Grade an answer to an exercise identified by its id.

    Raises `ExerciseError` for a malformed id or an answer of the wrong shape (a list where text
    was expected). An answer of the right shape that cannot be understood musically (``Hx7``) is
    graded ``unreadable`` with an explanation, so the interface can ask again.
    """
    kind, difficulty, seed = parse_exercise_id(exercise_id_text)
    exercise, built = _build(kind, difficulty, seed)
    status, feedback, items = _CHECKERS[built.check](built, answer)
    correct = status == "correct" or (status == "enharmonic" and not built.spelling)
    return Grade(
        exercise.id, status, correct, feedback, built.correct_display, built.explanation, items
    )
