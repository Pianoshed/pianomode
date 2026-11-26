import pytest

from music_theory.errors import TheoryError
from music_theory.fingering import (
    FingeringDataError,
    _check,
    curated_scale_ids,
    scale_fingering,
    thumb_on_black_key,
)
from music_theory.scales import make_scale

ROOTS = ["C", "C#", "Db", "D", "Eb", "E", "F", "F#", "Gb", "G", "Ab", "A", "Bb", "B"]


def test_known_answers_c_major() -> None:
    f = scale_fingering(make_scale("C", "major"))
    assert f is not None
    assert f.right_hand == (1, 2, 3, 1, 2, 3, 4, 5)
    assert f.left_hand == (5, 4, 3, 2, 1, 3, 2, 1)


@pytest.mark.parametrize(
    ("root", "rh", "lh"),
    [
        ("F", (1, 2, 3, 4, 1, 2, 3, 4), (5, 4, 3, 2, 1, 3, 2, 1)),
        ("Bb", (4, 1, 2, 3, 1, 2, 3, 4), (3, 2, 1, 4, 3, 2, 1, 3)),
        ("F#", (2, 3, 4, 1, 2, 3, 1, 2), (4, 3, 2, 1, 3, 2, 1, 4)),
        ("B", (1, 2, 3, 1, 2, 3, 4, 5), (4, 3, 2, 1, 4, 3, 2, 1)),
    ],
)
def test_known_answers_other_majors(root: str, rh: tuple[int, ...], lh: tuple[int, ...]) -> None:
    f = scale_fingering(make_scale(root, "major"))
    assert f is not None
    assert (f.right_hand, f.left_hand) == (rh, lh)


def test_all_twelve_major_keys_are_curated() -> None:
    for pc_root in ["C", "Db", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B"]:
        assert scale_fingering(make_scale(pc_root, "major")) is not None


def test_enharmonic_roots_share_fingering() -> None:
    a = scale_fingering(make_scale("F#", "major"))
    b = scale_fingering(make_scale("Gb", "major"))
    assert a is not None and b is not None
    assert (a.right_hand, a.left_hand) == (b.right_hand, b.left_hand)


def test_no_curated_fingering_returns_none() -> None:
    assert scale_fingering(make_scale("C", "blues")) is None
    assert scale_fingering(make_scale("Bb", "natural_minor")) is None


def test_descending_is_reversed() -> None:
    up = scale_fingering(make_scale("D", "major"))
    down = scale_fingering(make_scale("D", "major"), "descending")
    assert up is not None and down is not None
    assert down.right_hand == up.right_hand[::-1]


def test_thumb_never_on_black_key_for_any_curated_scale() -> None:
    for sid in curated_scale_ids():
        for root in ROOTS:
            scale = make_scale(root, sid)
            f = scale_fingering(scale)
            if f is not None:
                assert not thumb_on_black_key(scale, f), (sid, root)
                assert not thumb_on_black_key(scale, scale_fingering(scale, "descending"))  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "bad", [[1, 2, 3], [1, 2, 3, 1, 2, 3, 4, 6], [1, 1, 3, 1, 2, 3, 4, 5], "12345678", [0] * 8]
)
def test_bad_data_is_rejected(bad: object) -> None:
    with pytest.raises(FingeringDataError):
        _check("x", bad, 7)


def test_error_is_a_theory_error() -> None:
    assert issubclass(FingeringDataError, TheoryError)
