"""Everything the dashboard shows, built from the person's own stored activity (no sample data)."""

from collections import Counter
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.base import ensure_utc, utcnow
from app.models.exercise_attempt import ExerciseAttempt
from app.models.library import LibraryItem
from app.models.practice_attempt import PracticeAttempt
from app.models.user import User
from app.services import lesson_service

ACTIVITY_DAYS = 7


def _lessons(session: Session, user: User) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    lessons = lesson_service.list_lessons(session, user)
    title = {x["id"]: x["title"] for x in lessons}
    current = [
        {
            "id": x["id"],
            "title": x["title"],
            "goals_met": x["goals_met"],
            "goals_total": x["goals_total"],
            "progress_percent": round(100 * x["goals_met"] / x["goals_total"])
            if x["goals_total"]
            else 0,
        }
        for x in lessons
        if x["status"] == "in_progress"
    ][:3]
    nxt = next(
        (x for x in lessons if x["status"] == "not_started" and not x["unmet_prerequisites"]), None
    )
    recommended = None
    if nxt is not None:
        done = [title[p] for p in nxt["prerequisites"] if p in title]
        recommended = {
            "id": nxt["id"],
            "title": nxt["title"],
            "summary": nxt["summary"],
            "reason": (
                f"You have practised {', '.join(done)}, so this is the next step."
                if done
                else "A good place to begin."
            ),
        }
    return current, recommended


def _recent(session: Session, user: User, kinds: tuple[str, ...], limit: int) -> list[LibraryItem]:
    when = func.coalesce(LibraryItem.last_opened_at, LibraryItem.created_at)
    return list(
        session.scalars(
            select(LibraryItem)
            .where(LibraryItem.user_id == user.id, LibraryItem.kind.in_(kinds))
            .order_by(when.desc())
            .limit(limit)
        )
    )


def activity(session: Session, user: User, now: datetime) -> list[dict[str, Any]]:
    """Practice passes and theory answers per day for the last 7 days (UTC days), oldest first."""
    today = now.date()
    first = today - timedelta(days=ACTIVITY_DAYS - 1)
    start = datetime.combine(first, datetime.min.time(), tzinfo=now.tzinfo)
    counts: Counter[str] = Counter()
    for model in (PracticeAttempt, ExerciseAttempt):
        for (created,) in session.execute(
            select(model.created_at).where(model.user_id == user.id, model.created_at >= start)
        ):
            counts[ensure_utc(created).date().isoformat()] += 1
    return [
        {
            "date": (d := first + timedelta(days=i)).isoformat(),
            "count": counts.get(d.isoformat(), 0),
        }
        for i in range(ACTIVITY_DAYS)
    ]


def build_dashboard(session: Session, user: User, now: datetime | None = None) -> dict[str, Any]:
    now = now or utcnow()
    current, recommended = _lessons(session, user)
    days = activity(session, user, now)
    return {
        "continue_learning": current,
        "recommended": recommended,
        "recent_projects": [
            {
                "id": i.id,
                "kind": i.kind,
                "title": i.title,
                "opened_at": i.last_opened_at or i.created_at,
            }
            for i in _recent(session, user, ("midi", "audio"), 5)
        ],
        "saved_progressions": [
            {"id": i.id, "title": i.title, "data": i.data}
            for i in _recent(session, user, ("progression",), 5)
        ],
        "activity": days,
        "activity_total": sum(d["count"] for d in days),
    }
