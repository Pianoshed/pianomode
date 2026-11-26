"""Schemas for scoring a practice performance."""

import uuid
from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from app.schemas.theory import Req, Resp

Level = Literal["beginner", "intermediate", "advanced", "expert"]
Midi = Annotated[int, Field(ge=0, le=127, strict=True)]
MAX_NOTES = 5000


class ExpectedNoteIn(Req):
    midi: Midi
    start_beat: Annotated[float, Field(ge=0, le=4096)]
    duration_beats: Annotated[float, Field(gt=0, le=64)] = 1.0
    hand: Literal["L", "R"] | None = None
    chord_index: Annotated[int, Field(ge=0, le=4096)] | None = None


class PlayedNoteIn(Req):
    midi: Midi
    time_s: Annotated[float, Field(ge=0, le=7200)]
    off_time_s: Annotated[float, Field(ge=0, le=7200)] | None = None


class MovementSourceIn(Req):
    slug: Annotated[str, Field(min_length=1, max_length=80)]
    level: Level
    key: Annotated[str, Field(max_length=4)] | None = None
    hands: Literal["both", "L", "R"] = "both"


class SaveIn(Req):
    """Keep this result in the learner's history. Only possible when scoring a movement."""

    session_id: uuid.UUID
    pass_index: Annotated[int, Field(ge=0, le=500)] = 0


class ScoreRequest(Req):
    """Score `played` against either explicit `expected` notes or a published movement."""

    expected: Annotated[list[ExpectedNoteIn], Field(min_length=1, max_length=MAX_NOTES)] | None = (
        None
    )
    movement: MovementSourceIn | None = None
    played: Annotated[list[PlayedNoteIn], Field(max_length=MAX_NOTES)]
    tempo_bpm: Annotated[float, Field(ge=20, le=400)] | None = None  # defaults to the movement's
    level: Level | None = None  # sets the timing window; default intermediate
    window_ms: Annotated[float, Field(ge=20, le=1000)] | None = None  # overrides `level`
    offset_s: Annotated[float, Field(ge=0, le=7200)] = 0.0  # time of beat 0 in the recording
    latency_ms: Annotated[float, Field(ge=0, le=500)] = 0.0
    octave_equivalent: bool = False
    beat_range: (
        Annotated[list[Annotated[float, Field(ge=0, le=4096)]], Field(min_length=2, max_length=2)]
        | None
    ) = None
    save: SaveIn | None = None

    @model_validator(mode="after")
    def _one_source(self) -> Self:
        if (self.expected is None) == (self.movement is None):
            raise ValueError(
                "Give either `expected` notes or a `movement`, not both and not neither."
            )
        if self.expected is not None and self.tempo_bpm is None:
            raise ValueError("`tempo_bpm` is required with explicit expected notes.")
        if self.save is not None and self.movement is None:
            raise ValueError("Results can only be saved when scoring a movement.")
        if self.level is not None and self.window_ms is not None:
            raise ValueError("Give `level` or `window_ms`, not both.")
        return self


class NoteResultOut(Resp):
    index: int
    midi: int
    name: str
    start_beat: float
    hand: str | None
    chord_index: int | None
    status: Literal["on_time", "early", "late", "missed", "near_miss"]
    error_ms: float | None
    played_midi: int | None
    held_ratio: float | None


class ExtraNoteOut(Resp):
    midi: int
    name: str
    time_s: float
    beat: float


class ChordResultOut(Resp):
    chord_index: int
    expected: int
    hit: int
    complete: bool
    spread_ms: float | None


class HandResultOut(Resp):
    hand: Literal["L", "R"]
    expected: int
    hit: int
    accuracy: float


class TimingOut(Resp):
    hits: int
    mean_error_ms: float | None
    mean_abs_error_ms: float | None
    median_error_ms: float | None
    spread_ms: float | None
    tendency: Literal["rushing", "dragging", "steady", "not_enough_notes"]


class ScoreResponse(Resp):
    expected: int
    hits: int
    on_time: int
    early: int
    late: int
    missed: int
    near_miss: int
    extra: int
    short_holds: int
    accuracy: float
    timing: TimingOut
    notes: list[NoteResultOut]
    extras: list[ExtraNoteOut]
    chords: list[ChordResultOut]
    hands: list[HandResultOut]
    feedback: list[str]
    window_ms: float
    tempo_bpm: float
    limits: list[str]
    source: Literal["explicit", "movement"]
    saved_id: str | None = None


class WaitResultIn(Req):
    movement_slug: Annotated[str, Field(min_length=1, max_length=80)]
    level: Level
    key: Annotated[str, Field(max_length=4)] | None = None
    hands: Literal["both", "L", "R"] = "both"
    session_id: uuid.UUID
    steps: Annotated[int, Field(ge=1, le=500)]
    first_try: Annotated[int, Field(ge=0, le=500)]  # chords played right with no wrong note first
    wrong_presses: Annotated[int, Field(ge=0, le=100000)]

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if self.first_try > self.steps:
            raise ValueError("`first_try` cannot be more than `steps`.")
        return self


class AttemptOut(Resp):
    id: str
    session_id: str
    created_at: str
    movement_slug: str
    level: str
    key: str | None
    mode: Literal["play", "wait"]
    hands: str
    pass_index: int
    tempo_bpm: float | None
    window_ms: float | None
    expected: int
    hits: int
    accuracy: float
    on_time: int
    early: int
    late: int
    missed: int
    near_miss: int
    extra: int
    mean_error_ms: float | None
    tendency: str | None


class ProgressOut(Resp):
    movement_slug: str
    level: str
    mode: Literal["play", "wait"]
    attempts: int
    best_accuracy: float
    last_accuracy: float
    best_tempo_at_90: float | None  # fastest tempo with 90%+ accuracy on 8+ notes (play mode)
    last_practised: str


class HistoryOut(Resp):
    items: list[AttemptOut]
    progress: list[ProgressOut]
    total: int
