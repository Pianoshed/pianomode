"""Schemas for the chord-movement library (learner and content-admin APIs)."""

from typing import Annotated, Any, Literal

from pydantic import Field

from app.schemas.theory import KeyIn, Req, Resp, Symbol

Level = Literal["beginner", "intermediate", "advanced", "expert"]
Status = Literal["draft", "under_review", "approved", "published", "archived"]
Tag = Annotated[str, Field(min_length=1, max_length=32)]
TemplateId = Annotated[str, Field(min_length=1, max_length=48, pattern=r"^[a-z][a-z0-9_]*$")]


class CustomChordIn(Req):
    symbol: Symbol
    beats: Annotated[float, Field(gt=0, le=32)] = 4.0


class MovementDefinitionIn(Req):
    name: Annotated[str, Field(min_length=1, max_length=120)]
    key: KeyIn
    template_id: TemplateId | None = None
    custom_chords: Annotated[list[CustomChordIn], Field(max_length=16)] = []
    tempo: Annotated[int, Field(strict=True, ge=20, le=300)] = 80
    time_signature: Annotated[list[int], Field(min_length=2, max_length=2)] = [4, 4]
    tags: Annotated[list[Tag], Field(max_length=12)] = []
    theory_explanation: Annotated[str, Field(max_length=4000)] = ""
    practice: dict[Level, Annotated[str, Field(max_length=4000)]] = {}
    variations: Annotated[list[Annotated[str, Field(max_length=300)]], Field(max_length=12)] = []
    levels: Annotated[list[Level], Field(min_length=1, max_length=4)] = [
        "beginner", "intermediate", "advanced", "expert",
    ]  # fmt: skip
    author: Annotated[str, Field(max_length=100)] | None = None
    source: Annotated[str, Field(max_length=200)] | None = None


class MovementUpdateIn(MovementDefinitionIn):
    revision: Annotated[int, Field(ge=1)]  # the revision the editor started from


class StatusChangeIn(Req):
    to: Status
    note: Annotated[str, Field(max_length=500)] = ""


# ------------------------------------------------------------------ built output


class StepOut(Resp):
    index: int
    symbol: str
    roman: str | None
    beat: float
    duration: float
    role: str
    chord_tones: list[str]
    bass: str
    inversion: str
    left: list[int]
    right: list[int]
    left_names: list[str]
    right_names: list[str]
    voicing_type: str
    omitted: list[str]
    tensions: list[str]
    explanation: list[str]
    cost: float


class PlaybackEventOut(Resp):
    midi: int
    hand: Literal["L", "R"]
    start_beat: float
    duration_beats: float
    chord_index: int
    velocity: int


class VersionOut(Resp):
    level: Level
    voicing_type: str
    theory_explanation: str
    practice: str
    variations: list[str]
    total_cost: float
    method: str
    warnings: list[str]
    validation_errors: list[str]
    validation_warnings: list[str]
    tempo: int | None
    time_signature: list[int]
    total_beats: float
    steps: list[StepOut]
    playback: list[PlaybackEventOut]


class BuiltOut(Resp):
    schema_version: int
    generator_version: int
    slug: str
    name: str
    key: dict[str, str]
    tempo: int
    time_signature: list[int]
    tags: list[str]
    author: str | None
    source: str | None
    template_id: str | None
    transposition_options: list[str]
    versions: list[VersionOut]


class MovementDetailOut(Resp):
    movement: BuiltOut
    live: bool  # True: built now (for another key); False: the frozen published snapshot
    score_meaning: str = (
        "Cost is a ranking of how smooth and easy a voicing is (lower is smoother); it is not a "
        "measure of musical quality."
    )


class MovementSummaryOut(Resp):
    slug: str
    name: str
    key: str
    mode: str
    tags: list[str]
    levels: list[Level]
    chords: list[str]  # the intermediate (or first available) version's symbols
    romans: list[str | None]
    tempo: int
    time_signature: list[int]
    author: str | None
    published_at: str | None


class MovementListOut(Resp):
    items: list[MovementSummaryOut]
    total: int


# ------------------------------------------------------------------ admin


class HistoryOut(Resp):
    revision: int
    at: str
    by: str
    action: str
    note: str
    from_status: str | None
    to_status: str | None


class AdminMovementOut(Resp):
    id: str
    slug: str
    name: str
    status: Status
    revision: int
    mode: str
    definition: dict[str, Any]
    history: list[HistoryOut]
    allowed_transitions: list[Status]
    published_at: str | None
    updated_at: str


class AdminMovementSummaryOut(Resp):
    id: str
    slug: str
    name: str
    status: Status
    revision: int
    mode: str
    tags: list[str]
    updated_at: str


class AdminListOut(Resp):
    items: list[AdminMovementSummaryOut]
    total: int


class ValidationOut(Resp):
    publishable: bool
    blockers: list[str]
    warnings: list[str]
    can_publish_now: bool  # publishable AND currently approved


class PreviewOut(Resp):
    movement: BuiltOut
    validation: ValidationOut
