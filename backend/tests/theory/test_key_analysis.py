import math

import pytest

from music_theory.chord_symbols import parse_chord
from music_theory.errors import TheoryError
from music_theory.key_analysis import (
    detect_modulations,
    estimate_key,
    rank_keys_for_chords,
    weights_from_chords,
    weights_from_midi,
)


def chords(text: str):  # type: ignore[no-untyped-def]
    return [parse_chord(s) for s in text.split()]


C_SCALE = [1, 0, 1, 0, 1, 1, 0, 1, 0, 1, 0, 1]


def test_c_major_scale_is_c_major_but_flagged_as_ambiguous_with_a_minor() -> None:
    est = estimate_key(C_SCALE)
    assert str(est.candidates[0].key) == "C major"
    assert str(est.candidates[1].key) == "A minor"
    assert est.ambiguous and est.reliable
    assert any("relative key" in w for w in est.warnings)


def test_emphasising_the_tonic_resolves_the_ambiguity() -> None:
    est = estimate_key([3, 0, 1, 0, 2, 1, 0, 3, 0, 1, 0, 1])
    assert str(est.candidates[0].key) == "C major" and not est.ambiguous
    minor = estimate_key([1, 0, 1, 0, 0, 1, 0, 2, 0, 3, 0, 1][::-1][::-1])
    assert minor.candidates  # smoke: any valid weights give a ranked list


def test_a_minor_melody() -> None:
    # A minor scale with harmonic leading tone, tonic and dominant weighted
    w = weights_from_midi([(57, 3), (59, 1), (60, 2), (62, 1), (64, 2), (65, 1), (68, 1), (69, 2)])
    est = estimate_key(w)
    assert str(est.candidates[0].key) == "A minor"


def test_scores_are_sorted_bounded_correlations_not_probabilities() -> None:
    est = estimate_key(C_SCALE, top=24)
    scores = [c.score for c in est.candidates]
    assert scores == sorted(scores, reverse=True) and len(scores) == 24
    assert all(-1.0 <= s <= 1.0 for s in scores)
    assert not math.isclose(sum(scores), 1.0)


def test_too_little_evidence_is_flagged() -> None:
    one = estimate_key([1] + [0] * 11)
    assert not one.reliable and any("Fewer than three" in w for w in one.warnings)
    triad = estimate_key([1, 0, 0, 0, 1, 0, 0, 1, 0, 0, 0, 0])
    assert triad.reliable  # three pitch classes is the minimum we accept
    empty = estimate_key([0] * 12)
    assert not empty.reliable and not empty.candidates and empty.best is None
    flat = estimate_key([1] * 12)
    assert not flat.candidates  # no information: a chromatic cluster says nothing about key


@pytest.mark.parametrize("bad", [[1] * 11, [1] * 13, [-1] + [0] * 11, [math.nan] + [0] * 11])
def test_invalid_weights(bad: list[float]) -> None:
    with pytest.raises(TheoryError):
        estimate_key(bad)


def test_weights_helpers() -> None:
    assert weights_from_midi([(60, 2.0), (72, 1.0), (64, 1.0)])[0] == 3.0
    w = weights_from_chords(chords("C"), [2.0])
    assert w[0] == 4.0 and w[4] == 2.0 and w[7] == 2.0  # root counts double
    with pytest.raises(TheoryError):
        weights_from_midi([(60, -1.0)])
    with pytest.raises(TheoryError):
        weights_from_chords(chords("C G"), [1.0])


def test_chord_based_ranking() -> None:
    est = rank_keys_for_chords(chords("C Am F G7 C"))
    assert str(est.best.key) == "C major" and not est.ambiguous  # type: ignore[union-attr]
    minor = rank_keys_for_chords(chords("Am F C G"))
    assert str(minor.best.key) == "A minor"  # type: ignore[union-attr]
    assert "C major" in [str(c.key) for c in minor.candidates[:2]]  # relative key stays visible
    assert minor.ambiguous
    assert not rank_keys_for_chords([]).candidates


def test_modulation_candidates() -> None:
    found = detect_modulations(chords("C F G7 C D G A7 D"))
    assert [(str(m.from_key), str(m.to_key)) for m in found] == [("C major", "D major")]
    assert 3 <= found[0].index <= 5 and "approximate" in found[0].note
    assert detect_modulations(chords("C F G7 C F G7 C")) == []
    assert detect_modulations(chords("C G")) == []
    with pytest.raises(TheoryError):
        detect_modulations(chords("C G Am F C"), window=2)
