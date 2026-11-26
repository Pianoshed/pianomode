"""Music-theory endpoints.

All routes are deterministic, synchronous and CPU-bounded (inputs are size-limited). They need a
signed-in user and are rate limited per client address; the combinatorial ones (voicings, voice
leading, progressions, MIDI) have a tighter limit. Audio *analysis* is not here: it is a
background job. `POST /audio/interpret` only interprets estimates the audio worker has produced.

Musical errors are `TheoryError`s and come back as 422 with a stable `error.code`.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.deps import CurrentUser, SessionDep, require_access
from app.core.rate_limit import rate_limited
from app.schemas import theory as s
from app.schemas.errors import ErrorResponse
from app.services import exercise_service, scale_service
from app.services import theory_service as svc

MINUTE = 60

router = APIRouter(
    prefix="/api/v1/theory",
    tags=["theory"],
    dependencies=[
        Depends(require_access),
        Depends(rate_limited("theory", 600, MINUTE, by_session=True)),
    ],
    responses={401: {"model": ErrorResponse}, 422: {"model": ErrorResponse}},
)
heavy = [Depends(rate_limited("theory_heavy", 30, MINUTE, by_session=True))]
# MIDI Studio re-analyses on every mute, merge or setting change, so it has its own, larger bucket.
# A request is bounded (20,000 events), so this stays cheap.
midi_heavy = [Depends(rate_limited("theory_midi", 60, MINUTE, by_session=True))]
# The Audio Analyzer re-interprets after every correction (relabel, retime, add, delete).
audio_heavy = [Depends(rate_limited("theory_audio", 60, MINUTE, by_session=True))]


# notes, intervals, scales -------------------------------------------------------------------


@router.post("/notes/identify", response_model=s.NoteIdentifyResponse)
def identify_note(body: s.NoteIdentifyRequest) -> s.NoteIdentifyResponse:
    """Identify a note from its name, MIDI number or frequency (configurable A4 and octave
    convention). Returns enharmonic spellings and, for a frequency, the cents off the nearest
    note."""
    return svc.identify_note(body)


@router.post("/intervals", response_model=s.IntervalResponse)
def intervals(body: s.IntervalRequest) -> s.IntervalResponse:
    """Name the interval between two notes, or find the note an interval above/below a root."""
    return svc.interval(body)


@router.get("/scales", response_model=s.ScaleListResponse)
def list_scales(session: SessionDep) -> s.ScaleListResponse:
    """Built-in scales plus published administrator-defined scales."""
    return svc.list_scales(scale_service.live_registry(session))


@router.post("/scales/generate", response_model=s.ScaleResponse)
def generate_scale(body: s.ScaleRequest, session: SessionDep) -> s.ScaleResponse:
    """A scale or mode on any root, with degrees, keyboard notes and optional diatonic chords."""
    return svc.generate_scale(body, scale_service.live_registry(session))


# chords -------------------------------------------------------------------------------------


@router.get("/chords/types", response_model=s.ChordTypeListResponse)
def list_chord_types() -> s.ChordTypeListResponse:
    return svc.list_chord_types()


@router.post("/chords/construct", response_model=s.ChordConstructResponse)
def construct_chord(body: s.ChordConstructRequest) -> s.ChordConstructResponse:
    """Build a chord from a symbol (strictly parsed) or from root + type, with inversion."""
    return svc.construct_chord(body)


@router.post("/chords/identify", response_model=s.ChordIdentifyResponse)
def identify_chord(body: s.ChordIdentifyRequest) -> s.ChordIdentifyResponse:
    """Ranked chord readings of some notes, or an explicit "no reliable label"."""
    return svc.identify(body)


# keys and harmony ---------------------------------------------------------------------------


@router.post("/keys/estimate", response_model=s.KeyEstimateOut)
def estimate_key(body: s.KeyEstimateRequest) -> s.KeyEstimateOut:
    """Key candidates from pitch-class weights or from chords. An estimate, never a certainty."""
    return svc.estimate_key_request(body)


@router.post("/harmony/analyze", response_model=s.HarmonyAnalyzeResponse)
def analyze_harmony(body: s.HarmonyAnalyzeRequest) -> s.HarmonyAnalyzeResponse:
    """Roman numerals, cadences and modulation candidates for a chord list."""
    return svc.analyze_harmony(body)


# progressions -------------------------------------------------------------------------------


@router.get("/progressions/templates", response_model=s.TemplateListResponse)
def list_templates(
    style: Annotated[str | None, Query(max_length=32)] = None,
    difficulty: Annotated[str | None, Query(max_length=16)] = None,
    mode: Annotated[str | None, Query(max_length=8)] = None,
) -> s.TemplateListResponse:
    return svc.list_templates(style, difficulty, mode)


@router.post("/progressions/generate", response_model=s.ProgressionResponse, dependencies=heavy)
def generate_progression(body: s.ProgressionGenerateRequest) -> s.ProgressionResponse:
    """A progression from a template or custom chords, optionally with smooth two-hand voicings."""
    return svc.generate_progression_request(body)


@router.post(
    "/progressions/transpose", response_model=s.ProgressionTransposeResponse, dependencies=heavy
)
def transpose_progression(body: s.ProgressionTransposeRequest) -> s.ProgressionTransposeResponse:
    """Move a stored progression to another key, preserving function and re-voicing if needed."""
    return svc.transpose(body)


@router.post(
    "/progressions/validate", response_model=s.ProgressionValidateResponse, dependencies=heavy
)
def validate_progression(body: s.ProgressionValidateRequest) -> s.ProgressionValidateResponse:
    """Errors and warnings for a stored progression (add `publication` before publishing)."""
    return svc.validate_progression_request(body)


# voicings and voice leading -----------------------------------------------------------------


@router.post("/voicings/generate", response_model=s.VoicingsGenerateResponse, dependencies=heavy)
def generate_voicings(body: s.VoicingsGenerateRequest) -> s.VoicingsGenerateResponse:
    """Playable two-hand voicings of one chord under configurable ranges, span and style."""
    return svc.generate_voicing_options(body)


@router.post("/voicings/sequence", response_model=s.VoicingSequenceResponse, dependencies=heavy)
def voice_sequence(body: s.VoicingSequenceRequest) -> s.VoicingSequenceResponse:
    """The smoothest sequence of voicings for a list of chords (deterministic)."""
    return svc.voice_sequence(body)


@router.post(
    "/voice-leading/evaluate", response_model=s.VoiceLeadingEvaluateResponse, dependencies=heavy
)
def evaluate_voice_leading(body: s.VoiceLeadingEvaluateRequest) -> s.VoiceLeadingEvaluateResponse:
    """Score voicings someone else chose, with a per-component cost and explanation."""
    return svc.evaluate_voice_leading(body)


# MIDI and audio -----------------------------------------------------------------------------


@router.post("/midi/analyze", response_model=s.MidiAnalyzeResponse, dependencies=midi_heavy)
def analyze_midi(body: s.MidiAnalyzeRequest) -> s.MidiAnalyzeResponse:
    """Chords, key, numerals and suggested hands for MIDI note events."""
    return svc.analyze_midi(body)


@router.post("/audio/interpret", response_model=s.AudioInterpretResponse, dependencies=audio_heavy)
def interpret_audio(body: s.AudioInterpretRequest) -> s.AudioInterpretResponse:
    """Interpret chord estimates from the audio worker, apply corrections. No audio is processed."""
    return svc.interpret_audio(body)


# exercises ----------------------------------------------------------------------------------


@router.get("/exercises/kinds", response_model=s.ExerciseKindListResponse)
def list_exercise_kinds() -> s.ExerciseKindListResponse:
    return svc.list_exercise_kinds()


@router.post("/exercises/generate", response_model=s.ExerciseSetResponse)
def generate_exercises(body: s.ExerciseGenerateRequest) -> s.ExerciseSetResponse:
    """Generated exercises. The ids are stateless: the server can regrade them from the id."""
    return svc.make_exercises(body)


@router.post("/exercises/validate", response_model=s.ExerciseGradeResponse)
def validate_exercise(
    body: s.ExerciseValidateRequest, user: CurrentUser, session: SessionDep
) -> s.ExerciseGradeResponse:
    """Grade an answer with the theory engine (never a language model). Each graded answer is
    recorded for the learner's progress; unreadable answers are not."""
    grade = svc.grade_exercise(body)
    exercise_service.record_attempt(session, user, body.exercise_id, grade.status, grade.correct)
    return grade


@router.get("/exercises/progress", response_model=s.ExerciseProgressResponse)
def exercise_progress(user: CurrentUser, session: SessionDep) -> s.ExerciseProgressResponse:
    """The signed-in learner's own counts per exercise kind and difficulty."""
    return s.ExerciseProgressResponse(
        items=[s.KindProgressOut(**vars(p)) for p in exercise_service.progress(session, user)]
    )
