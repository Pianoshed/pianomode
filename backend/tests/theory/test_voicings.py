import pytest

from music_theory.chord_symbols import parse_chord as P
from music_theory.chords import CHORD_TYPES, make_chord
from music_theory.errors import TheoryError
from music_theory.intervals import parse_interval
from music_theory.voicings import (
    PIANO_HI,
    PIANO_LO,
    PRESETS,
    SKILLS,
    Voicing,
    VoicingConstraints,
    constraints_for_skill,
    generate_voicings,
    playability_issues,
    voiced_notes,
)


def pcs(notes: tuple[int, ...]) -> set[int]:
    return {n % 12 for n in notes}


def gen(symbol: str, skill: str = "intermediate", **kw):  # type: ignore[no-untyped-def]
    return generate_voicings(P(symbol), constraints_for_skill(skill), **kw)  # type: ignore[arg-type]


def test_beginner_voicings_are_a_bass_note_and_a_close_triad() -> None:
    voicings = gen("Cmaj7", "beginner")
    assert voicings
    for v in voicings:
        assert pcs(v.notes) <= {0, 4, 7} and v.omitted == ("M7",)
        assert v.rh_style == "triad_close" and len(v.right) == 3
        assert v.left and v.left[0] % 12 == 0  # the bass is the root
    rights = {v.right for v in voicings}
    assert {(60, 64, 67), (64, 67, 72), (55, 60, 64)} <= rights  # root, 1st, 2nd inversion
    by_right = {v.right: v for v in voicings}
    assert [by_right[r].rh_inversion for r in [(60, 64, 67), (64, 67, 72), (55, 60, 64)]] == [
        0,
        1,
        2,
    ]


def test_rootless_evans_voicings() -> None:
    dm7 = {(v.right, v.rh_style) for v in gen("Dm7", "advanced")}
    assert ((65, 69, 72, 76), "rootless_a") in dm7  # F A C E: 3-5-7-9
    assert ((60, 64, 65, 69), "rootless_b") in dm7  # C E F A: 7-9-3-5
    g7 = {(v.right, v.rh_style) for v in gen("G7", "advanced")}
    assert ((59, 64, 65, 69), "rootless_a") in g7  # B E F A: 3-13-7-9
    rootless = next(
        v
        for v in gen("Dm7", "advanced")
        if v.right == (65, 69, 72, 76) and v.rh_style == "rootless_a"
    )
    assert rootless.tensions == ("M9",) and "P1" in rootless.omitted or rootless.left


def test_shells_guide_tones_and_tenths() -> None:
    lefts = {(v.left, v.lh_style) for v in gen("G7", "expert")}
    assert ((43, 47, 53), "shell_r37") in lefts  # G B F
    assert ((43, 53, 59), "shell_r73") in lefts  # G F B
    assert ((47, 53), "guide_tones_3_7") in lefts or ((59, 65), "guide_tones_3_7") in lefts
    tenth = {v.left for v in gen("C", "expert", lh_styles=["tenth"], rh_styles=["triad_close"])}
    assert (36, 52) in tenth  # C2 + E3
    narrow = constraints_for_skill("intermediate")  # span 12 cannot hold a tenth
    assert not generate_voicings(P("C"), narrow, lh_styles=["tenth"], rh_styles=["triad_close"])


def test_drop2_is_the_second_note_from_the_top_dropped_an_octave() -> None:
    c = constraints_for_skill("expert")
    voicings = generate_voicings(P("Cmaj7"), c, lh_styles=["bass"], rh_styles=["drop2"])
    assert voicings
    for v in voicings:
        assert len(v.right) == 4 and v.right[-1] - v.right[0] >= 13
    assert (55, 60, 64, 71) in {v.right for v in voicings}  # G C E B from C E G B


def test_upper_structure_triads_sit_above_a_shell() -> None:
    c = constraints_for_skill("expert")
    voicings = generate_voicings(P("C7"), c, lh_styles=["shell_r37"], rh_styles=["upper_structure"])
    ust = [v for v in voicings if v.rh_style == "upper_structure_II"]
    assert ust
    for v in ust:
        assert pcs(v.right) == {2, 6, 9}  # D F# A over C7
        assert {4, 10} <= pcs(v.left)  # the shell carries the 3rd and 7th
        assert v.tensions == ("M9", "A11", "M13")
    assert {v.rh_style for v in voicings} == {
        "upper_structure_II", "upper_structure_bIII", "upper_structure_bV"
    }  # fmt: skip
    assert not generate_voicings(
        P("Cm7"), c, lh_styles=["shell_r37"], rh_styles=["upper_structure"]
    )


def test_altered_dominant_voicings() -> None:
    c = constraints_for_skill("expert")
    voicings = generate_voicings(P("C7"), c, lh_styles=["bass"], rh_styles=["altered"])
    assert voicings
    for v in voicings:
        assert {4, 10} <= pcs(v.right)  # 3rd and flat 7th
        assert pcs(v.right) - {4, 10} <= {1, 3, 8}  # b9, #9, b13
        assert len(v.tensions) == 2


def test_gospel_and_worship_presets_add_the_ninth() -> None:
    for preset in ("gospel", "worship"):
        voicings = gen("C", "intermediate", preset=preset)
        added = [v for v in voicings if v.tensions == ("M9",)]
        assert added and all(2 in pcs(v.right) for v in added)
    assert gen("C", "intermediate", preset="gospel")[0].lh_style in (
        "bass",
        "octave_root",
        "open_fifth",
    )
    sus2 = gen("Csus2", "intermediate", preset="worship")
    assert sus2 and all(v.tensions == () for v in sus2)  # the 9th is already in a sus2 chord


def test_slash_chords_keep_their_bass() -> None:
    inverted = gen("C/E", "intermediate")
    assert inverted and all(min(v.notes) % 12 == 4 for v in inverted)
    assert {v.lh_style for v in inverted} <= {"bass", "octave_root"}
    non_chord = gen("C/D", "intermediate")
    assert non_chord and all(min(v.notes) % 12 == 2 for v in non_chord)
    assert all(pcs(v.right) <= {0, 4, 7} for v in non_chord)


def test_constraints_are_honoured() -> None:
    c = VoicingConstraints(
        lh_range=(40, 52), rh_range=(60, 72), max_span=7, max_notes_per_hand=2,
        forbidden_tones=frozenset({"fifth"}), required_tones=frozenset({"seventh"}),
    )  # fmt: skip
    voicings = generate_voicings(P("G7"), c, preset="advanced")
    assert voicings
    for v in voicings:
        assert not playability_issues(v, c)
        assert 2 not in pcs(v.notes) and 5 in pcs(v.notes)  # no D, has the F
    only_bass_d = VoicingConstraints(bass_pc=2, max_notes_per_hand=4)
    for v in generate_voicings(P("Dm7"), only_bass_d):
        assert min(v.notes) % 12 == 2


def test_hand_gap_is_configurable() -> None:
    for gap in (1, 5, 9):
        c = constraints_for_skill("intermediate", min_hand_gap=gap)
        for v in generate_voicings(P("Dm7"), c):
            if v.left and v.right:
                assert v.right[0] - v.left[-1] >= gap


def test_required_tones_the_chord_lacks_are_ignored() -> None:
    c = constraints_for_skill("intermediate", required_tones=frozenset({"seventh", "M13"}))
    assert generate_voicings(P("C"), c)  # a triad has no seventh or 13th: nothing to require


def test_impossible_constraints_give_no_voicings_not_wrong_ones() -> None:
    c = VoicingConstraints(rh_range=(60, 62), lh_range=(36, 40))
    assert generate_voicings(P("Cmaj7"), c) == []


@pytest.mark.parametrize("skill", SKILLS)
@pytest.mark.parametrize("root", ["C", "F#", "Bb", "E"])
@pytest.mark.parametrize("type_id", list(CHORD_TYPES))
def test_every_voicing_of_every_chord_is_valid_and_repeatable(
    skill: str, root: str, type_id: str
) -> None:
    chord = make_chord(root, type_id)
    c = constraints_for_skill(skill)  # type: ignore[arg-type]
    first = generate_voicings(chord, c)
    assert first == generate_voicings(chord, c)  # deterministic
    chord_pcs = {(chord.root.pitch_class + i.semitones) % 12 for i in chord.type.formula}
    third = next((i for i in chord.type.formula if i.number == 3), None)
    for v in first:
        assert playability_issues(v, c) == [], (chord, v)
        allowed = chord_pcs | {
            (chord.root.pitch_class + parse_interval(t).semitones) % 12 for t in v.tensions
        }
        assert pcs(v.notes) <= allowed, (chord, v)
        assert all(PIANO_LO <= n <= PIANO_HI for n in v.notes)
        if third is not None:
            assert (chord.root.pitch_class + third.semitones) % 12 in pcs(v.notes)
        assert len(v.left) <= c.max_notes_per_hand and len(v.right) <= c.max_notes_per_hand


def test_common_chords_always_have_voicings_at_every_level() -> None:
    for skill in SKILLS:
        for symbol in ("C", "Dm7", "G7", "Cmaj7", "Am", "F", "Bm7b5", "E7", "Fmaj7", "Bb"):
            assert gen(symbol, skill), (skill, symbol)


def test_voiced_notes_label_hands_roles_and_spelling() -> None:
    v = next(
        x
        for x in gen("Dm7", "advanced")
        if x.right == (65, 69, 72, 76) and x.rh_style == "rootless_a"
    )
    notes = voiced_notes(P("Dm7"), v)
    right = [n for n in notes if n.hand == "R"]
    assert [str(n.name) for n in right] == ["F", "A", "C", "E"]
    assert [n.role for n in right] == ["third", "fifth", "seventh", "tension"]
    assert sum(n.is_bass for n in notes) == 1 and notes[0].is_bass
    flat = voiced_notes(P("Bbmaj7"), gen("Bbmaj7", "intermediate")[0])
    assert any(str(n.name) == "Bb" for n in flat)


def test_voicing_serialisation_round_trip() -> None:
    v = gen("G7", "expert")[0]
    assert Voicing.from_dict(v.to_dict()) == v
    with pytest.raises(TheoryError):
        Voicing.from_dict({"left": "x"})


def test_playability_issues_are_reported() -> None:
    c = constraints_for_skill("intermediate")
    bad = Voicing((30, 60), (50, 51, 52, 53, 54), "x", "y")
    text = " | ".join(playability_issues(bad, c))
    assert "left hand leaves its range" in text and "plays 5 notes" in text
    assert "right hand leaves its range" in text
    assert "hands cross" in text
    assert "both hands play the same note" in " | ".join(
        playability_issues(Voicing((48,), (48,), "x", "y"), c)
    )
    assert "spans" in " | ".join(playability_issues(Voicing((), (60, 80), "x", "y"), c))
    assert "outside the 88-key piano" in " | ".join(
        playability_issues(Voicing((15,), (60,), "x", "y"), VoicingConstraints(lh_range=(0, 40)))
    )
    assert playability_issues(Voicing((), (), "x", "y"), c) == ["no notes"]


@pytest.mark.parametrize(
    "kwargs",
    [
        {"lh_range": (60, 40)}, {"rh_range": (-1, 50)}, {"max_span": 99}, {"max_notes_per_hand": 0},
        {"skill": "pro"}, {"required_tones": frozenset({"foo"})}, {"forbidden_tones": frozenset({"P9"})},
        {"tensions": ("root",)}, {"bass_pc": 12}, {"max_leap": -1}, {"min_hand_gap": -1},
    ],
)  # fmt: skip
def test_invalid_constraints_are_rejected(kwargs: dict[str, object]) -> None:
    with pytest.raises(TheoryError) as err:
        VoicingConstraints(**kwargs)  # type: ignore[arg-type]
    assert err.value.code == "invalid_constraints"


def test_unknown_presets_and_styles_are_rejected() -> None:
    with pytest.raises(TheoryError):
        gen("C", preset="polka")
    with pytest.raises(TheoryError):
        gen("C", rh_styles=["wobble"])
    with pytest.raises(TheoryError):
        gen("C", lh_styles=["wobble"])
    assert set(PRESETS) >= {
        "beginner",
        "intermediate",
        "advanced",
        "expert",
        "jazz",
        "gospel",
        "worship",
    }


@pytest.mark.parametrize("skill", SKILLS)
@pytest.mark.parametrize("preset", sorted(PRESETS))
def test_every_chord_type_can_be_voiced_by_every_preset_and_level(skill: str, preset: str) -> None:
    c = constraints_for_skill(skill)  # type: ignore[arg-type]
    for type_id in CHORD_TYPES:
        assert generate_voicings(make_chord("C", type_id), c, preset=preset), (
            skill,
            preset,
            type_id,
        )
