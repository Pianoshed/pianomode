"""Schemas for writing lessons in the admin screen.

A lesson is *authored data*: text plus example specifications (a chord symbol, a scale, two notes,
a chord list). No notes are written by hand; the engine builds them, so a lesson cannot disagree
with the engine that marks its exercises. Example fields beyond `type` and `caption` depend on the
type and are validated by the engine, which names exactly what is wrong.
"""

from typing import Annotated, Any, Literal

from pydantic import ConfigDict, Field, model_validator

from app.schemas.lesson import LessonDetailOut
from app.schemas.theory import Req, Resp

Level = Literal["beginner", "intermediate", "advanced", "expert"]
LessonStatus = Literal["draft", "under_review", "approved", "published", "archived"]
LessonKey = Annotated[str, Field(min_length=2, max_length=64, pattern=r"^[a-z0-9][a-z0-9-]*$")]
Text = Annotated[str, Field(min_length=1, max_length=2000)]
_SCALAR = (str, int, float, bool)


class ExampleIn(Req):
    """`type` and `caption` plus the fields that type needs, for example `symbol`/`octave` for a
    chord, `root`/`scale` for a scale, `lower`/`upper` for an interval, `chords`/`key` for a
    sequence."""

    model_config = ConfigDict(extra="allow")
    type: Literal["chord", "scale", "interval", "sequence"]
    caption: Annotated[str, Field(min_length=1, max_length=200)]

    @model_validator(mode="after")
    def _bounded_extras(self) -> "ExampleIn":
        extra = self.model_extra or {}
        if len(extra) > 8:
            raise ValueError("An example takes at most 8 fields besides type and caption.")
        for key, value in extra.items():
            ok = isinstance(value, _SCALAR) or (
                isinstance(value, list)
                and len(value) <= 12
                and all(isinstance(v, _SCALAR) for v in value)
            )
            if not ok or len(key) > 24 or (isinstance(value, str) and len(value) > 80):
                raise ValueError(f"Example field {key!r} must be short text, a number or a list.")
        return self


class SectionIn(Req):
    heading: Annotated[str, Field(min_length=1, max_length=120)]
    body: Annotated[list[Text], Field(min_length=1, max_length=8)]
    examples: Annotated[list[ExampleIn], Field(max_length=6)] = []


class PracticeIn(Req):
    kind: Annotated[str, Field(min_length=1, max_length=40, pattern=r"^[a-z][a-z0-9_]*$")]
    difficulty: Level
    goal: Annotated[int, Field(strict=True, ge=1, le=20)] = 3


class LessonDefinitionIn(Req):
    id: LessonKey
    title: Annotated[str, Field(min_length=1, max_length=120)]
    level: Level
    summary: Annotated[str, Field(min_length=1, max_length=300)]
    objectives: Annotated[
        list[Annotated[str, Field(min_length=1, max_length=300)]], Field(min_length=1, max_length=6)
    ]
    prerequisites: Annotated[list[LessonKey], Field(max_length=6)] = []
    sections: Annotated[list[SectionIn], Field(min_length=1, max_length=12)]
    practice: Annotated[list[PracticeIn], Field(min_length=1, max_length=6)]
    movement_template: Annotated[str, Field(max_length=48, pattern=r"^[a-z][a-z0-9_]*$")] | None = (
        None
    )
    tags: Annotated[
        list[Annotated[str, Field(min_length=1, max_length=32)]], Field(max_length=8)
    ] = []


class LessonUpdateIn(LessonDefinitionIn):
    revision: Annotated[int, Field(ge=1)]


class LessonStatusIn(Req):
    to: LessonStatus
    note: Annotated[str, Field(max_length=500)] = ""


class LessonHistoryOut(Resp):
    revision: int
    at: str
    actor: str
    action: str
    note: str
    from_status: str | None
    to_status: str | None


class AdminLessonOut(Resp):
    id: str
    lesson_id: str
    title: str
    level: str
    status: LessonStatus
    revision: int
    definition: dict[str, Any]
    history: list[LessonHistoryOut]
    allowed_transitions: list[str]
    published_at: str | None
    updated_at: str


class AdminLessonSummaryOut(Resp):
    id: str
    lesson_id: str
    title: str
    level: str
    status: LessonStatus
    revision: int
    updated_at: str


class AdminLessonListOut(Resp):
    items: list[AdminLessonSummaryOut]
    total: int


class LessonPreviewOut(Resp):
    lesson: LessonDetailOut  # exactly what a learner would see, with no practice progress
    publishable: bool
    blockers: list[str]
    warnings: list[str]
    can_publish_now: bool
