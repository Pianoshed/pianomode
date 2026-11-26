import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, utcnow


class PracticeAttempt(Base):
    """One scored pass (or one wait-mode run) of a published movement. Only results are stored:
    never the notes that were played. Owner-only."""

    __tablename__ = "practice_attempts"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    session_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    movement_slug: Mapped[str] = mapped_column(String(80), index=True)
    level: Mapped[str] = mapped_column(String(16))
    key: Mapped[str | None] = mapped_column(String(4), nullable=True)
    mode: Mapped[str] = mapped_column(String(8))  # "play" (timed, scored) or "wait"
    hands: Mapped[str] = mapped_column(String(4))  # both | L | R
    pass_index: Mapped[int] = mapped_column(Integer, default=0)
    tempo_bpm: Mapped[float | None] = mapped_column(Float, nullable=True)
    window_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    expected: Mapped[int] = mapped_column(Integer)
    hits: Mapped[int] = mapped_column(Integer)
    accuracy: Mapped[float] = mapped_column(Float)
    on_time: Mapped[int] = mapped_column(Integer, default=0)
    early: Mapped[int] = mapped_column(Integer, default=0)
    late: Mapped[int] = mapped_column(Integer, default=0)
    missed: Mapped[int] = mapped_column(Integer, default=0)
    near_miss: Mapped[int] = mapped_column(Integer, default=0)
    extra: Mapped[int] = mapped_column(Integer, default=0)
    mean_error_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    tendency: Mapped[str | None] = mapped_column(String(20), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )
