import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, JsonType, TimestampMixin

KINDS = ("midi", "audio", "progression")


class LibraryItem(Base, TimestampMixin):
    """Something a person saved in My Library. Owner-only.

    `data` holds the settings the page needs to put things back as they were. Its shape belongs to
    the web app (it carries a version number), so the server only checks that it is a small JSON
    object. A MIDI item also has the .mid file itself in the file store (`file_size` > 0).
    Audio analyses never keep the audio, only the settings and corrections.
    """

    __tablename__ = "library_items"
    __table_args__ = (
        Index("ix_library_items_user_kind", "user_id", "kind"),
        Index("ix_library_items_user_opened", "user_id", "last_opened_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(12))
    title: Mapped[str] = mapped_column(String(120))
    data: Mapped[dict[str, Any]] = mapped_column(JsonType, default=dict)
    file_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    file_size: Mapped[int] = mapped_column(Integer, default=0)
    last_opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
