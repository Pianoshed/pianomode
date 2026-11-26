"""The live lesson catalogue: built-in lessons plus published administrator-written ones.

Built-ins always come first and always win: a written lesson can never replace or shadow one. A
written lesson joins the catalogue only if every prerequisite is already in it, so a stored row
that has gone bad (or whose prerequisite was removed by hand) is skipped, never fatal.
"""

import dataclasses

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.custom_lesson import CustomLesson
from music_theory import lessons as lx
from music_theory.errors import TheoryError


def parse_row(row: CustomLesson) -> lx.Lesson:
    """The engine's lesson for a stored row, carrying the row's revision."""
    return dataclasses.replace(lx.validate_lesson(row.definition), revision=row.revision)


def catalog(session: Session) -> tuple[lx.Lesson, ...]:
    lessons: list[lx.Lesson] = list(lx.all_lessons())
    known = {x.id for x in lessons}
    rows = session.scalars(
        select(CustomLesson)
        .where(CustomLesson.status == "published")
        .order_by(CustomLesson.published_at, CustomLesson.lesson_id)
    ).all()
    for row in rows:
        try:
            lesson = parse_row(row)
        except TheoryError:
            continue
        if lesson.id in known or not all(p in known for p in lesson.prerequisites):
            continue
        lessons.append(lesson)
        known.add(lesson.id)
    return tuple(lessons)


def followers_in(lessons: tuple[lx.Lesson, ...], lesson_id: str) -> tuple[str, ...]:
    return tuple(x.id for x in lessons if lesson_id in x.prerequisites)
