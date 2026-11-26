# 0007 Lessons

## Decisions
**Authored text, engine-built examples.** Lessons are data (`music_theory/data/lessons.json`): objectives, explanation, example *specifications* and practice goals. An example names a chord, scale, interval or chord sequence; the theory engine builds the notes, MIDI numbers, Roman numerals and playback when the lesson is requested. The data contains no MIDI numbers and no note lists for examples.

**Prose that names notes is tested too.** A few captions spell notes by hand ("C major: C, E, G"). Tests parse those captions and compare them with what the engine built, so the text cannot drift from the marking engine.

**Progress is derived, not stored.** A practice goal is met when the learner has answered at least `goal` *distinct* exercises of that kind and difficulty correctly (from `exercise_attempts`, see ADR 0006). A lesson is *practised* when every goal is met, *in progress* when something was attempted. There is no "mark as done" button and no lesson-progress table, so lesson status can never disagree with the practice record. Repeating one exercise does not count twice.

**Prerequisites are advice.** A lesson shows what it builds on and links to it, but never blocks. The list page suggests the first unfinished lesson whose prerequisites are practised.

**Strict loader.** Loading refuses duplicate ids, unknown prerequisites, prerequisite cycles, unknown exercise kinds, malformed or unbuildable examples, empty objectives and unknown movement templates. Tests also require that every exercise kind is practised by some lesson, that prerequisites come earlier in the curriculum and are not harder, and that practice never uses a harder difficulty than the lesson.

## Limits
- 16 lessons in English only. Lessons that need a worked analysis of a full piece, or recorded audio, are not covered.
- "Practised" counts practice answers. It is not a measure of understanding.
- Examples are built at one octave chosen by the author; a sequence can set an octave per chord when close voicings are the point (an inversion sits above its root-position octave).
- Lesson content is edited in the JSON file, not through the admin screen.
- Lessons link to the movement library by progression template; the link appears only when a matching movement is published.
