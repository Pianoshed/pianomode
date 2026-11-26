import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, utcnow


class ExerciseAttempt(Base):
    """One graded answer. Exercises are stateless (the id regenerates them), so this records only
    the result, never the question text or the answer the learner typed."""

    __tablename__ = "exercise_attempts"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    exercise_id: Mapped[str] = mapped_column(String(80))
    kind: Mapped[str] = mapped_column(String(48), index=True)
    difficulty: Mapped[str] = mapped_column(String(12))
    status: Mapped[str] = mapped_column(String(12))
    correct: Mapped[bool] = mapped_column(Boolean)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )
