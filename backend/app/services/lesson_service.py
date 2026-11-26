"""Lessons for learners: curriculum order, derived progress, and engine-built examples.

Progress is derived from `exercise_attempts`: a practice goal is met when the learner has answered
at least `goal` *distinct* exercises of that kind and difficulty correctly. Nothing is stored per
lesson, so lesson status can never disagree with the practice record.
"""

import dataclasses
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import NotFoundError
from app.models.exercise_attempt import ExerciseAttempt
from app.models.movement import Movement
from app.models.user import User
from app.services import lesson_catalog
from music_theory import lessons as lx
from music_theory.exercises import KINDS


@dataclasses.dataclass(frozen=True)
class Counts:
    correct: dict[tuple[str, str], int]
    attempted: set[tuple[str, str]]


def _counts(session: Session, user: User) -> Counts:
    correct = {
        (k, d): int(n)
        for k, d, n in session.execute(
            select(
                ExerciseAttempt.kind,
                ExerciseAttempt.difficulty,
                func.count(func.distinct(ExerciseAttempt.exercise_id)),
            )
            .where(ExerciseAttempt.user_id == user.id, ExerciseAttempt.correct.is_(True))
            .group_by(ExerciseAttempt.kind, ExerciseAttempt.difficulty)
        )
    }
    attempted = {
        (k, d)
        for k, d in session.execute(
            select(ExerciseAttempt.kind, ExerciseAttempt.difficulty)
            .where(ExerciseAttempt.user_id == user.id)
            .distinct()
        )
    }
    return Counts(correct, attempted)


def _goals(lesson: lx.Lesson, c: Counts) -> list[dict[str, Any]]:
    out = []
    for g in lesson.practice:
        key = (g.kind, g.difficulty)
        n = c.correct.get(key, 0)
        out.append(
            {
                "kind": g.kind,
                "title": KINDS[g.kind].title,
                "difficulty": g.difficulty,
                "goal": g.goal,
                "correct": n,
                "attempted": key in c.attempted,
                "met": n >= g.goal,
                "ear_training": KINDS[g.kind].ear_training,
            }
        )
    return out


def _status(goals: list[dict[str, Any]]) -> str:
    if all(g["met"] for g in goals):
        return "practised"
    if any(g["attempted"] for g in goals):
        return "in_progress"
    return "not_started"


Catalog = tuple[lx.Lesson, ...]


def _statuses(c: Counts, lessons: Catalog) -> dict[str, str]:
    return {x.id: _status(_goals(x, c)) for x in lessons}


def build_list(c: Counts, lessons: Catalog | None = None) -> list[dict[str, Any]]:
    lessons = lx.all_lessons() if lessons is None else lessons
    status = _statuses(c, lessons)
    items = []
    for x in lessons:
        goals = _goals(x, c)
        items.append(
            {
                "id": x.id,
                "title": x.title,
                "level": x.level,
                "summary": x.summary,
                "tags": list(x.tags),
                "prerequisites": list(x.prerequisites),
                "unmet_prerequisites": [p for p in x.prerequisites if status[p] != "practised"],
                "status": _status(goals),
                "goals_met": sum(1 for g in goals if g["met"]),
                "goals_total": len(goals),
            }
        )
    return items


def list_lessons(session: Session, user: User) -> list[dict[str, Any]]:
    return build_list(_counts(session, user), lesson_catalog.catalog(session))


def _movement_slug(session: Session, template_id: str | None) -> str | None:
    if template_id is None:
        return None
    rows = session.scalars(
        select(Movement)
        .where(Movement.status == "published", Movement.search_text.contains(template_id.lower()))
        .order_by(Movement.name)
    )
    for row in rows:
        if (row.definition or {}).get("template_id") == template_id:
            return row.slug
    return None


def _example(spec: lx.ExampleSpec) -> dict[str, Any]:
    return dataclasses.asdict(lx.build_example(spec))


def build_detail(
    x: lx.Lesson, c: Counts, movement_slug: str | None, lessons: Catalog | None = None
) -> dict[str, Any]:
    lessons = lx.all_lessons() if lessons is None else lessons
    status = _statuses(c, lessons)
    goals = _goals(x, c)
    title = {y.id: y.title for y in lessons}
    return {
        "id": x.id,
        "title": x.title,
        "level": x.level,
        "summary": x.summary,
        "revision": x.revision,
        "tags": list(x.tags),
        "objectives": list(x.objectives),
        "sections": [
            {
                "heading": sec.heading,
                "body": list(sec.body),
                "examples": [_example(e) for e in sec.examples],
            }
            for sec in x.sections
        ],
        "practice": goals,
        "status": _status(goals),
        "prerequisites": [
            {"id": p, "title": title[p], "status": status[p]} for p in x.prerequisites
        ],
        "next": [
            {"id": f, "title": title[f], "status": status[f]}
            for f in lesson_catalog.followers_in(lessons, x.id)
        ],
        "movement_slug": movement_slug,
    }


def lesson_detail(session: Session, user: User, lesson_id: str) -> dict[str, Any]:
    lessons = lesson_catalog.catalog(session)
    x = next((y for y in lessons if y.id == lesson_id[:64]), None)
    if x is None:
        raise NotFoundError("Lesson not found.", code="lesson_not_found")
    return build_detail(
        x, _counts(session, user), _movement_slug(session, x.movement_template), lessons
    )
