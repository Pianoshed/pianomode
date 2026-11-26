"""Scoring practice performances. Stateless: nothing is stored by scoring itself."""

import dataclasses
import uuid
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.errors import NotFoundError
from app.models.base import ensure_utc
from app.models.practice_attempt import PracticeAttempt
from app.models.user import User
from app.schemas import practice as s
from app.services import movement_service
from music_theory.errors import TheoryError
from music_theory.performance import (
    ExpectedNote,
    PlayedNote,
    ScoringConfig,
    restrict_to_beats,
    score_performance,
    window_for,
)


def _from_movement(session: Session, src: s.MovementSourceIn) -> tuple[list[ExpectedNote], float]:
    detail = movement_service.published_detail(session, src.slug[:80], src.key)["movement"]
    version = next((v for v in detail["versions"] if v["level"] == src.level), None)
    if version is None:
        raise NotFoundError(f"This movement has no {src.level} version.", code="version_not_found")
    expected = [
        ExpectedNote(e["midi"], e["start_beat"], e["duration_beats"], e["hand"], e["chord_index"])
        for e in version["playback"]
        if src.hands == "both" or e["hand"] == src.hands
    ]
    if not expected:
        raise TheoryError("That hand plays no notes in this version.", code="no_expected")
    return expected, float(detail["tempo"])


def score(session: Session, req: s.ScoreRequest, user: User | None = None) -> dict[str, Any]:
    if req.movement is not None:
        expected, movement_tempo = _from_movement(session, req.movement)
        source = "movement"
    else:
        assert req.expected is not None  # guaranteed by the request validator
        expected = [
            ExpectedNote(e.midi, e.start_beat, e.duration_beats, e.hand, e.chord_index)
            for e in req.expected
        ]
        movement_tempo = 0.0
        source = "explicit"
    tempo = req.tempo_bpm if req.tempo_bpm is not None else movement_tempo
    window = req.window_ms if req.window_ms is not None else window_for(req.level or "intermediate")
    cfg = ScoringConfig(
        tempo_bpm=tempo,
        window_ms=window,
        offset_s=req.offset_s,
        latency_ms=req.latency_ms,
        octave_equivalent=req.octave_equivalent,
    )
    played = [PlayedNote(p.midi, p.time_s, p.off_time_s) for p in req.played]
    if req.beat_range is not None:
        start, end = req.beat_range
        expected, played = restrict_to_beats(expected, played, cfg, start, end)
        if not expected:
            raise TheoryError("No notes start inside that beat range.", code="no_expected")
    result = score_performance(expected, played, cfg)
    out = dataclasses.asdict(result)
    out["tempo_bpm"] = tempo
    out["source"] = source
    out["saved_id"] = save_pass(session, user, req, out) if req.save is not None and user else None
    return out


# ------------------------------------------------------------------ saved results

MAX_KEPT = 2000  # newest attempts kept per learner; older ones are removed when new ones arrive
HISTORY_LIMIT = 50
PROGRESS_SCAN = 1000


def _prune(session: Session, user: User) -> None:
    old = session.scalars(
        select(PracticeAttempt.id)
        .where(PracticeAttempt.user_id == user.id)
        .order_by(PracticeAttempt.created_at.desc(), PracticeAttempt.id)
        .offset(MAX_KEPT)
    ).all()
    if old:
        session.execute(delete(PracticeAttempt).where(PracticeAttempt.id.in_(old)))


def save_pass(session: Session, user: User, req: s.ScoreRequest, out: dict[str, Any]) -> str:
    assert req.movement is not None and req.save is not None  # guaranteed by the request validator
    t = out["timing"]
    row = PracticeAttempt(
        user_id=user.id, session_id=req.save.session_id, movement_slug=req.movement.slug,
        level=req.movement.level, key=req.movement.key, mode="play", hands=req.movement.hands,
        pass_index=req.save.pass_index, tempo_bpm=out["tempo_bpm"], window_ms=out["window_ms"],
        expected=out["expected"], hits=out["hits"], accuracy=out["accuracy"],
        on_time=out["on_time"], early=out["early"], late=out["late"], missed=out["missed"],
        near_miss=out["near_miss"], extra=out["extra"], mean_error_ms=t["mean_error_ms"],
        tendency=t["tendency"],
    )  # fmt: skip
    session.add(row)
    session.flush()
    _prune(session, user)
    session.commit()
    return str(row.id)


def save_wait(session: Session, user: User, body: s.WaitResultIn) -> PracticeAttempt:
    movement_service.published_detail(session, body.movement_slug, body.key)  # 404 if not live
    row = PracticeAttempt(
        user_id=user.id, session_id=body.session_id, movement_slug=body.movement_slug,
        level=body.level, key=body.key, mode="wait", hands=body.hands, pass_index=0,
        expected=body.steps, hits=body.first_try, accuracy=round(body.first_try / body.steps, 4),
        missed=body.steps - body.first_try, extra=body.wrong_presses,
    )  # fmt: skip
    session.add(row)
    session.flush()
    _prune(session, user)
    session.commit()
    return row


def attempt_out(r: PracticeAttempt) -> dict[str, Any]:
    return {
        "id": str(r.id), "session_id": str(r.session_id),
        "created_at": ensure_utc(r.created_at).isoformat(),
        "movement_slug": r.movement_slug, "level": r.level, "key": r.key, "mode": r.mode,
        "hands": r.hands, "pass_index": r.pass_index, "tempo_bpm": r.tempo_bpm,
        "window_ms": r.window_ms, "expected": r.expected, "hits": r.hits, "accuracy": r.accuracy,
        "on_time": r.on_time, "early": r.early, "late": r.late, "missed": r.missed,
        "near_miss": r.near_miss, "extra": r.extra, "mean_error_ms": r.mean_error_ms,
        "tendency": r.tendency,
    }  # fmt: skip


def history(session: Session, user: User, movement: str | None) -> dict[str, Any]:
    base = select(PracticeAttempt).where(PracticeAttempt.user_id == user.id)
    if movement:
        base = base.where(PracticeAttempt.movement_slug == movement[:80])
    order = (PracticeAttempt.created_at.desc(), PracticeAttempt.id)
    rows = list(session.scalars(base.order_by(*order).limit(PROGRESS_SCAN)))
    groups: dict[tuple[str, str, str], list[PracticeAttempt]] = {}
    for r in rows:  # newest first
        groups.setdefault((r.movement_slug, r.level, r.mode), []).append(r)
    progress = []
    for (slug, level, mode), rs in groups.items():
        fast = [
            r.tempo_bpm for r in rs
            if r.mode == "play" and r.tempo_bpm and r.accuracy >= 0.9 and r.expected >= 8
        ]  # fmt: skip
        progress.append({
            "movement_slug": slug, "level": level, "mode": mode, "attempts": len(rs),
            "best_accuracy": max(r.accuracy for r in rs), "last_accuracy": rs[0].accuracy,
            "best_tempo_at_90": max(fast) if fast else None,
            "last_practised": ensure_utc(rs[0].created_at).isoformat(),
        })  # fmt: skip
    progress.sort(key=lambda p: str(p["last_practised"]), reverse=True)
    return {
        "items": [attempt_out(r) for r in rows[:HISTORY_LIMIT]],
        "progress": progress,
        "total": len(rows),
    }


def delete_attempt(session: Session, user: User, attempt_id: uuid.UUID) -> None:
    row = session.get(PracticeAttempt, attempt_id)
    if row is None or row.user_id != user.id:  # someone else's result looks like a missing one
        raise NotFoundError("Result not found.", code="attempt_not_found")
    session.delete(row)
    session.commit()


def delete_history(session: Session, user: User) -> int:
    n = session.execute(delete(PracticeAttempt).where(PracticeAttempt.user_id == user.id)).rowcount
    session.commit()
    return int(n or 0)
