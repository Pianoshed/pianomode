"""Request and response schemas for the music-theory API.

Requests forbid unknown fields (a typo is an error, not silently ignored) and bound every list
and number. Responses are typed too, so the web client and the OpenAPI document agree.
"""

from typing import Annotated, Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

Prefer = Literal["sharps", "flats"]
Mode = Literal["major", "minor"]
Skill = Literal["beginner", "intermediate", "advanced", "expert"]
Style = Literal["classical", "pop", "worship", "gospel", "jazz"]
Midi = Annotated[int, Field(strict=True, ge=0, le=127)]
NoteText = Annotated[str, Field(min_length=1, max_length=8)]
Symbol = Annotated[str, Field(min_length=1, max_length=40)]
Identifier = Annotated[str, Field(min_length=1, max_length=48, pattern=r"^[a-z][a-z0-9_]*$")]
NoteInput = Midi | NoteText


class Req(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Resp(BaseModel):
    model_config = ConfigDict(extra="forbid")


class KeyIn(Req):
    tonic: NoteText
    mode: Mode = "major"


class KeyOut(Resp):
    tonic: str
    mode: str
    name: str
    signature: str
    fifths: int
    relative: str
    parallel: str


# ------------------------------------------------------------------ notes


class NoteIdentifyRequest(Req):
    """Exactly one of `name` (C#4 or just Eb), `midi` or `frequency`."""

    name: str | None = Field(None, min_length=1, max_length=8)
    midi: Midi | None = None
    frequency: float | None = Field(None, gt=0, le=30000)
    a4: float = Field(440.0, ge=220, le=880)
    middle_c_octave: int = Field(4, ge=3, le=5)
    prefer: Prefer = "sharps"

    @model_validator(mode="after")
    def _one_source(self) -> Self:
        given = [x for x in (self.name, self.midi, self.frequency) if x is not None]
        if len(given) != 1:
            raise ValueError("Give exactly one of name, midi or frequency.")
        return self


class NoteOut(Resp):
    name: str
    name_unicode: str
    octave: int | None
    midi: int | None
    pitch_class: int
    frequency: float | None


class NoteIdentifyResponse(Resp):
    note: NoteOut
    enharmonic_names: list[str]
    cents_from_nearest: float | None
    input_kind: Literal["name", "midi", "frequency"]
    a4: float
    middle_c_octave: int


# ------------------------------------------------------------------ intervals


class IntervalRequest(Req):
    """Either name two notes (`lower`, `upper`) or build one (`root`, `interval`, `direction`)."""

    lower: str | None = Field(None, min_length=1, max_length=8)
    upper: str | None = Field(None, min_length=1, max_length=8)
    root: str | None = Field(None, min_length=1, max_length=8)
    interval: str | None = Field(None, min_length=1, max_length=24)
    direction: Literal["up", "down"] = "up"
    middle_c_octave: int = Field(4, ge=3, le=5)

    @model_validator(mode="after")
    def _one_mode(self) -> Self:
        between = self.lower is not None or self.upper is not None
        build = self.root is not None or self.interval is not None
        if between == build:
            raise ValueError("Give either lower and upper, or root and interval.")
        if between and (self.lower is None or self.upper is None):
            raise ValueError("Both lower and upper are needed.")
        if build and (self.root is None or self.interval is None):
            raise ValueError("Both root and interval are needed.")
        return self


class IntervalOut(Resp):
    short: str
    long: str
    quality: str
    number: int
    semitones: int
    whole_tones: float
    is_compound: bool
    simple: str
    inverted: str
    description: str


class IntervalResponse(Resp):
    interval: IntervalOut
    lower: str | None = None
    upper: str | None = None
    result: NoteOut | None = None  # the note reached when building from a root
    direction: str | None = None
    signed_semitones: int | None = None


# ------------------------------------------------------------------ scales


class ScaleRequest(Req):
    root: NoteText
    scale: Identifier = "major"
    direction: Literal["ascending", "descending"] = "ascending"
    octave: int | None = Field(None, ge=-1, le=8)
    include_octave: bool = False
    chord_size: Literal[3, 4] | None = None


class ScaleDegreeOut(Resp):
    number: int
    note: str
    interval: str


class ScaleInfo(Resp):
    id: str
    name: str
    family: str
    size: int
    formula: list[str]
    aliases: list[str]
    builtin: bool = True  # False for administrator-defined scales


class DiatonicChordOut(Resp):
    degree: int
    symbol: str | None
    tones: list[str]
    intervals: list[str]


class FingeringOut(Resp):
    right_hand: list[int]
    left_hand: list[int]
    direction: str
    note: str


class ScaleResponse(Resp):
    root: str
    scale: ScaleInfo
    direction: str
    notes: list[str]
    degrees: list[ScaleDegreeOut]
    keyboard: list[NoteOut]
    key: KeyOut | None
    diatonic_chords: list[DiatonicChordOut]
    fingering: FingeringOut | None = None  # None: no curated fingering for this scale
    fingering_note: str = (
        "Fingering is curated, not computed; it is absent for scales without curated data."
    )


class ScaleListResponse(Resp):
    scales: list[ScaleInfo]


# ------------------------------------------------------------------ chords


class SymbolStyleIn(Req):
    major7: Literal["maj7", "M7", "Δ7"] = "maj7"
    minor: Literal["m", "min", "-"] = "m"
    half_diminished: Literal["m7b5", "ø7"] = "m7b5"
    diminished: Literal["dim", "°"] = "dim"
    augmented: Literal["aug", "+"] = "aug"
    unicode_accidentals: bool = False


class ChordConstructRequest(Req):
    """Either a `symbol` (Dm7/C) or `root` plus `type` (a chord type id such as minor7)."""

    symbol: Symbol | None = None
    root: NoteText | None = None
    type: Identifier | None = None
    bass: NoteText | None = None
    inversion: int | None = Field(None, ge=0, le=6)
    octave: int = Field(4, ge=0, le=8)
    symbol_style: SymbolStyleIn | None = None

    @model_validator(mode="after")
    def _one_form(self) -> Self:
        if self.symbol is not None:
            if self.root is not None or self.type is not None or self.bass is not None:
                raise ValueError("With a symbol, do not also give root, type or bass.")
        elif self.root is None or self.type is None:
            raise ValueError("Give a symbol, or both root and type.")
        return self


class ChordToneOut(Resp):
    name: str
    interval: str
    degree: int


class ChordOut(Resp):
    symbol: str
    root: str
    type_id: str
    quality: str
    bass: str
    inversion: int | None
    inversion_name: str | None
    tones: list[ChordToneOut]
    pitch_classes: list[int]


class ChordConstructResponse(Resp):
    chord: ChordOut
    notes: list[NoteOut]
    midi_notes: list[int]
    aliases: list[str]


class ChordTypeOut(Resp):
    id: str
    name: str
    symbol: str
    family: str
    formula: list[str]
    aliases: list[str]


class ChordTypeListResponse(Resp):
    types: list[ChordTypeOut]


class ChordIdentifyRequest(Req):
    notes: list[NoteInput] = Field(min_length=1, max_length=24)
    bass: NoteText | None = None
    key: KeyIn | None = None
    prefer: Prefer = "sharps"
    allow_rootless: bool = False
    max_extra_tones: int = Field(0, ge=0, le=3)
    max_candidates: int = Field(5, ge=1, le=10)
    ambiguity_margin: float = Field(1.0, ge=0, le=10)


class CandidateOut(Resp):
    symbol: str
    root: str
    type_id: str
    quality: str
    score: float
    required_tones: list[str]
    detected_tones: list[str]
    missing_tones: list[str]
    extra_tones: list[str]
    bass: str
    inversion: int | None
    inversion_name: str | None
    rootless: bool
    added_tones: list[str]
    altered_tones: list[str]
    enharmonic_symbol: str | None
    assumptions: list[str]


class ChordIdentifyResponse(Resp):
    status: Literal["identified", "ambiguous", "no_reliable_label"]
    reason: str | None
    bass: str | None
    pitch_classes: list[int]
    candidates: list[CandidateOut]
    score_meaning: str = "Scores rank the readings against each other. They are not probabilities."


# ------------------------------------------------------------------ voicing configuration


class ConstraintsIn(Req):
    lh_range: tuple[Midi, Midi] | None = None
    rh_range: tuple[Midi, Midi] | None = None
    max_span: int | None = Field(None, ge=0, le=36)
    max_notes_per_hand: int | None = Field(None, ge=1, le=8)
    preferred_inversion: int | None = Field(None, ge=0, le=6)
    bass_pc: int | None = Field(None, ge=0, le=11)
    required_tones: list[Annotated[str, Field(max_length=12)]] = Field(
        default_factory=list, max_length=8
    )
    forbidden_tones: list[Annotated[str, Field(max_length=12)]] = Field(
        default_factory=list, max_length=8
    )
    tensions: list[Annotated[str, Field(max_length=12)]] = Field(default_factory=list, max_length=6)
    max_leap: int | None = Field(None, ge=0, le=36)
    lh_center: Midi | None = None
    rh_center: Midi | None = None
    min_hand_gap: int | None = Field(None, ge=0, le=24)


class VoiceLeadingIn(Req):
    style: Style = "pop"
    weight_preset: Literal["balanced", "smooth", "complete", "root_position", "easy"] = "balanced"
    weights: dict[str, Annotated[float, Field(ge=0, le=100)]] = Field(
        default_factory=dict, max_length=16
    )
    strict_counterpoint: bool = False


class VoicingConfigIn(Req):
    skill: Skill = "intermediate"
    preset: Identifier | None = None
    constraints: ConstraintsIn | None = None
    voice_leading: VoiceLeadingIn = Field(default_factory=VoiceLeadingIn)


class VoicingIn(Req):
    left: list[Midi] = Field(default_factory=list, max_length=8)
    right: list[Midi] = Field(default_factory=list, max_length=8)
    lh_style: str = Field("", max_length=32)
    rh_style: str = Field("", max_length=32)

    @model_validator(mode="after")
    def _has_notes(self) -> Self:
        if not self.left and not self.right:
            raise ValueError("A voicing needs at least one note.")
        return self


class VoicingOut(Resp):
    left: list[int]
    right: list[int]
    left_names: list[str]
    right_names: list[str]
    lh_style: str
    rh_style: str
    tensions: list[str]
    omitted: list[str]
    rh_inversion: int | None


class CostOut(Resp):
    total: float
    parts: dict[str, float]


class TransitionOut(Resp):
    movement: int
    largest_leap: int
    common_tones: int
    bass_motion: int
    parallel_fifths: int
    parallel_octaves: int
    leap_excess: int
    cost: CostOut


class ScoredVoicingOut(Resp):
    voicing: VoicingOut
    static_cost: CostOut | None = None


class VoicingsGenerateRequest(Req):
    chord: Symbol
    config: VoicingConfigIn = Field(default_factory=VoicingConfigIn)
    limit: int = Field(25, ge=1, le=200)
    rank: bool = True


class VoicingsGenerateResponse(Resp):
    chord: ChordOut
    total_found: int
    returned: int
    ranking: str
    voicings: list[ScoredVoicingOut]
    message: str | None = None


class ChosenOut(Resp):
    chord: str
    voicing: VoicingOut
    static_cost: CostOut
    transition: TransitionOut | None
    cost: float
    explanation: list[str]


class VoicingSequenceRequest(Req):
    chords: list[Symbol] = Field(min_length=1, max_length=16)
    config: VoicingConfigIn = Field(default_factory=VoicingConfigIn)
    fixed: dict[int, VoicingIn] = Field(default_factory=dict, max_length=16)
    max_candidates: int = Field(60, ge=1, le=80)
    method: Literal["auto", "dp", "beam"] = "auto"


class VoicingSequenceResponse(Resp):
    items: list[ChosenOut]
    total_cost: float
    method: str
    relaxed_leap_limit: bool
    warnings: list[str]


class VoiceLeadingEvaluateRequest(Req):
    chords: list[Symbol] = Field(min_length=1, max_length=16)
    voicings: list[VoicingIn] = Field(min_length=1, max_length=16)
    config: VoicingConfigIn = Field(default_factory=VoicingConfigIn)


class VoiceLeadingEvaluateResponse(Resp):
    total_cost: float
    items: list[ChosenOut]
    score_meaning: str = "Lower cost is better. Costs compare voicings; they are not grades."


# ------------------------------------------------------------------ harmony and keys


class HarmonyAnalyzeRequest(Req):
    chords: list[Symbol] = Field(min_length=1, max_length=64)
    key: KeyIn | None = None
    durations: list[Annotated[float, Field(gt=0, le=64)]] | None = Field(None, max_length=64)
    min_phrase_chords: int = Field(3, ge=1, le=16)


class NumeralOut(Resp):
    symbol: str
    figure: str
    degree: int
    category: str
    function: str | None
    applied_to: str | None
    borrowed_from: str | None
    inversion: int | None
    note: str | None
    alternatives: list[str]


class CadenceOut(Resp):
    start: int
    end: int
    kind: str
    note: str


class KeyCandidateOut(Resp):
    key: KeyOut
    score: float


class KeyEstimateOut(Resp):
    candidates: list[KeyCandidateOut]
    reliable: bool
    ambiguous: bool
    warnings: list[str]
    method: str
    score_meaning: str = "Scores rank keys against each other; they are not probabilities."


class ModulationOut(Resp):
    index: int
    from_key: str
    to_key: str
    note: str


class RelationshipOut(Resp):
    start: int
    end: int
    common_tones: list[str]
    root_semitones: int
    root_motion: str
    kinds: list[str]
    transform: str | None
    voice_leading_distance: int
    unmatched_tones: int
    non_diatonic: bool | None
    note: str


class PhraseOut(Resp):
    index: int
    start: int
    end: int
    figures: list[str]
    function_path: list[str]
    cadence: str | None
    character: str
    short: bool
    duration_beats: float | None
    text: str


class HarmonyAnalyzeResponse(Resp):
    key: KeyOut | None
    key_source: Literal["provided", "estimated"] | None
    key_estimate: KeyEstimateOut | None
    numerals: list[NumeralOut]
    cadences: list[CadenceOut]
    modulation_candidates: list[ModulationOut]
    relationships: list[RelationshipOut] = []
    phrases: list[PhraseOut] = []
    phrase_note: str | None = None
    warnings: list[str]


class KeyEstimateRequest(Req):
    pitch_class_weights: list[Annotated[float, Field(ge=0, le=1e9)]] | None = Field(
        None, min_length=12, max_length=12
    )
    chords: list[Symbol] | None = Field(None, min_length=1, max_length=64)
    durations: list[Annotated[float, Field(gt=0, le=64)]] | None = Field(None, max_length=64)
    top: int = Field(5, ge=1, le=24)

    @model_validator(mode="after")
    def _one_source(self) -> Self:
        if (self.pitch_class_weights is None) == (self.chords is None):
            raise ValueError("Give exactly one of pitch_class_weights or chords.")
        return self


# ------------------------------------------------------------------ progressions


class CustomChordIn(Req):
    symbol: Symbol
    beats: float = Field(4.0, gt=0, le=64)


class ProgressionGenerateRequest(Req):
    key: KeyIn
    template_id: Identifier | None = None
    chords: list[CustomChordIn] | None = Field(None, min_length=1, max_length=64)
    name: str | None = Field(None, min_length=1, max_length=100)
    vocabulary: Literal["triads", "sevenths"] = "triads"
    tempo: int | None = Field(None, ge=20, le=400)
    time_signature: tuple[int, Literal[1, 2, 4, 8, 16, 32]] | None = None
    difficulty: Skill | None = None
    styles: list[Annotated[str, Field(max_length=32)]] = Field(default_factory=list, max_length=8)
    voicing: VoicingConfigIn | None = None

    @model_validator(mode="after")
    def _one_source(self) -> Self:
        if (self.template_id is None) == (self.chords is None):
            raise ValueError("Give exactly one of template_id or chords.")
        if self.time_signature is not None and not 1 <= self.time_signature[0] <= 32:
            raise ValueError("The time signature numerator must be 1 to 32.")
        return self


class ProgressionResponse(Resp):
    progression: dict[str, Any]
    chord_details: list[ChordOut]
    voicing: list[ChosenOut] | None = None
    voicing_total_cost: float | None = None
    warnings: list[str] = []


class ProgressionTransposeRequest(Req):
    progression: dict[str, Any]
    target: NoteText
    on_unplayable: Literal["revoice", "drop", "error"] = "revoice"
    voicing: VoicingConfigIn | None = None


class ProgressionTransposeResponse(Resp):
    progression: dict[str, Any]
    shift_semitones: int
    revoiced: bool
    warnings: list[str]


class ProgressionValidateRequest(Req):
    progression: dict[str, Any]
    strict_harmony: bool = False
    publication: bool = False
    deep: bool = False
    voicing: VoicingConfigIn | None = None


class IssueOut(Resp):
    severity: Literal["error", "warning"]
    code: str
    message: str
    index: int | None


class ProgressionValidateResponse(Resp):
    ok: bool
    errors: list[IssueOut]
    warnings: list[IssueOut]


class TemplateOut(Resp):
    id: str
    name: str
    mode: str
    difficulty: str
    styles: list[str]
    explanation: str
    practice: str
    time_signature: tuple[int, int]
    numerals_triads: list[str]
    numerals_sevenths: list[str]
    beats: list[float]


class TemplateListResponse(Resp):
    templates: list[TemplateOut]


# ------------------------------------------------------------------ MIDI


class MidiEventIn(Req):
    tick: int = Field(ge=0, le=2**40)
    kind: Literal["note_on", "note_off"]
    note: Midi
    velocity: int = Field(64, ge=0, le=127)
    channel: int = Field(0, ge=0, le=15)
    track: int = Field(0, ge=0, le=255)


class TempoChangeIn(Req):
    tick: int = Field(ge=0, le=2**40)
    bpm: float = Field(gt=0, le=1000)


class TimeSignatureIn(Req):
    tick: int = Field(ge=0, le=2**40)
    numerator: int = Field(ge=1, le=64)
    denominator: Literal[1, 2, 4, 8, 16, 32]


class TrackStateIn(Req):
    track: int = Field(ge=0, le=255)
    name: str | None = Field(None, max_length=60)
    hand: Literal["L", "R", "both", "other"] | None = None
    muted: bool = False
    solo: bool = False


class MidiAnalyzeRequest(Req):
    ppq: int = Field(480, ge=1, le=100_000)
    events: list[MidiEventIn] = Field(min_length=1, max_length=20_000)
    tempo_changes: list[TempoChangeIn] = Field(default_factory=list, max_length=2000)
    time_signatures: list[TimeSignatureIn] = Field(default_factory=list, max_length=2000)
    key: KeyIn | None = None
    grid: Literal["beat", "half_bar", "bar"] = "beat"
    prefer: Prefer = "sharps"
    min_note_fraction: float = Field(0.2, ge=0, le=1)
    max_candidates: int = Field(3, ge=1, le=5)
    track_states: list[TrackStateIn] | None = Field(None, max_length=256)
    hand_edits: dict[int, Literal["L", "R"]] = Field(default_factory=dict, max_length=20_000)
    split_pitch: Midi = 60
    include_notes: bool = True


class MidiNoteOut(Resp):
    id: int
    midi: int
    name: str
    velocity: int
    track: int
    channel: int
    start_beat: float
    end_beat: float
    start_sec: float
    end_sec: float
    duration_beats: float
    hand: Literal["L", "R"] | None
    hand_source: Literal["auto", "user"] | None


class MidiSegmentOut(Resp):
    origin: Literal["midi"] = "midi"
    start_beat: float
    end_beat: float
    start_sec: float
    end_sec: float
    status: Literal["identified", "ambiguous", "no_reliable_label", "silence"]
    reason: str | None
    bass: str | None
    pitches: list[int]
    candidates: list[CandidateOut]
    numeral: NumeralOut | None
    warnings: list[str]


class MidiAnalyzeResponse(Resp):
    segments: list[MidiSegmentOut]
    key: KeyOut | None
    key_source: Literal["provided", "estimated"] | None
    key_estimate: KeyEstimateOut
    note_count: int
    duration_beats: float
    notes: list[MidiNoteOut] | None
    warnings: list[str]
    hand_note: str = (
        "Hands are suggestions (source 'auto') until a person edits them (source 'user'). "
        "Track numbers are not assumed to be hands."
    )


# ------------------------------------------------------------------ audio interpretation


class AudioRegionIn(Req):
    start: float = Field(ge=0, le=86_400)
    end: float = Field(gt=0, le=86_400)
    label: str = Field(min_length=1, max_length=40)
    scores: dict[str, float] | None = Field(None, max_length=60)
    bass_pc: int | None = Field(None, ge=0, le=11)
    pitch_classes: list[Annotated[int, Field(ge=0, le=11)]] | None = Field(None, max_length=12)
    probability: float | None = Field(None, ge=0, le=1)
    calibration: str | None = Field(None, min_length=1, max_length=100)


class CorrectionIn(Req):
    op: Literal["relabel", "retime", "add", "delete"]
    index: int | None = Field(None, ge=0, le=100_000)
    label: str | None = Field(None, min_length=1, max_length=40)
    start: float | None = Field(None, ge=0, le=86_400)
    end: float | None = Field(None, gt=0, le=86_400)

    @model_validator(mode="after")
    def _fields_for_op(self) -> Self:
        need = {
            "relabel": ("index", "label"),
            "retime": ("index", "start", "end"),
            "add": ("start", "end", "label"),
            "delete": ("index",),
        }[self.op]
        missing = [f for f in need if getattr(self, f) is None]
        if missing:
            raise ValueError(f"{self.op} needs: {', '.join(missing)}")
        return self


class AlternativeOut(Resp):
    label: str | None
    symbol: str | None
    source: Literal["model", "pitch_evidence"]
    model_score: float | None


class HypothesisOut(Resp):
    origin: Literal["audio", "user"]
    start: float
    end: float
    status: Literal["estimated", "ambiguous", "no_chord", "unrecognised_label", "user_set"]
    symbol: str | None
    raw_label: str
    alternatives: list[AlternativeOut]
    model_score: float | None
    confidence: float | None
    calibration: str | None
    bass: str | None
    pitch_classes: list[int] | None
    numeral: NumeralOut | None
    warnings: list[str]


class CorrectionOut(Resp):
    kind: str
    index: int
    before: HypothesisOut | None
    after: HypothesisOut | None


class AudioInterpretRequest(Req):
    regions: list[AudioRegionIn] = Field(min_length=1, max_length=2000)
    key: KeyIn | None = None
    min_duration: float = Field(0.25, ge=0, le=60)
    score_margin: float = Field(0.1, ge=0, le=1000)
    prefer: Prefer = "sharps"
    corrections: list[CorrectionIn] = Field(default_factory=list, max_length=200)


class AudioInterpretResponse(Resp):
    hypotheses: list[HypothesisOut]
    original: list[HypothesisOut] | None
    corrections: list[CorrectionOut]
    key: KeyOut | None
    key_source: Literal["provided", "estimated"] | None
    key_estimate: KeyEstimateOut | None
    warnings: list[str]
    evidence_note: str = (
        "These chords are estimates from audio, not known pitches. Scores are raw model output "
        "and are not probabilities unless a named calibration is shown."
    )


# ------------------------------------------------------------------ exercises

Answer = str | list[Annotated[str, Field(max_length=64)]] | list[Midi]


class ExerciseGenerateRequest(Req):
    kind: Identifier
    difficulty: Skill = "beginner"
    seed: int | None = Field(None, ge=0, le=2**31 - 1)
    count: int = Field(1, ge=1, le=50)


class PlayEventOut(Resp):
    notes: list[int]
    start: float
    duration: float


class ExerciseOut(Resp):
    id: str
    kind: str
    difficulty: str
    seed: int
    topic: str
    prompt: str
    answer_format: Literal["choice", "text", "note_names", "note_set", "chord_symbols"]
    answer_help: str
    choices: list[str]
    show: list[int]
    play: list[PlayEventOut]
    tempo: int
    hint: str


class ExerciseSetResponse(Resp):
    exercises: list[ExerciseOut]


class ExerciseValidateRequest(Req):
    exercise_id: str = Field(min_length=1, max_length=80)
    answer: Answer


class ItemResultOut(Resp):
    index: int
    given: str
    correct: bool
    expected: str


class ExerciseGradeResponse(Resp):
    exercise_id: str
    status: Literal["correct", "enharmonic", "partial", "incorrect", "unreadable"]
    correct: bool
    feedback: str
    correct_answer: str
    explanation: str
    items: list[ItemResultOut]


class ExerciseKindOut(Resp):
    kind: str
    title: str
    topic: str
    objective: str
    prerequisites: list[str]
    ear_training: bool


class ExerciseKindListResponse(Resp):
    difficulties: list[str]
    kinds: list[ExerciseKindOut]


class KindProgressOut(Resp):
    kind: str
    difficulty: str
    attempts: int
    correct: int
    recent_attempts: int
    recent_correct: int
    last_at: str


class ExerciseProgressResponse(Resp):
    items: list[KindProgressOut]
    note: str = (
        "Counts of graded answers only. Answers that could not be read are not counted, and "
        "the same exercise answered twice counts twice."
    )
