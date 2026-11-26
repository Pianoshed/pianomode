import math

import pytest

from music_theory.audio_interpretation import (
    AudioLabelError,
    AudioRegion,
    ChordHypothesis,
    RegionError,
    add_region,
    delete_region,
    interpret_regions,
    parse_audio_label,
    relabel,
    retime,
    start_corrections,
)
from music_theory.errors import TheoryError
from music_theory.keys import Key
from music_theory.midi_analysis import ChordSegment
from music_theory.notes import parse_note_name as N

C = Key(N("C"))


def sym(label: str) -> str | None:
    chord = parse_audio_label(label)
    return None if chord is None else str(chord)


@pytest.mark.parametrize(
    ("label", "expected"),
    [
        ("C:maj", "C"), ("C#:min7", "C#m7"), ("Bb:maj/3", "Bb/D"), ("G:7/b7", "G7/F"),
        ("D:hdim7", "Dm7b5"), ("A:min/5", "Am/E"), ("F:maj7", "Fmaj7"), ("E:dim7", "Edim7"),
        ("G:sus4", "Gsus4"), ("C:minmaj7", "CmMaj7"), ("C:5", "C5"), ("Dm7/C", "Dm7/C"),
        ("F#m7b5", "F#m7b5"), ("N", None), ("  C:maj  ", "C"),
    ],
)  # fmt: skip
def test_chord_labels_from_audio_models_are_parsed(label: str, expected: str | None) -> None:
    assert sym(label) == expected


@pytest.mark.parametrize(
    "bad",
    ["", "  ", "X", "C:wobble", "C:maj/99", "H:maj", "Cmaj", "C:", ":maj", "C:maj(9)", "banana"],
)
def test_unrecognised_labels_are_errors_never_remapped(bad: str) -> None:
    with pytest.raises(AudioLabelError) as err:
        parse_audio_label(bad)
    assert err.value.code == "unrecognised_chord_label"


def region(start: float, end: float, label: str, **kw) -> AudioRegion:  # type: ignore[no-untyped-def]
    return AudioRegion(start, end, label, **kw)


def test_basic_interpretation_marks_everything_as_an_estimate() -> None:
    regions = [
        region(
            0, 2, "C:maj", scores={"C:maj": 0.9, "C:maj7": 0.2}, pitch_classes=[0, 4, 7], bass_pc=0
        ),
        region(2, 4, "A:min7", scores={"A:min7": 0.8, "C:maj": 0.1}),
        region(4, 6, "F:maj", scores={"F:maj": 0.7, "D:min": 0.2}),
        region(6, 8, "G:7", scores={"G:7": 0.9, "G:maj": 0.1}),
    ]
    out = interpret_regions(regions)
    assert [str(h.chord) for h in out.hypotheses] == ["C", "Am7", "F", "G7"]
    assert all(h.origin == "audio" and h.status == "estimated" for h in out.hypotheses)
    assert all(h.confidence is None for h in out.hypotheses)  # nothing was calibrated
    assert out.hypotheses[0].model_score == 0.9  # the raw score is reported as a raw score
    assert [a.label for a in out.hypotheses[0].alternatives] == ["C:maj7"]
    assert out.key is not None and out.key_source == "estimated"
    assert out.hypotheses[3].numeral is not None and out.hypotheses[3].numeral.figure in {
        "V7",
        "V7/V",
    }


def test_audio_hypotheses_and_midi_chords_are_different_kinds_of_thing() -> None:
    assert ChordHypothesis.__name__ != ChordSegment.__name__
    hyp = interpret_regions([region(0, 1, "C:maj")]).hypotheses[0]
    assert hyp.origin == "audio"
    seg = ChordSegment(0, 1, 0, 1, "silence", (), None, None, (), 1)
    assert seg.origin == "midi"


def test_probabilities_are_only_confidence_when_a_calibration_is_named() -> None:
    plain = interpret_regions([region(0, 1, "C:maj", probability=0.93)]).hypotheses[0]
    assert plain.confidence is None and plain.model_score == 0.93
    assert any("without a named calibration" in w for w in plain.warnings)
    calibrated = interpret_regions(
        [region(0, 1, "C:maj", probability=0.93, calibration="isotonic-v2")]
    ).hypotheses[0]
    assert calibrated.confidence == 0.93 and calibrated.calibration == "isotonic-v2"
    silly = interpret_regions([region(0, 1, "C:maj", probability=1.7, calibration="x")]).hypotheses[
        0
    ]
    assert silly.confidence is None and any(
        "without a named calibration" in w for w in silly.warnings
    )


def test_close_scores_and_inconsistent_labels_are_flagged_as_ambiguous() -> None:
    close = interpret_regions(
        [region(0, 2, "C:maj", scores={"C:maj": 0.80, "A:min": 0.78})]
    ).hypotheses[0]
    assert close.status == "ambiguous" and "nearly equal" in close.warnings[0]
    clear = interpret_regions(
        [region(0, 2, "C:maj", scores={"C:maj": 0.80, "A:min": 0.30})]
    ).hypotheses[0]
    assert clear.status == "estimated" and not clear.warnings
    wrong = interpret_regions(
        [region(0, 2, "C:maj", scores={"C:maj": 0.4, "A:min": 0.9})]
    ).hypotheses[0]
    assert wrong.status == "ambiguous" and "not the highest-scoring" in wrong.warnings[0]
    junk = interpret_regions(
        [region(0, 2, "C:maj", scores={"C:maj": 0.9, "weird": 0.1})]
    ).hypotheses[0]
    assert any("not understood" in w for w in junk.warnings) and junk.status == "estimated"
    assert not any(a.label == "weird" for a in junk.alternatives)


def test_detected_pitches_are_checked_against_the_label() -> None:
    ok = interpret_regions([region(0, 2, "C:maj", pitch_classes=[0, 4, 7], bass_pc=0)]).hypotheses[
        0
    ]
    assert ok.status == "estimated" and not ok.warnings
    disagree = interpret_regions(
        [region(0, 2, "C:maj", pitch_classes=[9, 0, 4], bass_pc=9)]
    ).hypotheses[0]
    assert disagree.status == "ambiguous"
    assert any("suggest Am rather than C" in w for w in disagree.warnings)
    assert any(a.source == "pitch_evidence" and str(a.chord) == "Am" for a in disagree.alternatives)
    both = interpret_regions(
        [region(0, 2, "C:maj7", pitch_classes=[0, 4, 7, 9], bass_pc=0)]
    ).hypotheses[0]
    assert both.status == "ambiguous" and any("Am" in a.label for a in both.alternatives if a.label)
    thin = interpret_regions([region(0, 2, "C:maj", pitch_classes=[0])]).hypotheses[0]
    assert any("lack the chord's third" in w for w in thin.warnings)
    assert any("too sparse" in w for w in thin.warnings)


def test_bass_estimates_suggest_inversions_and_slash_chords() -> None:
    inv = interpret_regions([region(0, 2, "C:maj", bass_pc=4, pitch_classes=[0, 4, 7])]).hypotheses[
        0
    ]
    assert str(inv.bass) == "E" and any("inversion" in w for w in inv.warnings)
    slash = interpret_regions(
        [region(0, 2, "C:maj", bass_pc=2, pitch_classes=[0, 4, 7, 2])]
    ).hypotheses[0]
    assert any("slash chord" in w for w in slash.warnings)
    marked = interpret_regions(
        [region(0, 2, "C:maj/3", bass_pc=4, pitch_classes=[0, 4, 7])]
    ).hypotheses[0]
    assert str(marked.chord) == "C/E" and not any("inversion" in w for w in marked.warnings)


def test_weak_evidence_is_called_out() -> None:
    short = interpret_regions([region(0, 0.1, "C:maj", scores={"C:maj": 0.9})]).hypotheses[0]
    assert any("Very short region" in w for w in short.warnings)
    bare = interpret_regions([region(0, 2, "C:maj")]).hypotheses[0]
    assert any("Only a label was provided" in w for w in bare.warnings)
    none = interpret_regions([region(0, 2, "N")]).hypotheses[0]
    assert none.status == "no_chord" and none.chord is None and not none.warnings
    unknown = interpret_regions([region(0, 2, "Q:foo")]).hypotheses[0]
    assert (
        unknown.status == "unrecognised_label"
        and unknown.chord is None
        and unknown.raw_label == "Q:foo"
    )
    assert unknown.warnings


def test_key_context_and_numerals() -> None:
    labels = ["A:min", "F:maj", "C:maj", "G:maj"]
    regions = [region(2 * i, 2 * i + 2, lab) for i, lab in enumerate(labels)]
    out = interpret_regions(regions)
    assert out.key is not None and str(out.key.tonic) in {"A", "C"} and out.key_estimate is not None
    given = interpret_regions(regions, key=C)
    assert given.key_source == "provided"
    assert [h.numeral.figure for h in given.hypotheses if h.numeral] == ["vi", "IV", "I", "V"]
    few = interpret_regions(regions[:2])
    assert few.key is None and all(h.numeral is None for h in few.hypotheses)
    assert any("Too few chords" in w for w in few.warnings)
    assert interpret_regions([]).hypotheses == ()


def test_results_are_deterministic() -> None:
    regions = [
        region(0, 2, "C:maj", scores={"C:maj": 0.8, "A:min": 0.78}, pitch_classes=[0, 4, 7]),
        region(2, 4, "G:7"),
    ]
    assert interpret_regions(regions) == interpret_regions(regions)


@pytest.mark.parametrize(
    "regions",
    [
        [region(-1, 1, "C:maj")], [region(1, 1, "C:maj")], [region(2, 1, "C:maj")],
        [region(0, math.nan, "C:maj")], [region(0, 2, "C:maj"), region(1, 3, "G:maj")],
        [region(2, 3, "C:maj"), region(0, 1, "G:maj")],
    ],
)  # fmt: skip
def test_regions_must_be_valid_and_in_order(regions: list[AudioRegion]) -> None:
    with pytest.raises(RegionError) as err:
        interpret_regions(regions)
    assert err.value.code == "invalid_regions"


def test_non_finite_scores_and_bad_bass_are_rejected() -> None:
    with pytest.raises(RegionError):
        interpret_regions([region(0, 1, "C:maj", scores={"C:maj": math.inf})])
    with pytest.raises(RegionError):
        interpret_regions([region(0, 1, "C:maj", bass_pc=12)])


# ------------------------------------------------------------ corrections


def fresh():  # type: ignore[no-untyped-def]
    regions = [
        region(0, 2, "C:maj", scores={"C:maj": 0.8, "A:min": 0.78}),
        region(2, 4, "F:maj"),
        region(4, 6, "G:maj"),
        region(6, 8, "C:maj"),
    ]
    return start_corrections(interpret_regions(regions, key=C))


def test_the_original_estimate_is_preserved_when_a_chord_is_corrected() -> None:
    ca = fresh()
    fixed = relabel(ca, 0, "A:min")
    assert str(fixed.current[0].chord) == "Am" and fixed.current[0].origin == "user"
    assert fixed.current[0].status == "user_set" and fixed.current[0].alternatives == ()
    assert fixed.current[0].numeral is not None and fixed.current[0].numeral.figure == "vi"
    assert fixed.original == ca.original and str(fixed.original[0].chord) == "C"  # untouched
    assert ca.current[0].origin == "audio"  # and the previous state is unchanged
    c = fixed.corrections[0]
    assert (c.kind, c.index) == ("relabel", 0)
    assert (
        c.before is not None
        and str(c.before.chord) == "C"
        and c.after is not None
        and str(c.after.chord) == "Am"
    )
    assert [str(h.chord) for h in relabel(fixed, 1, "N").current][1:2] == ["None"]


def test_corrections_pile_up_as_a_reviewable_history() -> None:
    ca = relabel(fresh(), 1, "Dm7")
    ca = retime(ca, 2, 4.5, 6)
    ca = add_region(ca, 8, 10, "F:maj")
    ca = delete_region(ca, 0)
    assert [c.kind for c in ca.corrections] == ["relabel", "retime", "add", "delete"]
    assert [str(h.chord) for h in ca.current] == ["Dm7", "G", "C", "F"]
    assert len(ca.original) == 4
    assert ca.corrections[2].index == 4 and ca.corrections[2].before is None


def test_invalid_corrections_are_rejected_and_change_nothing() -> None:
    ca = fresh()
    for bad in (
        lambda: relabel(ca, 0, "nonsense"),
        lambda: relabel(ca, 9, "C:maj"),
        lambda: retime(ca, 1, 1.0, 3.0),  # overlaps the first region
        lambda: retime(ca, 1, 3.0, 2.0),
        lambda: retime(ca, 1, math.nan, 3.0),
        lambda: add_region(ca, 1, 3, "C:maj"),
        lambda: add_region(ca, 8, 9, "Wobble"),
        lambda: delete_region(ca, 4),
    ):
        with pytest.raises(TheoryError):
            bad()
    assert ca == fresh()


def test_corrections_can_insert_in_the_gaps_in_time_order() -> None:
    regions = [region(0, 2, "C:maj"), region(4, 6, "G:maj")]
    ca = start_corrections(interpret_regions(regions, key=C))
    ca = add_region(ca, 2, 4, "F:maj")
    assert [(h.start, str(h.chord)) for h in ca.current] == [(0, "C"), (2, "F"), (4, "G")]
