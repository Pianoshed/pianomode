"""Schemas for the lessons API."""

from typing import Literal

from app.schemas.theory import Resp

Status = Literal["not_started", "in_progress", "practised"]


class ExampleItemOut(Resp):
    label: str
    notes: list[str]
    midi: list[int]
    detail: str | None


class PlayStepOut(Resp):
    notes: list[int]
    start: float
    duration: float
    item: int


class ExampleOut(Resp):
    type: Literal["chord", "scale", "interval", "sequence"]
    caption: str
    items: list[ExampleItemOut]
    play: list[PlayStepOut]
    tempo: int


class SectionOut(Resp):
    heading: str
    body: list[str]
    examples: list[ExampleOut]


class GoalOut(Resp):
    kind: str
    title: str
    difficulty: str
    goal: int
    correct: int  # distinct exercises answered correctly
    attempted: bool
    met: bool
    ear_training: bool


class LessonLinkOut(Resp):
    id: str
    title: str
    status: Status


class LessonSummaryOut(Resp):
    id: str
    title: str
    level: str
    summary: str
    tags: list[str]
    prerequisites: list[str]
    unmet_prerequisites: list[str]
    status: Status
    goals_met: int
    goals_total: int


class LessonListOut(Resp):
    items: list[LessonSummaryOut]
    note: str = (
        "Status counts practice answers only: 'practised' means every practice goal was met with "
        "distinct exercises answered correctly. It is not a measure of understanding."
    )


class LessonDetailOut(Resp):
    id: str
    title: str
    level: str
    summary: str
    revision: int
    tags: list[str]
    objectives: list[str]
    sections: list[SectionOut]
    practice: list[GoalOut]
    status: Status
    prerequisites: list[LessonLinkOut]
    next: list[LessonLinkOut]
    movement_slug: str | None
