"""Recording and summarising graded exercise attempts.

Progress is plain counts: attempts, correct answers, and the last RECENT attempts. There is no
"mastery" score: that would need evidence about what a good threshold is, and none exists yet.
"""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.exercise_attempt import ExerciseAttempt
from app.models.user import User
from music_theory.exercises import parse_exercise_id

RECENT = 10
MAX_ROWS = 5000  # most recent attempts considered; bounds the work for a very active learner


@dataclass(frozen=True)
class KindProgress:
    kind: str
    difficulty: str
    attempts: int
    correct: int
    recent_attempts: int
    recent_correct: int
    last_at: str


def record_attempt(
    session: Session, user: User, exercise_id: str, status: str, correct: bool
) -> None:
    """Store one result. Answers that could not be read are not attempts (the learner is asked
    again), and ids that do not parse are not stored (grading would already have failed)."""
    if status == "unreadable":
        return
    kind, difficulty, _seed = parse_exercise_id(exercise_id)
    session.add(
        ExerciseAttempt(
            user_id=user.id,
            exercise_id=exercise_id,
            kind=kind,
            difficulty=difficulty,
            status=status,
            correct=correct,
        )
    )
    session.commit()


def progress(session: Session, user: User) -> list[KindProgress]:
    rows = session.scalars(
        select(ExerciseAttempt)
        .where(ExerciseAttempt.user_id == user.id)
        .order_by(ExerciseAttempt.created_at.desc(), ExerciseAttempt.id)
        .limit(MAX_ROWS)
    ).all()
    groups: dict[tuple[str, str], list[ExerciseAttempt]] = {}
    for r in rows:  # newest first
        groups.setdefault((r.kind, r.difficulty), []).append(r)
    out = []
    for (kind, difficulty), items in sorted(groups.items()):
        recent = items[:RECENT]
        out.append(
            KindProgress(
                kind=kind,
                difficulty=difficulty,
                attempts=len(items),
                correct=sum(1 for i in items if i.correct),
                recent_attempts=len(recent),
                recent_correct=sum(1 for i in recent if i.correct),
                last_at=items[0].created_at.isoformat(),
            )
        )
    return out
