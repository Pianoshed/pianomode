import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, StringConstraints

Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
Kind = Literal["midi", "audio", "progression"]


class ItemOut(BaseModel):
    id: uuid.UUID
    kind: Kind
    title: str
    file_name: str | None
    file_size: int
    created_at: datetime
    updated_at: datetime
    last_opened_at: datetime | None


class ItemDetail(ItemOut):
    data: dict[str, Any]


class UsageOut(BaseModel):
    items: int
    max_items: int
    bytes: int
    max_bytes: int


class ListOut(BaseModel):
    items: list[ItemOut]
    usage: UsageOut


class CreateItemIn(BaseModel):
    kind: Kind
    title: Title
    data: dict[str, Any] = Field(default_factory=dict)
    file_name: str | None = Field(default=None, max_length=300)
    # MIDI only. About 7 MB of base64 is the most a 5 MB file can be; the exact limit is checked
    # after decoding.
    file_base64: str | None = Field(default=None, max_length=7_500_000)


class UpdateItemIn(BaseModel):
    title: Title | None = None
    data: dict[str, Any] | None = None
