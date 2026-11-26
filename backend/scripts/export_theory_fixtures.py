"""Write real theory API responses to the frontend's test fixtures.

The web client's TypeScript types are written by hand, so the frontend typechecks and tests against
these captured responses: if the API changes shape, regenerate and the build shows what broke.

    cd backend && PYTHONPATH=. python scripts/export_theory_fixtures.py
"""

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from app.schemas import lesson as ls
from app.schemas import movement as ms
from app.schemas import theory as s
from app.services import lesson_service
from app.services import theory_service as svc
from music_theory import lessons as lx
from music_theory import movements as mv
from music_theory.validation import parse_key

OUT = Path(__file__).resolve().parents[2] / "frontend" / "lib" / "piano" / "__fixtures__"
LESSON_OUT = Path(__file__).resolve().parents[2] / "frontend" / "lib" / "lessons" / "__fixtures__"
AUDIO_OUT = Path(__file__).resolve().parents[2] / "frontend" / "lib" / "audio" / "__fixtures__"
MOVEMENT_OUT = (
    Path(__file__).resolve().parents[2] / "frontend" / "lib" / "movements" / "__fixtures__"
)


def dump(name: str, model: BaseModel, out: Path = OUT) -> None:
    data: dict[str, Any] = model.model_dump(mode="json")
    (out / f"{name}.json").write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    dump("chord-dm7-over-c", svc.construct_chord(s.ChordConstructRequest(symbol="Dm7/C")))
    dump("chord-cmaj7", svc.construct_chord(s.ChordConstructRequest(symbol="Cmaj7")))
    dump("chord-c-over-d", svc.construct_chord(s.ChordConstructRequest(symbol="C/D")))
    dump("chord-gb-major", svc.construct_chord(s.ChordConstructRequest(root="Gb", type="major")))
    dump("identify-c-major", svc.identify(s.ChordIdentifyRequest(notes=[60, 64, 67])))
    dump("identify-first-inversion", svc.identify(s.ChordIdentifyRequest(notes=[64, 67, 72])))
    dump("identify-am7", svc.identify(s.ChordIdentifyRequest(notes=[57, 60, 64, 67])))
    dump("identify-cluster", svc.identify(s.ChordIdentifyRequest(notes=[60, 61, 62])))
    dump(
        "scale-f-sharp-major",
        svc.generate_scale(s.ScaleRequest(root="F#", scale="major", octave=4)),
    )
    dump(
        "voicings-cmaj7",
        svc.generate_voicing_options(
            s.VoicingsGenerateRequest(
                chord="Cmaj7", limit=1, config=s.VoicingConfigIn(skill="intermediate")
            )
        ),
    )
    MOVEMENT_OUT.mkdir(parents=True, exist_ok=True)
    AUDIO_OUT.mkdir(parents=True, exist_ok=True)
    regions = [
        {
            "start": 0.0,
            "end": 2.0,
            "label": "C:maj",
            "scores": {"C:maj": 0.93, "C:maj7": 0.91, "A:min7": 0.7},
            "bass_pc": 0,
            "pitch_classes": [0, 4, 7],
        },
        {
            "start": 2.0,
            "end": 4.0,
            "label": "A:min",
            "scores": {"A:min": 0.95, "C:maj": 0.72},
            "bass_pc": 9,
            "pitch_classes": [9, 0, 4],
        },
        {
            "start": 4.0,
            "end": 6.0,
            "label": "N",
            "scores": {},
            "bass_pc": None,
            "pitch_classes": None,
        },
        {
            "start": 6.0,
            "end": 8.0,
            "label": "F:maj",
            "scores": {"F:maj": 0.9},
            "bass_pc": 5,
            "pitch_classes": [5, 9, 0],
        },
    ]
    dump(
        "audio-interpret", svc.interpret_audio(s.AudioInterpretRequest(regions=regions)), AUDIO_OUT
    )  # type: ignore[arg-type]
    dump(
        "audio-interpret-corrected",
        svc.interpret_audio(
            s.AudioInterpretRequest(
                regions=regions, corrections=[{"op": "relabel", "index": 1, "label": "Am7"}]
            )
        ),
        AUDIO_OUT,
    )  # type: ignore[arg-type]
    LESSON_OUT.mkdir(parents=True, exist_ok=True)
    empty = lesson_service.Counts({}, set())
    dump(
        "lesson-list",
        ls.LessonListOut(
            items=[ls.LessonSummaryOut(**i) for i in lesson_service.build_list(empty)]
        ),
        LESSON_OUT,
    )
    dump(
        "lesson-triads",
        ls.LessonDetailOut(
            **lesson_service.build_detail(
                lx.get_lesson("triads"),
                lesson_service.Counts(
                    {("triad_build", "beginner"): 3}, {("triad_build", "beginner")}
                ),
                None,
            )
        ),
        LESSON_OUT,
    )
    built = mv.build_movement(
        mv.MovementDefinition(
            name="ii-V-I", key=parse_key("C"), template_id="ii_v_i", tags=("jazz",),
            author="Keystudy", theory_explanation="ii leads to V, which resolves to I.",
        )
    )  # fmt: skip
    dump(
        "movement-ii-v-i",
        ms.MovementDetailOut(movement=mv.built_to_dict(built), live=False),
        MOVEMENT_OUT,
    )  # type: ignore[arg-type]
    ex_set = svc.make_exercises(
        s.ExerciseGenerateRequest(kind="triad_identify", difficulty="beginner", seed=3)
    )
    dump("exercise-set", ex_set)
    dump(
        "exercise-grade",
        svc.grade_exercise(
            s.ExerciseValidateRequest(exercise_id=ex_set.exercises[0].id, answer="Zm")
        ),
    )
    dump("exercise-kinds", svc.list_exercise_kinds())
    dump("chord-types", svc.list_chord_types())
    dump("scales", svc.list_scales())


if __name__ == "__main__":
    main()
