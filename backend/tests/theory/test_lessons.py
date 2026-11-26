"""Lessons: the shipped content is valid and true to the engine, and the loader is strict."""

import copy
import json
import re

import pytest

from music_theory.errors import TheoryError
from music_theory.exercises import DIFFICULTIES, KINDS
from music_theory.lessons import (
    DATA_FILE,
    LEVELS,
    all_lessons,
    build_example,
    followers,
    get_lesson,
    parse_lessons,
)

RAW = json.loads(DATA_FILE.read_text(encoding="utf-8"))


def example(lesson_id: str, index: int = 0, section: int = 0):
    return build_example(get_lesson(lesson_id).sections[section].examples[index])


def all_examples():
    for lesson in all_lessons():
        for section in lesson.sections:
            for ex in section.examples:
                yield lesson.id, ex


def minimal(**over):
    base = {
        "id": "one",
        "title": "One",
        "level": "beginner",
        "summary": "s",
        "objectives": ["o"],
        "prerequisites": [],
        "sections": [{"heading": "h", "body": ["b"], "examples": []}],
        "practice": [{"kind": "note_name", "difficulty": "beginner", "goal": 3}],
    }
    return {**base, **over}


def data(*lessons, version=1):
    return {"schema_version": version, "lessons": list(lessons)}


def code_of(raw: dict) -> str:
    with pytest.raises(TheoryError) as exc:
        parse_lessons(raw)
    return str(exc.value.code)


# ------------------------------------------------------------------ the shipped curriculum


def test_shipped_lessons_load():
    lessons = all_lessons()
    assert len(lessons) >= 12
    assert {x.level for x in lessons} <= set(LEVELS)


def test_every_exercise_kind_has_a_lesson_that_practises_it():
    practised = {p.kind for x in all_lessons() for p in x.practice}
    assert practised == set(KINDS), set(KINDS) - practised


def test_practice_difficulty_matches_the_lesson_level_or_is_easier_or_equal():
    order = list(DIFFICULTIES)
    for x in all_lessons():
        for p in x.practice:
            assert order.index(p.difficulty) <= order.index(x.level), (x.id, p)


def test_prerequisites_come_earlier_and_are_not_harder():
    ids = [x.id for x in all_lessons()]
    for x in all_lessons():
        for pid in x.prerequisites:
            assert ids.index(pid) < ids.index(x.id), (x.id, pid)
            assert LEVELS.index(get_lesson(pid).level) <= LEVELS.index(x.level), (x.id, pid)


def test_every_lesson_is_reachable_from_a_starting_lesson():
    starts = [x.id for x in all_lessons() if not x.prerequisites]
    assert starts and get_lesson(starts[0]).level == "beginner"
    seen = set(starts)
    frontier = list(starts)
    while frontier:
        for f in followers(frontier.pop()):
            if f not in seen:
                seen.add(f)
                frontier.append(f)
    assert seen == {x.id for x in all_lessons()}


def test_authored_data_contains_no_notes():
    """Notes come from the engine; the data only names chords, scales and intervals."""
    for _lesson_id, ex in all_examples():
        assert "notes" not in ex.data and "midi" not in ex.data


def test_examples_are_deterministic():
    for _lid, ex in all_examples():
        assert build_example(ex) == build_example(ex)


def test_playback_refers_to_real_items_and_notes():
    for lid, ex in all_examples():
        b = build_example(ex)
        assert b.items and b.play and b.caption, lid
        for step in b.play:
            assert 0 <= step.item < len(b.items)
            assert set(step.notes) <= set(b.items[step.item].midi), (lid, b.caption)
            assert step.duration > 0 and step.start >= 0
        assert all(0 <= m <= 127 for it in b.items for m in it.midi)


# ------------------------------------------------------------------ known answers


def test_triads():
    assert example("triads", 0).items[0].notes == ("C", "E", "G")
    assert example("triads", 1).items[0].notes == ("C", "Eb", "G")
    assert example("triads", 0, 1).items[0].notes == ("C", "Eb", "Gb")
    assert example("triads", 1, 1).items[0].notes == ("C", "E", "G#")


def test_seventh_chords_keep_the_half_and_full_diminished_apart():
    notes = {
        it.label: it.notes
        for ex in get_lesson("seventh-chords").sections
        for e in ex.examples
        for it in build_example(e).items
    }
    assert notes["Cmaj7"] == ("C", "E", "G", "B")
    assert notes["C7"] == ("C", "E", "G", "Bb")
    assert notes["Cm7"] == ("C", "Eb", "G", "Bb")
    assert notes["Cm7b5"] == ("C", "Eb", "Gb", "Bb")
    assert notes["Cdim7"] == ("C", "Eb", "Gb", "Bbb")
    assert notes["Cm7b5"] != notes["Cdim7"]


def test_inversions_put_the_named_note_in_the_bass():
    items = [build_example(e).items[0] for e in get_lesson("inversions").sections[0].examples]
    assert [i.notes[0] for i in items] == ["C", "E", "G"]
    assert [i.midi[0] for i in items] == sorted(i.midi[0] for i in items)


def test_scales_and_key_signature_examples():
    ms = get_lesson("major-scale").sections[0].examples
    assert [i.notes[0] for i in build_example(ms[0]).items] == [
        "C",
        "D",
        "E",
        "F",
        "G",
        "A",
        "B",
        "C",
    ]
    assert "F#" in [i.notes[0] for i in build_example(ms[1]).items]
    assert "Bb" in [i.notes[0] for i in build_example(ms[2]).items]
    assert [i.notes[0] for i in example("key-signatures").items][:3] == ["D", "E", "F#"]


def test_intervals_have_the_right_size():
    sizes = {
        build_example(e).items[0].detail: build_example(e).items[0].label
        for e in get_lesson("intervals").sections[0].examples
    }
    assert sizes["m3"] == "m3 (3 semitones)" and sizes["M3"] == "M3 (4 semitones)"
    assert sizes["P4"] == "P4 (5 semitones)" and sizes["P5"] == "P5 (7 semitones)"
    assert example("notes-and-keyboard", 1, 1).items[0].label.endswith("(12 semitones)")


def test_roman_numerals_in_the_lessons_are_the_engines_own():
    numerals = lambda lid, i, s=0: [it.detail for it in example(lid, i, s).items]  # noqa: E731
    assert numerals("diatonic-harmony", 0) == ["I", "ii", "iii", "IV", "V", "vi", "vii°"]
    assert numerals("progressions", 2) == ["ii7", "V7", "Imaj7"]
    assert numerals("cadences", 0) == ["V", "I"] and numerals("cadences", 1) == ["IV", "I"]
    assert numerals("cadences", 1, 1) == ["V", "vi"]
    assert numerals("secondary-dominants", 0) == ["I", "V7/V", "V"]
    assert numerals("secondary-dominants", 1) == ["I", "V7/vi", "vi"]
    assert numerals("modal-interchange", 0) == ["I", "iv", "I"]
    assert numerals("modal-interchange", 1) == ["I", "bVI", "bVII", "I"]


def test_tritone_substitute_shares_the_third_and_seventh_of_the_dominant():
    plain, sub = (example("substitution", i).items[1] for i in (0, 1))
    assert (plain.label, sub.label) == ("G7", "Db7")
    third_and_seventh = lambda it: {m % 12 for m in it.midi[1::2]}  # noqa: E731
    assert third_and_seventh(plain) == third_and_seventh(sub) == {11, 5}  # B and F


def test_extension_examples():
    labels = [build_example(e).items[0] for e in get_lesson("extensions").sections[0].examples]
    assert labels[0].notes == ("C", "E", "G", "Bb", "D")  # C9
    assert labels[3].notes[-1] == "A"  # C13 ends on the thirteenth
    flat9 = build_example(get_lesson("extensions").sections[1].examples[0]).items[0]
    assert flat9.notes[-1] == "Db"


def test_voice_leading_captions_are_true_of_the_notes():
    """The lesson says common tones stay and the others move by step: check it."""
    lesson = get_lesson("voice-leading")
    for e in lesson.sections[0].examples + lesson.sections[1].examples:
        items = build_example(e).items
        for a, b in zip(items, items[1:], strict=False):
            moves = [abs(x - y) for x, y in zip(sorted(a.midi), sorted(b.midi), strict=True)]
            assert max(moves) <= 2, (e.caption, a.midi, b.midi)
    first = build_example(lesson.sections[0].examples[0]).items
    assert first[0].midi[:2] == first[1].midi[:2]  # C and E stay


# ------------------------------------------------------------------ the loader is strict


def test_a_minimal_lesson_loads():
    assert len(parse_lessons(data(minimal()))) == 1


@pytest.mark.parametrize(
    ("raw", "code"),
    [
        (data(minimal(), version=2), "unsupported_lesson_version"),
        ({"schema_version": 1, "lessons": []}, "invalid_lesson"),
        (data(minimal(), minimal()), "duplicate_lesson"),
        (data(minimal(prerequisites=["nope"])), "unknown_prerequisite"),
        (data(minimal(prerequisites=["one"])), "prerequisite_cycle"),
        (
            data(minimal(id="a", prerequisites=["b"]), minimal(id="b", prerequisites=["a"])),
            "prerequisite_cycle",
        ),
        (data(minimal(id="Bad Id")), "invalid_lesson"),
        (data(minimal(level="legendary")), "invalid_lesson"),
        (data(minimal(objectives=[])), "invalid_lesson"),
        (data(minimal(title="  ")), "invalid_lesson"),
        (data(minimal(sections=[])), "invalid_lesson"),
        (data(minimal(practice=[])), "invalid_lesson"),
        (
            data(minimal(practice=[{"kind": "nope", "difficulty": "beginner"}])),
            "unknown_exercise_kind",
        ),
        (
            data(minimal(practice=[{"kind": "note_name", "difficulty": "godlike"}])),
            "invalid_lesson",
        ),
        (
            data(minimal(practice=[{"kind": "note_name", "difficulty": "beginner", "goal": 0}])),
            "invalid_lesson",
        ),
        (
            data(minimal(practice=[{"kind": "note_name", "difficulty": "beginner", "goal": 99}])),
            "invalid_lesson",
        ),
        (
            data(minimal(practice=[{"kind": "note_name", "difficulty": "beginner", "goal": True}])),
            "invalid_lesson",
        ),
        (data(minimal(movement_template="no_such_template")), None),
    ],
)
def test_bad_lesson_data_is_refused(raw, code):
    got = code_of(raw)
    if code:
        assert got == code


def section_with(example: dict) -> dict:
    return {"sections": [{"heading": "h", "body": ["b"], "examples": [example]}]}


@pytest.mark.parametrize(
    "bad",
    [
        {
            "type": "chord",
            "caption": "c",
            "symbol": "Cmaj",
        },  # malformed symbol is never reinterpreted
        {"type": "chord", "caption": "c"},  # missing symbol
        {"type": "chord", "caption": "c", "symbol": "C", "octave": 9},
        {"type": "chord", "caption": "c", "symbol": "C", "octave": True},
        {"type": "scale", "caption": "c", "root": "C", "scale": "no_such_scale"},
        {"type": "scale", "caption": "c", "root": "H", "scale": "major"},
        {"type": "interval", "caption": "c", "lower": "C4"},
        {"type": "interval", "caption": "c", "lower": "C4", "upper": "nonsense"},
        {"type": "sequence", "caption": "c", "chords": []},
        {"type": "sequence", "caption": "c", "chords": ["C", 5]},
        {"type": "sequence", "caption": "c", "chords": ["C"] * 13},
        {"type": "sequence", "caption": "c", "chords": ["C", "G"], "key": "H major"},
        {"type": "sequence", "caption": "c", "chords": ["C", "G"], "octaves": [4]},
        {"type": "sequence", "caption": "c", "chords": ["C", "G"], "octaves": [4, 9]},
        {"type": "wizard", "caption": "c"},
        {"type": "chord", "symbol": "C"},  # no caption
    ],
)
def test_a_broken_example_stops_the_lesson_loading(bad):
    with pytest.raises(TheoryError):
        parse_lessons(data(minimal(**section_with(bad))))


def test_unknown_lesson_has_a_stable_code():
    with pytest.raises(TheoryError) as exc:
        get_lesson("nope")
    assert exc.value.code == "lesson_not_found"


def test_the_shipped_data_is_not_mutated_by_parsing():
    before = copy.deepcopy(RAW)
    parse_lessons(RAW)
    assert RAW == before


# ------------------------------------------------------------------ hand-written note names in captions

_TOKEN = re.compile(r"\b([A-G])(-flat| flat|-sharp| sharp| double flat| double sharp)?(?![a-z])")
_ACC = {
    "-flat": "b",
    " flat": "b",
    "-sharp": "#",
    " sharp": "#",
    " double flat": "bb",
    " double sharp": "##",
}


def notes_in(text: str) -> list[str]:
    """Note names written in prose such as 'C, E-flat, G' -> ['C', 'Eb', 'G']."""
    return [m[0] + _ACC.get(m[1] or "", "") for m in _TOKEN.findall(text)]


def test_the_note_reader_understands_the_caption_styles():
    assert notes_in("C, E-flat, G-flat, B double flat.") == ["C", "Eb", "Gb", "Bbb"]
    assert notes_in("F-sharp and C-sharp.") == ["F#", "C#"]
    assert notes_in("the third is lowered by a semitone.") == []


def test_captions_that_list_a_chords_notes_match_the_engine():
    checked = 0
    for lid, ex in all_examples():
        if ex.type != "chord" or ":" not in ex.caption:
            continue
        listed = notes_in(ex.caption.split(":", 1)[1])
        if not listed:
            continue
        built = build_example(ex).items[0]
        if "at the bottom" in ex.caption:  # names only the bass note, e.g. an inversion
            assert listed == [built.notes[0]], (lid, ex.caption, built.notes)
        else:
            assert listed == list(built.notes), (lid, ex.caption, built.notes)
        checked += 1
    assert checked >= 9  # really ran on the triad, inversion and seventh-chord captions


def test_captions_that_name_a_scales_accidentals_match_the_engine():
    checked = 0
    for lid, ex in all_examples():
        if ex.type != "scale" or ":" not in ex.caption:
            continue
        listed = notes_in(ex.caption.split(":", 1)[1])
        if not listed:
            continue
        built = {it.notes[0] for it in build_example(ex).items}
        accidentals = {n for n in built if len(n) > 1}
        assert set(listed) == accidentals, (lid, ex.caption, sorted(accidentals))
        checked += 1
    assert checked >= 3


def test_captions_about_a_notes_semitone_size_are_true():
    sizes = {"minor third": 3, "major third": 4, "perfect fourth": 5, "perfect fifth": 7}
    checked = 0
    for lid, ex in all_examples():
        if ex.type != "interval":
            continue
        for word, semis in sizes.items():
            m = re.search(rf"{word}: (\w+) semitones", ex.caption)
            if m:
                low, high = build_example(ex).items[0].midi
                assert high - low == semis, (lid, ex.caption)
                checked += 1
    assert checked == 4
