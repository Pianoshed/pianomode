"""What the learner is shown as the answer must be something the grader accepts if typed back."""

import re

import pytest

from music_theory.errors import TheoryError
from music_theory.exercises import (
    DIFFICULTIES,
    KINDS,
    generate_exercise,
    parse_interval_answer,
    reference_answer,
    validate_answer,
)

SEEDS = range(1, 31)
LIST_FORMATS = ("note_names", "chord_symbols", "note_set")


def probe(ex):
    """An answer in the right shape that is certainly wrong, used only to make the grader show
    its answer."""
    if ex.answer_format == "choice":
        return next(c for c in ex.choices if c != reference_answer(ex.id))
    return ["zzz"] if ex.answer_format in LIST_FORMATS else "zzz"


def shown_answer(ex):
    return validate_answer(ex.id, probe(ex)).correct_answer


def as_typed(ex, shown):
    """What the answer box would send for the text a learner copies from the screen."""
    if ex.answer_format in LIST_FORMATS:
        return [t for t in re.split(r"[\s,]+", shown) if t]
    return shown


@pytest.mark.parametrize("kind", sorted(KINDS))
def test_the_displayed_answer_is_accepted_when_typed_back(kind):
    for difficulty in DIFFICULTIES:
        for seed in SEEDS:
            ex = generate_exercise(kind, difficulty, seed)
            if ex.answer_format == "choice":
                assert reference_answer(ex.id) in ex.choices, (kind, difficulty, seed)
                continue
            typed = as_typed(ex, shown_answer(ex))
            got = validate_answer(ex.id, typed)
            assert got.correct, (kind, difficulty, seed, typed, got.status, got.feedback)


@pytest.mark.parametrize("kind", sorted(KINDS))
def test_the_reference_answer_is_always_correct(kind):
    for difficulty in DIFFICULTIES:
        for seed in SEEDS:
            ex = generate_exercise(kind, difficulty, seed)
            assert validate_answer(ex.id, reference_answer(ex.id)).correct, (kind, difficulty, seed)


def find(kind, predicate, difficulties=DIFFICULTIES):
    for difficulty in difficulties:
        for seed in range(1, 200):
            ex = generate_exercise(kind, difficulty, seed)
            if predicate(ex):
                return ex
    raise AssertionError(f"no {kind} exercise matched")


# ------------------------------------------------------------------ intervals


def test_interval_gloss_is_accepted_and_checked():
    assert parse_interval_answer("m3 (minor third)") == parse_interval_answer("m3")
    assert parse_interval_answer("P5 (perfect fifth)").short == "P5"
    assert parse_interval_answer("  M3   ( major third ) ").short == "M3"
    with pytest.raises(TheoryError) as exc:
        parse_interval_answer("m3 (major third)")
    assert exc.value.code == "unreadable_interval"
    with pytest.raises(TheoryError):
        parse_interval_answer("m3 (nonsense)")
    with pytest.raises(TheoryError):
        parse_interval_answer("(minor third)")


def test_a_wrong_interval_with_a_gloss_is_wrong_not_unreadable():
    ex = find("interval_identify", lambda e: e.answer_format == "text")
    right = reference_answer(ex.id)
    other = "P5 (perfect fifth)" if "P5" not in str(right) else "M2 (major second)"
    assert validate_answer(ex.id, other).status == "incorrect"


# ------------------------------------------------------------------ "which key" questions


def which_key(mode):
    return find("key_signature", lambda e: e.prompt.startswith(f"Which {mode} key"))


@pytest.mark.parametrize("mode", ["major", "minor"])
def test_key_answer_may_end_with_the_matching_mode_word(mode):
    ex = which_key(mode)
    tonic = reference_answer(ex.id)
    for text in (tonic, f"{tonic} {mode}", f"{tonic} {mode.title()}", f"{tonic} {mode[:3]}"):
        assert validate_answer(ex.id, text).correct, text


@pytest.mark.parametrize("mode", ["major", "minor"])
def test_the_wrong_mode_word_is_marked_incorrect_and_explained(mode):
    ex = which_key(mode)
    other = "minor" if mode == "major" else "major"
    got = validate_answer(ex.id, f"{reference_answer(ex.id)} {other}")
    assert got.status == "incorrect" and not got.correct
    assert other in got.feedback and mode in got.feedback


def test_a_mode_word_is_not_accepted_where_no_key_was_asked():
    ex = find("interval_build", lambda e: e.answer_format == "text")
    note = reference_answer(ex.id)
    assert validate_answer(ex.id, f"{note} major").status in ("unreadable", "incorrect")


# ------------------------------------------------------------------ black keys


def black_key(octave):
    return find(
        "note_name",
        lambda e: any(
            "#" in x and "/" in x for x in [validate_answer(e.id, "zzz").correct_answer] if True
        )
        and (any(ch.isdigit() for ch in validate_answer(e.id, "zzz").correct_answer) == octave),
    )


def test_both_names_of_a_black_key_are_accepted_together_or_alone():
    ex = black_key(octave=False)
    shown = validate_answer(ex.id, "zzz").correct_answer
    sharp, flat = (p.strip() for p in shown.split("/"))
    for text in (sharp, flat, shown, f"{sharp}/{flat}", f"{flat} / {sharp}"):
        assert validate_answer(ex.id, text).correct, text


def test_a_slash_with_a_wrong_name_is_not_accepted():
    ex = black_key(octave=False)
    sharp = validate_answer(ex.id, "zzz").correct_answer.split("/")[0].strip()
    wrong = "C" if sharp != "C" else "D"
    got = validate_answer(ex.id, f"{sharp} / {wrong}")
    assert not got.correct and got.status == "incorrect"
    assert validate_answer(ex.id, f"{sharp} / ???").status == "unreadable"
