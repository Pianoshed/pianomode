"""Glue between the HTTP schemas and the pure-Python theory engine.

Everything here is deterministic and synchronous. Nothing here runs audio models: audio analysis
is a background job (a later phase) whose *output* is interpreted by `interpret_audio`.
"""

import dataclasses
import random
from collections.abc import Sequence
from typing import Any

from app.schemas import theory as s
from music_theory import validation as v
from music_theory.audio_interpretation import (
    AudioRegion,
    ChordHypothesis,
    CorrectedAnalysis,
    add_region,
    delete_region,
    interpret_regions,
    relabel,
    retime,
    start_corrections,
)
from music_theory.chord_symbols import SymbolStyle, format_chord, parse_chord
from music_theory.chords import CHORD_TYPES, Chord, inversion_name, make_chord
from music_theory.errors import TheoryError
from music_theory.exercises import (
    DIFFICULTIES,
    KINDS,
    generate_exercise,
    generate_set,
    parse_interval_answer,
    validate_answer,
)
from music_theory.fingering import scale_fingering
from music_theory.harmony import diatonic_chords
from music_theory.identify import ChordCandidate, identify_chord
from music_theory.intervals import (
    Interval,
    interval_between_names,
    interval_between_notes,
    signed_semitones,
    transpose_name,
    transpose_note,
)
from music_theory.key_analysis import (
    KeyEstimate,
    detect_modulations,
    estimate_key,
    rank_keys_for_chords,
)
from music_theory.keys import Key
from music_theory.midi_analysis import (
    MidiEvent,
    NoteEvent,
    TempoChange,
    TempoMap,
    TimeSignatureChange,
    TrackState,
    analyze_notes,
    assign_hands,
    filter_audible,
    notes_from_events,
)
from music_theory.notes import (
    Note,
    NoteName,
    frequency_to_note,
    note_from_midi,
    parse_note_name,
)
from music_theory.phrases import PHRASE_LIMITATION, segment_phrases
from music_theory.progressions import (
    Progression,
    ValidationReport,
    default_library,
    make_progression,
    migrate_progression_data,
    progression_from_dict,
    progression_to_dict,
    realize,
    transpose_progression,
    validate_progression,
    voice_progression,
)
from music_theory.relationships import analyze_relationships
from music_theory.roman import RomanNumeral, analyze_progression, find_cadences
from music_theory.scales import ScaleDefinition, ScaleRegistry, default_registry, make_scale
from music_theory.voice_leading import (
    WEIGHT_PRESETS,
    ChosenVoicing,
    CostBreakdown,
    TransitionEvaluation,
    VoiceLeadingConfig,
    VoiceLeadingWeights,
    evaluate_sequence,
    static_cost,
    voice_chords,
)
from music_theory.voicings import (
    Voicing,
    VoicingConstraints,
    constraints_for_skill,
    generate_voicings,
)

# ------------------------------------------------------------------ small converters


def _key_out(key: Key) -> s.KeyOut:
    sig = key.signature
    return s.KeyOut(
        tonic=str(key.tonic),
        mode=key.mode,
        name=str(key),
        signature=sig.describe(),
        fifths=sig.fifths,
        relative=str(key.relative()),
        parallel=str(key.parallel()),
    )


def _key_in(key: s.KeyIn | None) -> Key | None:
    return None if key is None else v.parse_key(key.tonic, key.mode)


def _note_out(note: Note, a4: float = 440.0, middle_c_octave: int = 4) -> s.NoteOut:
    return s.NoteOut(
        name=note.format(middle_c_octave=middle_c_octave),
        name_unicode=note.format(unicode=True, middle_c_octave=middle_c_octave),
        octave=note.octave,
        midi=note.midi,
        pitch_class=note.pitch_class,
        frequency=round(note.frequency(a4), 4),
    )


def _name_out(name: NoteName) -> s.NoteOut:
    return s.NoteOut(
        name=name.format(),
        name_unicode=name.format(unicode=True),
        octave=None,
        midi=None,
        pitch_class=name.pitch_class,
        frequency=None,
    )


def _enharmonics(pc: int, exclude: NoteName) -> list[str]:
    found = []
    for letter in "CDEFGAB":
        for acc in (-2, -1, 0, 1, 2):
            n = NoteName(letter, acc)
            if n.pitch_class == pc and n != exclude:
                found.append(n.format())
    return sorted(found, key=lambda t: (len(t), t))


def _chord_out(chord: Chord, style: SymbolStyle | None = None) -> s.ChordOut:
    inv = chord.inversion()
    tones = [
        s.ChordToneOut(name=str(t), interval=i.short, degree=i.number)
        for t, i in zip(chord.tones(), chord.type.formula, strict=True)
    ]
    return s.ChordOut(
        symbol=format_chord(chord, style) if style else format_chord(chord),
        root=str(chord.root),
        type_id=chord.type.id,
        quality=chord.type.name,
        bass=str(chord.bass_name),
        inversion=inv,
        inversion_name=None if inv is None else inversion_name(inv),
        tones=tones,
        pitch_classes=list(chord.pitch_classes()),
    )


def _interval_out(iv: Interval) -> s.IntervalOut:
    return s.IntervalOut(
        short=iv.short,
        long=iv.long,
        quality=iv.quality,
        number=iv.number,
        semitones=iv.semitones,
        whole_tones=iv.whole_tones,
        is_compound=iv.is_compound,
        simple=iv.simple().short,
        inverted=iv.inverted().short,
        description=iv.describe(),
    )


def _parse_chord(symbol: str) -> Chord:
    return parse_chord(symbol)


def _parse_chords(symbols: Sequence[str]) -> list[Chord]:
    out = []
    for i, text in enumerate(symbols):
        try:
            out.append(parse_chord(text))
        except TheoryError as exc:
            raise TheoryError(f"Chord {i + 1}: {exc.message}", code=exc.code) from exc
    return out


# ------------------------------------------------------------------ notes and intervals


def identify_note(req: s.NoteIdentifyRequest) -> s.NoteIdentifyResponse:
    mc = req.middle_c_octave
    cents: float | None = None
    if req.frequency is not None:
        note, cents = frequency_to_note(req.frequency, req.a4, req.prefer)
        kind: Any = "frequency"
        out = _note_out(note, req.a4, mc)
        name = note.name
        cents = round(cents, 2)
    elif req.midi is not None:
        note = note_from_midi(req.midi, req.prefer)
        kind, out, name = "midi", _note_out(note, req.a4, mc), note.name
    else:
        assert req.name is not None  # noqa: S101 - guaranteed by the request validator
        parsed = v.parse_note_or_name(req.name, middle_c_octave=mc)
        kind = "name"
        if isinstance(parsed, Note):
            out, name = _note_out(parsed, req.a4, mc), parsed.name
        else:
            out, name = _name_out(parsed), parsed
    return s.NoteIdentifyResponse(
        note=out,
        enharmonic_names=_enharmonics(name.pitch_class, name),
        cents_from_nearest=cents,
        input_kind=kind,
        a4=req.a4,
        middle_c_octave=mc,
    )


def interval(req: s.IntervalRequest) -> s.IntervalResponse:
    mc = req.middle_c_octave
    if req.lower is not None and req.upper is not None:
        a = v.parse_note_or_name(req.lower, middle_c_octave=mc)
        b = v.parse_note_or_name(req.upper, middle_c_octave=mc)
        if isinstance(a, Note) and isinstance(b, Note):
            iv = interval_between_notes(a, b)
            signed = signed_semitones(a, b)
            way = "up" if signed > 0 else "down" if signed < 0 else "unison"
            return s.IntervalResponse(
                interval=_interval_out(iv),
                lower=a.format(middle_c_octave=mc),
                upper=b.format(middle_c_octave=mc),
                direction=way,
                signed_semitones=signed,
            )
        if isinstance(a, NoteName) and isinstance(b, NoteName):
            return s.IntervalResponse(
                interval=_interval_out(interval_between_names(a, b)),
                lower=a.format(),
                upper=b.format(),
                direction="up",
            )
        raise TheoryError(
            "Give both notes with octave numbers (C4, G5) or both without (C, G).",
            code="mixed_note_forms",
        )
    assert req.root is not None and req.interval is not None  # noqa: S101
    iv = parse_interval_answer(req.interval)
    root = v.parse_note_or_name(req.root, middle_c_octave=mc)
    down = req.direction == "down"
    if isinstance(root, Note):
        reached = _note_out(transpose_note(root, iv, down=down), middle_c_octave=mc)
    else:
        reached = _name_out(transpose_name(root, iv, down=down))
    return s.IntervalResponse(
        interval=_interval_out(iv),
        lower=req.root,
        result=reached,
        direction=req.direction,
        signed_semitones=-iv.semitones if down else iv.semitones,
    )


# ------------------------------------------------------------------ scales


def _scale_info(d: ScaleDefinition) -> s.ScaleInfo:
    return s.ScaleInfo(
        builtin=d.id in default_registry().ids(),
        id=d.id,
        name=d.name,
        family=d.family,
        size=d.size,
        formula=[i.short for i in d.formula],
        aliases=list(d.aliases),
    )


def list_scales(registry: ScaleRegistry | None = None) -> s.ScaleListResponse:
    """Built-in scales, then any published administrator-defined ones."""
    return s.ScaleListResponse(
        scales=[_scale_info(d) for d in (registry or default_registry()).all()]
    )


def generate_scale(req: s.ScaleRequest, registry: ScaleRegistry | None = None) -> s.ScaleResponse:
    scale = make_scale(req.root, req.scale, registry)
    d = scale.definition
    key: s.KeyOut | None = None
    if d.id in ("major", "natural_minor"):
        k = Key(scale.root, "major" if d.id == "major" else "minor")
        key = _key_out(k)
    chords: list[s.DiatonicChordOut] = []
    if req.chord_size is not None:
        for c in diatonic_chords(scale, req.chord_size):
            chords.append(
                s.DiatonicChordOut(
                    degree=c.degree,
                    symbol=None if c.chord is None else format_chord(c.chord),
                    tones=[str(t) for t in c.tones],
                    intervals=[i.short for i in c.intervals],
                )
            )
    keyboard = (
        [_note_out(n) for n in scale.keyboard_notes(req.octave, include_octave=req.include_octave)]
        if req.octave is not None
        else []
    )
    fing = scale_fingering(scale, req.direction)
    return s.ScaleResponse(
        fingering=None
        if fing is None
        else s.FingeringOut(
            right_hand=list(fing.right_hand),
            left_hand=list(fing.left_hand),
            direction=fing.direction,
            note=fing.note,
        ),
        root=str(scale.root),
        scale=_scale_info(d),
        direction=req.direction,
        notes=[str(n) for n in scale.notes(req.direction)],
        degrees=[
            s.ScaleDegreeOut(number=g.number, note=str(g.note), interval=g.interval.short)
            for g in scale.degrees()
        ],
        keyboard=keyboard,
        key=key,
        diatonic_chords=chords,
    )


# ------------------------------------------------------------------ chords


def _style(style: s.SymbolStyleIn | None) -> SymbolStyle | None:
    return None if style is None else SymbolStyle(**style.model_dump())


def construct_chord(req: s.ChordConstructRequest) -> s.ChordConstructResponse:
    if req.symbol is not None:
        chord = parse_chord(req.symbol)
    else:
        assert req.root is not None and req.type is not None  # noqa: S101
        if req.type not in CHORD_TYPES:
            raise TheoryError(
                f"Unknown chord type {req.type!r}. See GET /api/v1/theory/chords/types.",
                code="unknown_chord_type",
            )
        chord = make_chord(req.root, req.type, req.bass)
    inversion = req.inversion
    if inversion is not None:
        chord = chord.with_inversion(inversion)
    notes = chord.notes(req.octave)
    return s.ChordConstructResponse(
        chord=_chord_out(chord, _style(req.symbol_style)),
        notes=[_note_out(n) for n in notes],
        midi_notes=[n.midi for n in notes],
        aliases=list(chord.type.aliases),
    )


def list_chord_types() -> s.ChordTypeListResponse:
    return s.ChordTypeListResponse(
        types=[
            s.ChordTypeOut(
                id=t.id,
                name=t.name,
                symbol=t.symbol,
                family=t.family,
                formula=[i.short for i in t.formula],
                aliases=list(t.aliases),
            )
            for t in CHORD_TYPES.values()
        ]
    )


def _candidate_out(c: ChordCandidate) -> s.CandidateOut:
    return s.CandidateOut(
        symbol=c.symbol,
        root=str(c.chord.root),
        type_id=c.chord.type.id,
        quality=c.chord.type.name,
        score=round(c.score, 4),
        required_tones=[str(n) for n in c.required_tones],
        detected_tones=[str(n) for n in c.detected_tones],
        missing_tones=[str(n) for n in c.missing_tones],
        extra_tones=[str(n) for n in c.extra_tones],
        bass=str(c.bass),
        inversion=c.inversion,
        inversion_name=None if c.inversion is None else inversion_name(c.inversion),
        rootless=c.rootless,
        added_tones=list(c.added_tones),
        altered_tones=list(c.altered_tones),
        enharmonic_symbol=c.enharmonic_symbol,
        assumptions=list(c.assumptions),
    )


def identify(req: s.ChordIdentifyRequest) -> s.ChordIdentifyResponse:
    v.check_count("notes", len(req.notes), v.MAX_NOTES)
    result = identify_chord(
        list(req.notes),
        bass=req.bass,
        key=_key_in(req.key),
        prefer=req.prefer,
        allow_rootless=req.allow_rootless,
        max_extra_tones=req.max_extra_tones,
        max_candidates=req.max_candidates,
        ambiguity_margin=req.ambiguity_margin,
    )
    return s.ChordIdentifyResponse(
        status=result.status,
        reason=result.reason,
        bass=None if result.bass is None else str(result.bass),
        pitch_classes=list(result.pitch_classes),
        candidates=[_candidate_out(c) for c in result.candidates],
    )


# ------------------------------------------------------------------ voicing configuration


def build_constraints(cfg: s.VoicingConfigIn) -> VoicingConstraints:
    overrides: dict[str, Any] = {}
    if cfg.constraints is not None:
        for name, value in cfg.constraints.model_dump().items():
            if value is None:
                continue
            if name in ("required_tones", "forbidden_tones"):
                value = frozenset(value)
            elif name == "tensions":
                value = tuple(value)
            elif name in ("lh_range", "rh_range"):
                value = (int(value[0]), int(value[1]))
            overrides[name] = value
    return constraints_for_skill(cfg.skill, **overrides)


def build_vl_config(vl: s.VoiceLeadingIn) -> VoiceLeadingConfig:
    known = {f.name for f in dataclasses.fields(VoiceLeadingWeights)}
    unknown = sorted(set(vl.weights) - known)
    if unknown:
        raise TheoryError(
            f"Unknown weight {unknown[0]!r}. Weights: {', '.join(sorted(known))}.",
            code="unknown_weight",
        )
    weights = dataclasses.replace(WEIGHT_PRESETS[vl.weight_preset], **vl.weights)
    return VoiceLeadingConfig(vl.style, weights, vl.strict_counterpoint)


def _voicing_in(vi: s.VoicingIn) -> Voicing:
    left, right = tuple(sorted(vi.left)), tuple(sorted(vi.right))
    return Voicing(left, right, vi.lh_style, vi.rh_style)


def _voicing_out(voicing: Voicing) -> s.VoicingOut:
    return s.VoicingOut(
        left=list(voicing.left),
        right=list(voicing.right),
        left_names=[note_from_midi(n).format() for n in voicing.left],
        right_names=[note_from_midi(n).format() for n in voicing.right],
        lh_style=voicing.lh_style,
        rh_style=voicing.rh_style,
        tensions=list(voicing.tensions),
        omitted=list(voicing.omitted),
        rh_inversion=voicing.rh_inversion,
    )


def _cost_out(cost: CostBreakdown) -> s.CostOut:
    return s.CostOut(total=cost.total, parts=cost.as_dict())


def _transition_out(t: TransitionEvaluation) -> s.TransitionOut:
    i = t.info
    return s.TransitionOut(
        movement=i.movement,
        largest_leap=i.largest_leap,
        common_tones=i.common_tones,
        bass_motion=i.bass_motion,
        parallel_fifths=i.parallel_fifths,
        parallel_octaves=i.parallel_octaves,
        leap_excess=t.leap_excess,
        cost=_cost_out(t.cost),
    )


def _chosen_out(item: ChosenVoicing) -> s.ChosenOut:
    return s.ChosenOut(
        chord=format_chord(item.chord),
        voicing=_voicing_out(item.voicing),
        static_cost=_cost_out(item.static),
        transition=None if item.transition is None else _transition_out(item.transition),
        cost=item.cost,
        explanation=list(item.explanation),
    )


def generate_voicing_options(req: s.VoicingsGenerateRequest) -> s.VoicingsGenerateResponse:
    chord = parse_chord(req.chord)
    c = build_constraints(req.config)
    cfg = build_vl_config(req.config.voice_leading)
    found = generate_voicings(chord, c, preset=req.config.preset)
    ranked: list[tuple[float, Voicing]] = [
        (static_cost(chord, x, c, cfg).total if req.rank else 0.0, x) for x in found
    ]
    if req.rank:
        ranked.sort(key=lambda t: (t[0], t[1].left, t[1].right, t[1].lh_style, t[1].rh_style))
    top = ranked[: req.limit]
    items = [
        s.ScoredVoicingOut(
            voicing=_voicing_out(x),
            static_cost=_cost_out(static_cost(chord, x, c, cfg)) if req.rank else None,
        )
        for _, x in top
    ]
    message = None
    if not found:
        message = (
            "No playable voicing satisfies these constraints. Try a wider hand span, a wider "
            "range, more notes per hand, or fewer required tones."
        )
    return s.VoicingsGenerateResponse(
        chord=_chord_out(chord),
        total_found=len(found),
        returned=len(items),
        ranking="static cost, lowest first" if req.rank else "generation order",
        voicings=items,
        message=message,
    )


def voice_sequence(req: s.VoicingSequenceRequest) -> s.VoicingSequenceResponse:
    v.check_count("chords", len(req.chords), v.MAX_VOICED_CHORDS)
    chords = _parse_chords(req.chords)
    for index in req.fixed:
        if not 0 <= index < len(chords):
            raise TheoryError(
                f"Pinned voicing index {index} is outside the {len(chords)} chords.",
                code="invalid_index",
            )
    voiced = voice_chords(
        chords,
        build_constraints(req.config),
        config=build_vl_config(req.config.voice_leading),
        preset=req.config.preset,
        fixed={i: _voicing_in(x) for i, x in req.fixed.items()},
        max_candidates=min(req.max_candidates, v.MAX_CANDIDATES),
        method=req.method,
    )
    return s.VoicingSequenceResponse(
        items=[_chosen_out(i) for i in voiced.items],
        total_cost=voiced.total_cost,
        method=voiced.method,
        relaxed_leap_limit=voiced.relaxed_leap_limit,
        warnings=list(voiced.warnings),
    )


def evaluate_voice_leading(req: s.VoiceLeadingEvaluateRequest) -> s.VoiceLeadingEvaluateResponse:
    chords = _parse_chords(req.chords)
    result = evaluate_sequence(
        chords,
        [_voicing_in(x) for x in req.voicings],
        build_constraints(req.config),
        build_vl_config(req.config.voice_leading),
    )
    return s.VoiceLeadingEvaluateResponse(
        total_cost=result.total_cost, items=[_chosen_out(i) for i in result.items]
    )


# ------------------------------------------------------------------ harmony, keys


def _numeral_out(n: RomanNumeral) -> s.NumeralOut:
    return s.NumeralOut(
        symbol=format_chord(n.chord),
        figure=n.figure,
        degree=n.degree,
        category=n.category,
        function=n.function,
        applied_to=n.applied_to,
        borrowed_from=n.borrowed_from,
        inversion=n.inversion,
        note=n.note,
        alternatives=list(n.alternatives),
    )


def _estimate_out(e: KeyEstimate) -> s.KeyEstimateOut:
    return s.KeyEstimateOut(
        candidates=[
            s.KeyCandidateOut(key=_key_out(c.key), score=round(c.score, 4)) for c in e.candidates
        ],
        reliable=e.reliable,
        ambiguous=e.ambiguous,
        warnings=list(e.warnings),
        method=e.method,
    )


def analyze_harmony(req: s.HarmonyAnalyzeRequest) -> s.HarmonyAnalyzeResponse:
    chords = _parse_chords(req.chords)
    if req.durations is not None and len(req.durations) != len(chords):
        raise TheoryError("Give one duration per chord.", code="length_mismatch")
    key = _key_in(req.key)
    source: Any = "provided" if key else None
    estimate: s.KeyEstimateOut | None = None
    warnings: list[str] = []
    if key is None:
        est = rank_keys_for_chords(chords, req.durations)
        estimate = _estimate_out(est)
        if est.reliable and est.best is not None:
            key, source = est.best.key, "estimated"
            if est.ambiguous:
                warnings.append(
                    f"The key is uncertain: {key} is one of several close fits, so the "
                    "numerals are relative to that guess."
                )
        else:
            warnings.append("Not enough evidence to name a key, so there are no Roman numerals.")
    numerals: list[s.NumeralOut] = []
    cadences: list[s.CadenceOut] = []
    phrases: list[s.PhraseOut] = []
    relationships = analyze_relationships(chords)
    if key is not None:
        analysed = analyze_progression(chords, key)
        numerals = [_numeral_out(n) for n in analysed]
        found = find_cadences(analysed)
        cadences = [s.CadenceOut(start=c.start, end=c.end, kind=c.kind, note=c.note) for c in found]
        relationships = analyze_relationships(chords, analysed)
        phrases = [
            s.PhraseOut(
                index=p.index, start=p.start, end=p.end, figures=list(p.figures),
                function_path=list(p.function_path), cadence=p.cadence, character=p.character,
                short=p.short, duration_beats=p.duration_beats, text=p.text,
            )
            for p in segment_phrases(
                analysed, found, durations=req.durations, min_chords=req.min_phrase_chords
            )
        ]  # fmt: skip
    modulations = [
        s.ModulationOut(index=m.index, from_key=str(m.from_key), to_key=str(m.to_key), note=m.note)
        for m in detect_modulations(chords)
    ]
    return s.HarmonyAnalyzeResponse(
        key=None if key is None else _key_out(key),
        key_source=source,
        key_estimate=estimate,
        numerals=numerals,
        cadences=cadences,
        modulation_candidates=modulations,
        relationships=[
            s.RelationshipOut(
                start=r.start, end=r.end, common_tones=[str(n) for n in r.common_tones],
                root_semitones=r.root_semitones, root_motion=r.root_motion, kinds=list(r.kinds),
                transform=r.transform, voice_leading_distance=r.voice_leading_distance,
                unmatched_tones=r.unmatched_tones, non_diatonic=r.non_diatonic, note=r.note,
            )
            for r in relationships
        ],
        phrases=phrases,
        phrase_note=PHRASE_LIMITATION if phrases else None,
        warnings=warnings,
    )  # fmt: skip


def estimate_key_request(req: s.KeyEstimateRequest) -> s.KeyEstimateOut:
    if req.pitch_class_weights is not None:
        return _estimate_out(estimate_key(req.pitch_class_weights, top=req.top))
    assert req.chords is not None  # noqa: S101
    chords = _parse_chords(req.chords)
    if req.durations is not None and len(req.durations) != len(chords):
        raise TheoryError("Give one duration per chord.", code="length_mismatch")
    return _estimate_out(rank_keys_for_chords(chords, req.durations, top=req.top))


# ------------------------------------------------------------------ progressions


def _issue_out(i: Any) -> s.IssueOut:
    return s.IssueOut(severity=i.severity, code=i.code, message=i.message, index=i.index)


def _progression_response(
    prog: Progression, voiced_items: list[ChosenVoicing] | None, total: float | None,
    voiced_warnings: Sequence[str] = (),
) -> s.ProgressionResponse:  # fmt: skip
    report = validate_progression(prog)
    notes = [f"[{i.code}] {i.message}" for i in report.issues]
    return s.ProgressionResponse(
        progression=progression_to_dict(prog),
        chord_details=[_chord_out(c.chord) for c in prog.chords],
        voicing=None if voiced_items is None else [_chosen_out(i) for i in voiced_items],
        voicing_total_cost=total,
        warnings=[*voiced_warnings, *notes],
    )


def generate_progression_request(req: s.ProgressionGenerateRequest) -> s.ProgressionResponse:
    key = v.parse_key(req.key.tonic, req.key.mode)
    if req.template_id is not None:
        prog = realize(
            default_library().get(req.template_id),
            key,
            req.vocabulary,
            tempo=req.tempo,
            difficulty=req.difficulty,
        )
        if req.styles:
            prog = dataclasses.replace(prog, styles=tuple(req.styles))
    else:
        assert req.chords is not None  # noqa: S101
        v.check_count("chords", len(req.chords), v.MAX_PROGRESSION_CHORDS)
        fields: dict[str, Any] = {"styles": tuple(req.styles)}
        if req.tempo is not None:
            fields["tempo"] = req.tempo
        if req.time_signature is not None:
            fields["time_signature"] = req.time_signature
        if req.difficulty is not None:
            fields["difficulty"] = req.difficulty
        prog = make_progression(
            req.name or f"Custom progression in {key}",
            key,
            _parse_chords([c.symbol for c in req.chords]),
            beats=[c.beats for c in req.chords],
            **fields,
        )
    if req.name is not None and req.template_id is not None:
        prog = dataclasses.replace(prog, name=req.name)
    if req.voicing is None:
        return _progression_response(prog, None, None)
    v.check_count("chords", len(prog.chords), v.MAX_VOICED_CHORDS)
    voiced_prog, voiced = voice_progression(
        prog,
        build_constraints(req.voicing),
        build_vl_config(req.voicing.voice_leading),
        preset=req.voicing.preset,
    )
    return _progression_response(
        voiced_prog, list(voiced.items), voiced.total_cost, voiced.warnings
    )


def _load_progression(data: dict[str, Any]) -> Progression:
    chords = data.get("chords")
    if isinstance(chords, list):
        v.check_count("chords", len(chords), v.MAX_PROGRESSION_CHORDS)
    return progression_from_dict(migrate_progression_data(data))


def transpose(req: s.ProgressionTransposeRequest) -> s.ProgressionTransposeResponse:
    prog = _load_progression(req.progression)
    target = parse_note_name(req.target)
    constraints = build_constraints(req.voicing) if req.voicing else None
    config = build_vl_config(req.voicing.voice_leading) if req.voicing else None
    if req.on_unplayable == "revoice":
        v.check_count("chords", len(prog.chords), v.MAX_VOICED_CHORDS)
    result = transpose_progression(
        prog, target, constraints=constraints, config=config, on_unplayable=req.on_unplayable
    )
    return s.ProgressionTransposeResponse(
        progression=progression_to_dict(result.progression),
        shift_semitones=result.shift_semitones,
        revoiced=result.revoiced,
        warnings=list(result.warnings),
    )


def validate_progression_request(
    req: s.ProgressionValidateRequest,
) -> s.ProgressionValidateResponse:
    prog = _load_progression(req.progression)
    if req.deep:
        v.check_count("chords", len(prog.chords), v.MAX_VOICED_CHORDS)
    report: ValidationReport = validate_progression(
        prog,
        constraints=build_constraints(req.voicing) if req.voicing else None,
        strict_harmony=req.strict_harmony,
        publication=req.publication,
        deep=req.deep,
    )
    return s.ProgressionValidateResponse(
        ok=report.ok,
        errors=[_issue_out(i) for i in report.errors],
        warnings=[_issue_out(i) for i in report.warnings],
    )


def list_templates(
    style: str | None, difficulty: str | None, mode: str | None
) -> s.TemplateListResponse:
    if difficulty is not None and difficulty not in DIFFICULTIES:
        raise TheoryError(
            f"Difficulty must be one of {', '.join(DIFFICULTIES)}.", code="unknown_difficulty"
        )
    if mode is not None and mode not in ("major", "minor"):
        raise TheoryError("Mode must be 'major' or 'minor'.", code="unknown_mode")
    found = default_library().search(style=style, difficulty=difficulty, mode=mode)
    return s.TemplateListResponse(
        templates=[
            s.TemplateOut(
                id=t.id,
                name=t.name,
                mode=t.mode,
                difficulty=t.difficulty,
                styles=list(t.styles),
                explanation=t.explanation,
                practice=t.practice,
                time_signature=t.time_signature,
                numerals_triads=[c.triads for c in t.chords],
                numerals_sevenths=[c.sevenths for c in t.chords],
                beats=[c.beats for c in t.chords],
            )
            for t in found
        ]
    )


# ------------------------------------------------------------------ MIDI


def analyze_midi(req: s.MidiAnalyzeRequest) -> s.MidiAnalyzeResponse:
    v.check_count("MIDI events", len(req.events), v.MAX_MIDI_EVENTS)
    tempo = TempoMap(req.ppq, [TempoChange(t.tick, t.bpm) for t in req.tempo_changes])
    extraction = notes_from_events(
        [MidiEvent(e.tick, e.kind, e.note, e.velocity, e.channel, e.track) for e in req.events],
        tempo,
    )
    notes: list[NoteEvent] = list(extraction.notes)
    if req.track_states is not None:
        states = [TrackState(t.track, t.name, t.hand, t.muted, t.solo) for t in req.track_states]
        notes = filter_audible(notes, states)
    assignment = assign_hands(notes, split_pitch=req.split_pitch)
    if req.hand_edits:
        assignment = assignment.with_user_edits(req.hand_edits)
    analysis = analyze_notes(
        notes,
        time_signatures=[
            TimeSignatureChange(t.tick, t.numerator, t.denominator) for t in req.time_signatures
        ],
        key=_key_in(req.key),
        grid=req.grid,
        prefer=req.prefer,
        max_candidates=req.max_candidates,
        min_note_fraction=req.min_note_fraction,
        ppq=req.ppq,
    )
    segments = [
        s.MidiSegmentOut(
            start_beat=seg.start_beat,
            end_beat=seg.end_beat,
            start_sec=seg.start_sec,
            end_sec=seg.end_sec,
            status=seg.status,
            reason=seg.reason,
            bass=None if seg.bass is None else str(seg.bass),
            pitches=list(seg.pitches),
            candidates=[_candidate_out(c) for c in seg.candidates],
            numeral=None if seg.numeral is None else _numeral_out(seg.numeral),
            warnings=list(seg.warnings),
        )
        for seg in analysis.segments
    ]
    note_list = None
    if req.include_notes:
        note_list = [
            s.MidiNoteOut(
                id=n.id,
                midi=n.midi,
                name=note_from_midi(n.midi, req.prefer).format(),
                velocity=n.velocity,
                track=n.track,
                channel=n.channel,
                start_beat=n.start_beat,
                end_beat=n.end_beat,
                start_sec=n.start_sec,
                end_sec=n.end_sec,
                duration_beats=n.duration_beats,
                hand=assignment.hands.get(n.id),
                hand_source=assignment.source.get(n.id),
            )
            for n in notes
        ]
    return s.MidiAnalyzeResponse(
        segments=segments,
        key=None if analysis.key is None else _key_out(analysis.key),
        key_source=analysis.key_source,
        key_estimate=_estimate_out(analysis.key_estimate),
        note_count=analysis.note_count,
        duration_beats=analysis.duration_beats,
        notes=note_list,
        warnings=[*extraction.warnings, *analysis.warnings],
    )


# ------------------------------------------------------------------ audio interpretation


def _hypothesis_out(h: ChordHypothesis) -> s.HypothesisOut:
    return s.HypothesisOut(
        origin=h.origin,
        start=h.start,
        end=h.end,
        status=h.status,
        symbol=None if h.chord is None else format_chord(h.chord),
        raw_label=h.raw_label,
        alternatives=[
            s.AlternativeOut(
                label=a.label,
                symbol=None if a.chord is None else format_chord(a.chord),
                source=a.source,
                model_score=a.model_score,
            )
            for a in h.alternatives
        ],
        model_score=h.model_score,
        confidence=h.confidence,
        calibration=h.calibration,
        bass=None if h.bass is None else str(h.bass),
        pitch_classes=None if h.pitch_classes is None else list(h.pitch_classes),
        numeral=None if h.numeral is None else _numeral_out(h.numeral),
        warnings=list(h.warnings),
    )


def _apply_correction(ca: CorrectedAnalysis, c: s.CorrectionIn) -> CorrectedAnalysis:
    # The request validator guarantees the fields each operation needs.
    if c.op == "relabel":
        return relabel(ca, c.index, c.label)  # type: ignore[arg-type]
    if c.op == "retime":
        return retime(ca, c.index, c.start, c.end)  # type: ignore[arg-type]
    if c.op == "add":
        return add_region(ca, c.start, c.end, c.label)  # type: ignore[arg-type]
    return delete_region(ca, c.index)  # type: ignore[arg-type]


def interpret_audio(req: s.AudioInterpretRequest) -> s.AudioInterpretResponse:
    v.check_count("audio regions", len(req.regions), v.MAX_AUDIO_REGIONS)
    v.check_count("corrections", len(req.corrections), v.MAX_CORRECTIONS, minimum=0)
    regions = [
        AudioRegion(
            r.start, r.end, r.label, r.scores, r.bass_pc, r.pitch_classes, r.probability,
            r.calibration,
        )
        for r in req.regions
    ]  # fmt: skip
    interp = interpret_regions(
        regions,
        key=_key_in(req.key),
        min_duration=req.min_duration,
        score_margin=req.score_margin,
        prefer=req.prefer,
    )
    current: tuple[ChordHypothesis, ...] = interp.hypotheses
    log: list[s.CorrectionOut] = []
    key = interp.key
    if req.corrections:
        ca = start_corrections(interp)
        for c in req.corrections:
            ca = _apply_correction(ca, c)
        current, key = ca.current, ca.key
        log = [
            s.CorrectionOut(
                kind=c.kind,
                index=c.index,
                before=None if c.before is None else _hypothesis_out(c.before),
                after=None if c.after is None else _hypothesis_out(c.after),
            )
            for c in ca.corrections
        ]
    return s.AudioInterpretResponse(
        hypotheses=[_hypothesis_out(h) for h in current],
        original=[_hypothesis_out(h) for h in interp.hypotheses] if req.corrections else None,
        corrections=log,
        key=None if key is None else _key_out(key),
        key_source=interp.key_source,
        key_estimate=None if interp.key_estimate is None else _estimate_out(interp.key_estimate),
        warnings=list(interp.warnings),
    )


# ------------------------------------------------------------------ exercises


def list_exercise_kinds() -> s.ExerciseKindListResponse:
    return s.ExerciseKindListResponse(
        difficulties=list(DIFFICULTIES),
        kinds=[
            s.ExerciseKindOut(
                kind=k.kind,
                title=k.title,
                topic=k.topic,
                objective=k.objective,
                prerequisites=list(k.prerequisites),
                ear_training=k.ear_training,
            )
            for k in KINDS.values()
        ],
    )


def make_exercises(req: s.ExerciseGenerateRequest) -> s.ExerciseSetResponse:
    if req.count == 1:
        items = [generate_exercise(req.kind, req.difficulty, req.seed)]
    else:
        base = req.seed if req.seed is not None else random.SystemRandom().randrange(2**31 - 100)
        items = generate_set(req.kind, req.difficulty, req.count, base)
    return s.ExerciseSetResponse(
        exercises=[s.ExerciseOut.model_validate(dataclasses.asdict(e)) for e in items]
    )


def grade_exercise(req: s.ExerciseValidateRequest) -> s.ExerciseGradeResponse:
    grade = validate_answer(req.exercise_id, req.answer)
    return s.ExerciseGradeResponse.model_validate(dataclasses.asdict(grade))
