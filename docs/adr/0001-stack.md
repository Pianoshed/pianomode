# ADR 0001 — Stack and layering

**Status:** accepted

- **API:** FastAPI (typed schemas, OpenAPI docs, native fit with librosa/pretty_midi). Django was considered for its admin/ORM; we use SQLAlchemy + Alembic and build the admin publishing workflow explicitly because it needs bespoke validation (theory engine) anyway.
- **Layering:** `api/routes` (HTTP only) → `services` (business logic, transactions) → `models` (SQLAlchemy). Routes never contain business rules.
- **Errors:** every failure returns `{"error": {"code", "message", "details"}}` with stable machine-readable codes.
- **Jobs:** expensive work (audio analysis, conversion) runs in Celery workers. Job rows are the source of truth for status: `queued → processing → completed | failed | cancelled`, enforced by a transition table in `services/job_service.py`.
- **Config:** environment variables with the `PIANO_` prefix, validated by pydantic-settings.
- **Theory engine:** a pure-Python package (`backend/music_theory`) with no web/DB imports, built in its own phase.
