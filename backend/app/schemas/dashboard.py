import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel


class ContinueOut(BaseModel):
    id: str
    title: str
    goals_met: int
    goals_total: int
    progress_percent: int


class RecommendedOut(BaseModel):
    id: str
    title: str
    summary: str
    reason: str


class ProjectOut(BaseModel):
    id: uuid.UUID
    kind: Literal["midi", "audio"]
    title: str
    opened_at: datetime


class SavedProgressionOut(BaseModel):
    id: uuid.UUID
    title: str
    data: dict[str, Any]


class DayOut(BaseModel):
    date: str
    count: int


class DashboardOut(BaseModel):
    continue_learning: list[ContinueOut]
    recommended: RecommendedOut | None
    recent_projects: list[ProjectOut]
    saved_progressions: list[SavedProgressionOut]
    activity: list[DayOut]
    activity_total: int
