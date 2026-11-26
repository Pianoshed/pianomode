"""Schemas for administrator-defined scales."""

from typing import Annotated, Literal

from pydantic import Field

from app.schemas.theory import Req, Resp

ScaleStatus = Literal["draft", "published", "archived"]
IntervalText = Annotated[str, Field(min_length=2, max_length=4, pattern=r"^[PMmAd]{1,2}\d{1,2}$")]
ScaleKey = Annotated[str, Field(min_length=2, max_length=40, pattern=r"^[a-z][a-z0-9_]*$")]
# Aliases are looked up through the same identifier-only field as ids, so they use the same form.
AliasKey = Annotated[str, Field(min_length=2, max_length=40, pattern=r"^[a-z][a-z0-9_]*$")]


class ScaleDefinitionIn(Req):
    id: ScaleKey
    name: Annotated[str, Field(min_length=1, max_length=60)]
    family: Annotated[str, Field(min_length=1, max_length=32)] = "custom"
    formula: Annotated[list[IntervalText], Field(min_length=3, max_length=12)]
    descending: Annotated[list[IntervalText], Field(min_length=3, max_length=12)] | None = None
    aliases: Annotated[list[AliasKey], Field(max_length=8)] = []
    description: Annotated[str, Field(max_length=1000)] = ""


class ScaleUpdateIn(ScaleDefinitionIn):
    revision: Annotated[int, Field(ge=1)]


class ScaleStatusIn(Req):
    to: ScaleStatus
    note: Annotated[str, Field(max_length=500)] = ""


class ScaleHistoryOut(Resp):
    revision: int
    at: str
    actor: str
    action: str
    note: str
    from_status: str | None
    to_status: str | None


class AdminScaleOut(Resp):
    id: str
    scale_id: str
    name: str
    status: ScaleStatus
    revision: int
    definition: dict[str, object]
    history: list[ScaleHistoryOut]
    allowed_transitions: list[str]
    published_at: str | None
    updated_at: str


class AdminScaleSummaryOut(Resp):
    id: str
    scale_id: str
    name: str
    status: ScaleStatus
    revision: int
    size: int
    updated_at: str


class AdminScaleListOut(Resp):
    items: list[AdminScaleSummaryOut]
    total: int


class RootSpellingOut(Resp):
    root: str
    notes: list[str] | None  # None when this root cannot be spelled
    problem: str | None


class ScalePreviewOut(Resp):
    scale_id: str
    name: str
    size: int
    semitones: list[int]
    roots: list[RootSpellingOut]
    same_pattern_as: list[str]  # ids of scales with the identical pitch pattern
    blockers: list[str]  # would stop publication
    warnings: list[str]
