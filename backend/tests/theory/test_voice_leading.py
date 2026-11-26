import itertools
import math
import time

import pytest

from music_theory.chord_symbols import parse_chord as P
from music_theory.errors import TheoryError
from music_theory.voice_leading import (
    STYLE_PROFILES,
    WEIGHT_PRESETS,
    VoiceLeadingConfig,
    _candidates,
    _transition_total,
    config_for,
    evaluate_sequence,
    evaluate_transition,
    static_cost,
    voice_chords,
)
from music_theory.voicings import (
    Voicing,
    VoicingConstraints,
    constraints_for_skill,
    generate_voicings,
    playability_issues,
)


def v(left: tuple[int, ...] = (), right: tuple[int, ...] = ()) -> Voicing:
    return Voicing(left, right, "x", "y")


def chords(text: str):  # type: ignore[no-untyped-def]
    return [P(s) for s in text.split()]


II_V_I = "Dm7 G7 Cmaj7"


def test_transition_measures_motion_leaps_and_held_notes() -> None:
    ev = evaluate_transition(v(right=(60, 64, 67)), v(right=(60, 65, 69)))
    i = ev.info
    assert (i.movement, i.largest_leap, i.common_tones, i.parallel_fifths) == (3, 2, 1, 0)
    same = evaluate_transition(v(right=(60, 64, 67)), v(right=(60, 64, 67)))
    assert same.info.movement == 0 and same.info.common_tones == 3
    assert same.cost.total < ev.cost.total  # holding everything is the smoothest possible


def test_voices_that_appear_or_vanish_cost_something() -> None:
    ev = evaluate_transition(v(right=(60, 64)), v(right=(60, 64, 67)))
    assert ev.info.movement == 4  # the new voice is charged a fixed penalty
    assert evaluate_transition(v(right=(60, 64, 67)), v(right=(60, 64))).info.movement == 4


def test_bass_motion_is_measured_on_the_lowest_note() -> None:
    ev = evaluate_transition(v((36,), (60,)), v((43,), (60,)))
    assert ev.info.bass_motion == 7


def test_parallel_fifths_and_octaves_are_detected_but_only_penalised_where_unwanted() -> None:
    fifths = evaluate_transition(v((48, 55)), v((50, 57)))
    assert fifths.info.parallel_fifths == 1 and fifths.info.parallel_octaves == 0
    octaves = evaluate_transition(v((48, 60)), v((50, 62)))
    assert octaves.info.parallel_octaves == 1
    contrary = evaluate_transition(v((48, 55)), v((50, 53)))
    assert contrary.info.parallel_fifths == 0
    held = evaluate_transition(v((48, 55)), v((48, 57)))
    assert held.info.parallel_fifths == 0  # one voice stays: not parallel
    strict = VoiceLeadingConfig("jazz", strict_counterpoint=True)
    jazz = VoiceLeadingConfig("jazz")
    assert (
        evaluate_transition(v((48, 55)), v((50, 57)), cfg=strict).cost.as_dict()["parallels"]
        == 10.0
    )
    assert (
        evaluate_transition(v((48, 55)), v((50, 57)), cfg=jazz).cost.as_dict()["parallels"] == 0.0
    )
    pop = VoiceLeadingConfig("pop")
    assert (
        0 < evaluate_transition(v((48, 55)), v((50, 57)), cfg=pop).cost.as_dict()["parallels"] < 10
    )


def test_costs_are_split_into_named_components_that_sum() -> None:
    ev = evaluate_transition(v((40,), (60, 64)), v((43,), (62, 65)))
    assert set(ev.cost.as_dict()) == {
        "movement",
        "leap",
        "common_tones",
        "bass_motion",
        "parallels",
    }
    assert math.isclose(ev.cost.total, sum(ev.cost.as_dict().values()), abs_tol=1e-5)
    c = constraints_for_skill("advanced")
    st = static_cost(P("Dm7"), generate_voicings(P("Dm7"), c)[0], c, VoiceLeadingConfig("jazz"))
    assert {"completeness", "dissonance", "clustering", "span", "register", "ease"} <= set(
        st.as_dict()
    )


def test_leaving_out_the_third_costs_more_than_leaving_out_the_fifth() -> None:
    c = constraints_for_skill("intermediate")
    cfg = VoiceLeadingConfig("pop")
    chord = P("Cmaj7")
    no_fifth = Voicing((36,), (64, 71, 72), "bass", "seventh_close", (), ("P5",))
    no_third = Voicing((36,), (67, 71, 72), "bass", "seventh_close", (), ("M3",))
    assert static_cost(chord, no_fifth, c, cfg).total < static_cost(chord, no_third, c, cfg).total


def test_low_close_intervals_are_penalised() -> None:
    c = constraints_for_skill("advanced")
    cfg = VoiceLeadingConfig("jazz")
    low = Voicing((36, 41), (60, 64), "x", "y")  # C2 F2: a fourth in the mud
    high = Voicing((48, 53), (60, 64), "x", "y")
    assert (
        static_cost(P("Dm7"), low, c, cfg).as_dict()["clustering"]
        > static_cost(P("Dm7"), high, c, cfg).as_dict()["clustering"]
    )


def test_style_changes_what_counts_as_a_problem() -> None:
    c = constraints_for_skill("advanced")
    rootless = next(x for x in generate_voicings(P("Dm7"), c) if x.rh_style == "rootless_a")
    classical = static_cost(P("Dm7"), rootless, c, VoiceLeadingConfig("classical")).as_dict()[
        "tension"
    ]
    jazz = static_cost(P("Dm7"), rootless, c, VoiceLeadingConfig("jazz")).as_dict()["tension"]
    assert classical > jazz == 0


# ---------------------------------------------------------------- sequence choice


def brute_force_cost(cs, c, cfg, limit: int) -> float:  # type: ignore[no-untyped-def]
    cand = [_candidates(ch, c, cfg, None, limit) for ch in cs]
    best = math.inf
    for combo in itertools.product(*cand):
        total = sum(s for s, _ in combo)
        for (_, a), (_, b) in zip(combo, combo[1:], strict=False):
            total += _transition_total(evaluate_transition(a, b, c, cfg), False)
        best = min(best, total)
    return best


@pytest.mark.parametrize("skill", ["beginner", "intermediate", "advanced"])
@pytest.mark.parametrize("progression", [II_V_I, "C Am F G", "Cmaj7 A7 Dm7 G7"])
def test_dp_finds_the_true_optimum(skill: str, progression: str) -> None:
    c = constraints_for_skill(skill)  # type: ignore[arg-type]
    cfg = config_for("jazz" if skill == "advanced" else "pop", "smooth")
    cs = chords(progression)
    result = voice_chords(cs, c, config=cfg, max_candidates=7, method="dp")
    assert result.method == "dp" and not result.relaxed_leap_limit
    assert math.isclose(result.total_cost, brute_force_cost(cs, c, cfg, 7), abs_tol=1e-5)


def test_beam_search_is_never_better_than_dp_and_matches_when_wide() -> None:
    c = constraints_for_skill("advanced")
    cfg = config_for("jazz", "smooth")
    cs = chords("Dm7 G7 Cmaj7 Am7 Dm7 G7 Cmaj7")
    dp = voice_chords(cs, c, config=cfg, method="dp", max_candidates=25)
    wide = voice_chords(cs, c, config=cfg, method="beam", beam_width=500, max_candidates=25)
    narrow = voice_chords(cs, c, config=cfg, method="beam", beam_width=2, max_candidates=25)
    assert wide.method == narrow.method == "beam"
    assert math.isclose(wide.total_cost, dp.total_cost, abs_tol=1e-5)
    assert narrow.total_cost >= dp.total_cost - 1e-6


def test_results_are_reproducible() -> None:
    c = constraints_for_skill("expert")
    cfg = config_for("jazz", "smooth")
    cs = chords("Dm7 G7 Cmaj7 A7")
    a = voice_chords(cs, c, config=cfg)
    b = voice_chords(cs, c, config=cfg)
    assert a == b
    assert [i.voicing for i in a.items] == [i.voicing for i in b.items]


def test_every_chosen_voicing_is_playable_and_contains_the_right_notes() -> None:
    for skill in ("beginner", "intermediate", "advanced", "expert"):
        c = constraints_for_skill(skill)  # type: ignore[arg-type]
        result = voice_chords(chords("Dm7 G7 Cmaj7 Fmaj7 Bm7b5 E7 Am7"), c)
        for item in result.items:
            assert playability_issues(item.voicing, c) == []
            tones = {
                (item.chord.root.pitch_class + i.semitones) % 12 for i in item.chord.type.formula
            }
            third = (item.chord.root.pitch_class + 3) % 12, (item.chord.root.pitch_class + 4) % 12
            assert any(t in {n % 12 for n in item.voicing.notes} for t in third)
            assert {n % 12 for n in item.voicing.notes} - tones <= {
                (item.chord.root.pitch_class + 14) % 12,
                (item.chord.root.pitch_class + 21) % 12,
                (item.chord.root.pitch_class + 18) % 12,
                (item.chord.root.pitch_class + 15) % 12,
            }  # only declared tensions beyond the chord tones


def test_smooth_weights_move_less_than_root_position_weights() -> None:
    c = constraints_for_skill("intermediate")
    cs = chords("C Am F G C F G C")
    smooth = voice_chords(cs, c, config=config_for("pop", "smooth"))
    rooted = voice_chords(cs, c, config=config_for("pop", "root_position"))

    def motion(res) -> int:  # type: ignore[no-untyped-def]
        return sum(i.transition.info.movement for i in res.items if i.transition)

    def root_pos(res) -> int:  # type: ignore[no-untyped-def]
        return sum(1 for i in res.items if i.voicing.rh_inversion == 0)

    assert motion(smooth) <= motion(rooted)
    assert root_pos(rooted) >= root_pos(smooth)


def test_voice_leading_is_actually_smooth() -> None:
    c = constraints_for_skill("advanced")
    result = voice_chords(
        chords("Dm7 G7 Cmaj7 Am7 Dm7 G7 Cmaj7"), c, config=config_for("jazz", "smooth")
    )
    for item in result.items[1:]:
        assert item.transition is not None
        assert item.transition.info.largest_leap <= 5
        assert item.transition.info.movement <= 12


def test_strict_counterpoint_avoids_parallel_fifths_and_octaves() -> None:
    c = constraints_for_skill("intermediate")
    cfg = VoiceLeadingConfig("classical", strict_counterpoint=True)
    result = voice_chords(chords("C F G C Am Dm G C"), c, config=cfg)
    for item in result.items[1:]:
        assert item.transition is not None
        assert item.transition.info.parallel_fifths == 0
        assert item.transition.info.parallel_octaves == 0


def test_max_leap_is_a_hard_limit_when_it_can_be_met() -> None:
    c = constraints_for_skill("intermediate", max_leap=4)
    result = voice_chords(chords(II_V_I), c)
    assert not result.relaxed_leap_limit and not result.warnings
    assert all(i.transition.info.largest_leap <= 4 for i in result.items[1:] if i.transition)


def test_impossible_max_leap_is_relaxed_and_reported_not_hidden() -> None:
    c = constraints_for_skill("intermediate", max_leap=3)
    pinned = {0: v((36,), (60, 64, 67, 71)), 1: v((38,), (74, 77, 81, 84))}  # forced far apart
    result = voice_chords(chords("Cmaj7 Dm7"), c, fixed=pinned)
    assert result.relaxed_leap_limit and result.warnings
    assert "exceeds the max leap of 3" in result.warnings[0]


def test_pinned_voicings_are_kept_and_checked() -> None:
    c = constraints_for_skill("intermediate")
    pin = generate_voicings(P("G7"), c)[0]
    result = voice_chords(chords(II_V_I), c, fixed={1: pin})
    assert result.items[1].voicing == pin
    with pytest.raises(TheoryError) as err:
        voice_chords(chords(II_V_I), c, fixed={1: v((10,), (200,))})
    assert err.value.code == "unplayable_voicing"


def test_errors_for_impossible_or_invalid_requests() -> None:
    with pytest.raises(TheoryError) as err:
        voice_chords([], constraints_for_skill("beginner"))
    assert err.value.code == "no_chords"
    tiny = VoicingConstraints(rh_range=(60, 62), lh_range=(36, 40))
    with pytest.raises(TheoryError) as err2:
        voice_chords(chords("C Dm7"), tiny)
    assert err2.value.code == "no_playable_voicing" and "chord 1" in err2.value.message
    with pytest.raises(TheoryError):
        voice_chords(chords("C"), max_candidates=0)
    with pytest.raises(TheoryError):
        VoiceLeadingConfig("polka")
    with pytest.raises(TheoryError):
        config_for("pop", "nope")
    assert set(STYLE_PROFILES) >= {"classical", "pop", "jazz", "gospel", "worship"}
    assert set(WEIGHT_PRESETS) >= {"balanced", "smooth", "complete", "root_position", "easy"}


def test_explanations_describe_each_choice() -> None:
    result = voice_chords(
        chords(II_V_I), constraints_for_skill("advanced"), config=config_for("jazz")
    )
    first, second = result.items[0], result.items[1]
    assert (
        first.explanation[0].startswith("Dm7:")
        and "LH" in first.explanation[0]
        and "RH" in first.explanation[0]
    )
    assert not any("Moves" in line for line in first.explanation)
    assert any(line.startswith("Moves") and "holds" in line for line in second.explanation)
    named = " ".join(result.items[0].explanation)
    assert "D" in named  # spelled note names with octaves, e.g. "F4 A4 C5"


def test_evaluate_sequence_agrees_with_the_optimiser() -> None:
    c = constraints_for_skill("intermediate")
    cfg = VoiceLeadingConfig("pop")
    cs = chords("C Am F G")
    chosen = voice_chords(cs, c, config=cfg)
    scored = evaluate_sequence(cs, [i.voicing for i in chosen.items], c, cfg)
    assert math.isclose(scored.total_cost, chosen.total_cost, abs_tol=1e-5)
    worse = evaluate_sequence(
        cs, [generate_voicings(ch, c)[-1] for ch in cs], c, cfg
    )  # the last (highest) voicing of each chord, chosen without thinking about movement
    assert worse.total_cost > chosen.total_cost
    with pytest.raises(TheoryError):
        evaluate_sequence(cs, [], c, cfg)


def test_a_long_progression_solves_quickly() -> None:
    cs = chords("Dm7 G7 Cmaj7 A7 Dm7 G7 Em7 A7 Dm7 G7 Cmaj7 Am7 Dm7 G7 Cmaj7 Cmaj7")
    start = time.perf_counter()
    result = voice_chords(
        cs, constraints_for_skill("advanced"), config=config_for("jazz", "smooth")
    )
    assert time.perf_counter() - start < 15
    assert len(result.items) == 16 and result.method == "dp"
