# Music theory engine (`backend/music_theory`)

Pure Python, standard library only. No web, database or audio imports, so every module is testable
alone and the API layer is a thin wrapper. Errors are `TheoryError` with a stable `code`.

## Built so far
| Module | What it does |
|---|---|
| `notes.py` | `NoteName` (spelling), `Note` (spelling + octave), MIDI, frequency (configurable A4), octave-number convention, enharmonics |
| `intervals.py` | `Interval` (number + semitones), qualities, compound, inversion, spelling-correct transposition, interval between notes |
| `scales.py` | Data-driven scales/modes from `data/scales.json`, validated registry, ascending/descending forms |
| `keys.py` | Key signatures (including theoretical keys), relative/parallel keys, spelling in a key |
| `chords.py` | 40+ chord types as explicit interval formulas, `Chord` with tones, inversions, slash bass, MIDI realisation, transposition |
| `chord_symbols.py` | Strict parser (aliases, unicode, slash chords) and configurable formatter |
| `harmony.py` | Diatonic triads and sevenths for any seven-note scale |
| `identify.py` | Chord identification from notes: ranked candidates, inversions, slash chords, rootless readings, omitted/added/altered tones, explicit "no reliable label" |
| `key_analysis.py` | Key estimation from pitch-class weights or chords, with alternatives and warnings; modulation candidates |
| `voicings.py` | Two-hand voicing generation: 9 left-hand and 11 right-hand styles, presets (beginner to expert, jazz, gospel, worship), configurable ranges/span/note counts/required and forbidden tones/tensions, playability checks |
| `voice_leading.py` | Cost model for voicings and transitions, style profiles, configurable weights, exact DP (or deterministic beam) choice of a whole sequence, explanations |
| `progressions.py` | Progression objects (chords, timing, numerals, roles, voicings, metadata), 18 data-driven templates, realisation in any key, transposition, substitutions and passing chords, validation, versioned JSON, walking bass |
| `midi_analysis.py` | MIDI note events to notes (tempo map, pairing), chord segmentation on a bar/beat grid, bass, key estimate, Roman numerals, editable hand assignment, mute/solo/merge/split tracks, playback lookups |
| `audio_interpretation.py` | Interpretation layer for audio chord estimates: label parsing (Harte and engine symbols), hypotheses with alternatives and warnings, pitch cross-check, key context, corrections kept apart from the original |
| `roman.py` | Roman-numeral analysis (diatonic, secondary dominant / leading-tone, borrowed, chromatic), numeral parsing back to chords, cadence candidates |
| `exercises.py` | 23 generated exercise kinds across every theory topic plus ear training; deterministic from `(kind, difficulty, seed)`; answers graded by the engine with spelling-aware feedback |
| `lessons.py` | Lessons: strict loader for authored lesson data, and engine-built examples (chord, scale, interval, sequence with Roman numerals) |
| `movements.py` | Chord-movement library: four derived levels per movement, definition (de)serialisation, publication checks, status rules |
| `relationships.py` | Facts about adjacent chords: common tones, root motion, P/R/L triad transforms, chromatic mediants, tritone-substitution pairs, least voice motion |
| `phrases.py` | Phrase candidates from harmony: function path, closing cadence, closed/open/interrupted character, plain-language description |
| `fingering.py` | Curated scale fingering lookup (`data/fingering.json`); returns None where nothing is curated |
| `validation.py` | Shared request limits and parsing helpers (keys, notes, counts) used by the API and any other caller |

## Decisions
- **Sounding pitch is an integer MIDI number; spelling is separate.** B#3 and C4 are the same pitch but different notes. Octave numbering follows scientific pitch (C4 = 60) and can be shifted with `middle_c_octave`.
- **Spelling comes from interval arithmetic, not lookup tables.** C + d5 = Gb, C + A4 = F#. At most two sharps/flats are supported; anything needing a third raises `spelling_overflow` instead of guessing.
- **Chord symbols are never guessed.** `Cmaj` is rejected (triad or seventh?), as is anything unrecognised. A root followed by `b`/`#` is read as an accidental, so `Db5` is D-flat power chord.
- **Chord types carry `omissible` tones** (e.g. the fifth of a ninth chord) for the identification step.
- **Scales are data.** `ScaleRegistry.copy()` + `register()` adds a scale with no code change; the shared defaults are not mutated.

## How the heuristics work
**Chord identification.** For every present pitch class as a possible root, and every chord type, a reading is valid only if all required tones are present and no unexplained note remains (a bass note outside the chord becomes a slash bass; `max_extra_tones` can allow more). Score = 4 x fraction of chord tones present, -0.6 per omitted tone, +2 root-position bass (+0.5 first/second inversion, -0.3 higher), -2 slash bass, -2.5 per extra tone, -4 rootless, plus a small prior (rarer types such as altered and quartal lose ties). Rooted readings scoring below 0 are dropped. Two readings within 1.0 of each other make the result `ambiguous`. The score is a ranking value, **not a probability**. Root spelling follows the caller's note names; for MIDI input it uses the fewest accidentals, then the key or sharps/flats preference.

**Key estimation.** Krumhansl-Schmuckler: Pearson correlation between a pitch-class weight profile and the 24 rotated Krumhansl-Kessler profiles. "Reliable" requires at least three distinct pitch classes. A gap under 0.05 between the top two keys is flagged as ambiguous (a relative major/minor pair is named). The chord-based ranking counts how many chords are diatonic to each key, adds bonuses for a tonic chord first (+0.1) and last (+0.15) and 0.1 x the profile correlation; it cannot separate relative keys by itself, and says so.

**Modulation candidates.** The best key of a sliding window of chords; a change that persists for two windows is reported with an approximate boundary. These are candidates only.

**Roman numerals.** Order of tests: diatonic (all chord tones in the key, minor key includes the raised seventh) -> applied dominant or leading-tone chord to a diatonic degree 2-7 -> borrowed from the parallel mode -> chromatic. A chord that fits both an applied reading and a borrowed one (D major in A minor: V/VII or IV from A major) reports the first and lists the other in `alternatives`. Numerals follow the spelling of the chord root, so respell before analysing if the spelling is unreliable. Function labels are simplified to tonic / predominant / dominant.

**Cadences.** Found from chord pairs only: authentic, plagal, deceptive, half (ends on V), Phrygian half. Without melody or phrase boundaries a *perfect* authentic cadence can only be suggested.

**Chord relationships.** For each adjacent pair: shared pitch classes (spelled as in the first chord), ascending root distance and its wording, and these labels, each a *description of the pair*, not a claim about intent. `transform_P/R/L`: two major/minor triads sharing two tones (same root; relative; leading-tone exchange). `chromatic_mediant`: same-quality triads a third apart sharing exactly one tone. `tritone_substitution`: dominant 7/9/13 chords a tritone apart. `smooth`: total pitch-class motion of 2 semitones or less. The least motion is a circular pitch-class matching (octave and register ignored), with unmatched tones counted when the chords differ in size (G7 to C leaves one tone unmatched). Slash basses are ignored. `non_diatonic` is set only when Roman numerals are available.

**Phrases.** Cadence candidates (see Cadences) close a phrase when it would hold at least `min_chords` chords (default 3); the strongest cadence at a position wins (authentic, plagal, deceptive, Phrygian half, half). A shorter leftover becomes its own phrase marked `short`. Each phrase reports its collapsed function path and whether it sounds closed (authentic/plagal), open (half), interrupted (deceptive) or has no cadence. Limits: harmony only, one key, and a mid-phrase plagal or authentic cadence is read as a boundary; the response carries `phrase_note` saying so.

**Administrator-defined scales.** Admins add scales as interval formulas under `/api/v1/admin/scales` (admin role only): create, edit (drafts only, with a revision check), preview, publish, unpublish, archive, restore, with a history of every change. The engine validates the formula before anything is stored (starts on P1, rises strictly, stays within an octave, descending form the same length). Preview shows the spelling on all twelve roots, flags roots that need double accidentals, and names built-in scales with the same pitch pattern. Publication is refused when an id or alias clashes with a built-in or another published scale; built-ins can never be replaced or shadowed. Only published scales reach `GET /theory/scales` and `POST /theory/scales/generate` (marked `builtin: false`); the registry is read from the database per request, so every worker sees a change at once, and a corrupt stored row is skipped, never fatal. Aliases use the same identifier form as ids, so a name an admin defines is one the API accepts. Limit: key detection, generated exercises and lessons keep using the built-in scales; custom scales do not affect them.

**Lesson authoring.** Educators and admins write lessons under `/api/v1/admin/lessons`. A lesson is text plus example *specifications* (a chord symbol, a scale, two notes, a chord list); no notes are typed, and the engine builds every example, so a written lesson cannot disagree with the engine that grades its exercises. The engine validates a lesson before it is saved (structure, every example built, exercise kinds, linked progression template). Workflow matches movements: draft, in review, approved, published, archived, with a history of every change; editing a lesson in review or approved returns it to draft, and a published or archived lesson cannot be edited. Publishing needs `approved`, at least one example, and every prerequisite already live (built-in or published); a lesson that other live lessons list as a prerequisite cannot be unpublished or archived. Preview returns exactly what a learner would see, with warnings that do not block (a section with no example, a single objective, a prerequisite of a harder level). Built-in lesson ids are protected. Published lessons join the learner curriculum after the built-ins, and the catalogue skips any stored row that no longer builds or whose prerequisite is missing, so a bad row never breaks the learner screens. Limits: English only; prerequisites are advice, not enforced for learners; the editor form covers the four example types, and anything beyond them still needs the JSON file.

**Scale fingering.** Curated, not computed: all twelve major scales and natural/harmonic minor on C, D, E, G and A, one octave, both hands; descending is the reverse. A test checks that no curated fingering puts the thumb on a black key. Other scales return `fingering: null`; fingering for chords and movements is still not generated.

**Voicings.** Each preset lists left-hand styles (bass note, octave root, root+fifth, open fifth, guide tones 3-7 / 7-3, shells R-3-7 / R-7-3, tenth) and right-hand styles (close and open triads, close seventh, extended, drop-2, spread, rootless A/B, guide tones, upper-structure triads, altered). Generation enumerates every placement of each style and keeps only voicings that pass `playability_issues`: hand ranges, per-hand span and note count, no shared or crossing notes, MIDI/piano bounds. It also requires the chord's third (and seventh unless a beginner triad deliberately omits it), the chord's own bass for slash chords and inversions, and any required/forbidden tones. Required tones a chord does not contain are ignored; forbidden tones are banned even as added colour. Defaults come from the skill level (span 9/12/14/16 semitones, 3/4/4/5 notes per hand) and every value can be overridden. Rootless voicings follow the Evans 3-5-7-9 (A) and 7-9-3-5 (B) shapes (13th replaces the fifth on dominants). Upper-structure triads: II, bIII, bV over dominant sevenths; V, II over major sevenths. Drop-2 in one hand spans 13-16 semitones, so it only appears at levels that allow that stretch.

**Voice leading.** Everything is a cost (lower is better), reported by component. Static: omitted chord tones (third and seventh cost most; the root costs little in rootless styles), added tensions, minor-second/ninth clashes, clusters and close intervals below C3, over-wide spans, distance from the preferred register, preferred inversion, and a small ease term. Transition: total voice motion, the largest single leap, held notes (a reward), bass motion, and parallel fifths/octaves. Parallels cost 10 in classical/strict-counterpoint mode, 0.5 in pop, 0.3 in worship and nothing in jazz and gospel. Voices are paired between chords by an order-preserving alignment; with equal note counts every voice is paired, otherwise each surplus note costs 4 semitones. `max_leap` is enforced as a hard limit first; if no sequence can meet it, it is relaxed with a penalty and the result says so.

**Sequence choice.** Exact dynamic programming over each chord's candidate list (sorted by static cost, default top 60), or a deterministic beam search for very large problems. Ties go to the earlier candidate, so results repeat exactly. DP is optimal *over the candidate lists*: pruning to the top candidates by static cost can exclude the global optimum, so raise `max_candidates` when exactness matters. A 16-chord jazz progression takes about 2 seconds; API endpoints should cap the number of chords and candidates.

**Progressions.** A `Progression` holds structured chords with beat positions and durations, Roman numerals, a role (main / passing / substitution), an optional voicing (the left/right hand split lives in the voicing), difficulty, style tags, explanation and publication metadata (author, source, status, revision). Templates are rows in `data/progressions.json` with a triad and a seventh-chord version of each chord; `realize` builds them through the numeral parser, so ii-V-I in C is Dm / G / C with triads and Dm7 / G7 / Cmaj7 with sevenths. Administrators add templates with `ProgressionLibrary.copy()` + `register`; each numeral is checked against a reference key on load.

*Transposition* re-derives every chord from its Roman numeral rather than shifting letters, so Db major gives Ebm7 Ab7 Dbmaj7 and F# major gives G#m7 C#7 F#maj7. If a chord has no numeral or the numeral disagrees with the chord, it falls back to interval transposition with respelling for the new key. The bass keeps its relationship to the root. Voicings shift by the shortest semitone move (-6..+5); if any becomes unplayable under the constraints, `on_unplayable` chooses between regenerating all voicings smoothly (default), dropping the bad ones, or raising an error. The mode cannot change.

*Substitutions and passing chords* keep total length: a tritone substitute replaces a dominant 7/9/13 with the dominant a tritone away (G7 to Db7); a secondary dominant is inserted in the first half of its target chord; a passing diminished seventh goes a half step below the next chord's root in the second half of the previous chord.

*Validation* separates errors (structure, timing overlaps, unparseable symbols, voicing outside the chord, unplayable voicing, wrong bass, crossing hands, MIDI/piano bounds) from warnings (timing gaps, late start, incomplete bar, chord outside the key, numeral that disagrees, lowest note not the root, missing third). `strict_harmony` turns the harmonic warnings into errors for lessons that define strict rules; `publication` adds the requirements for publishing (author, explanation, style tag, numerals); `deep` tests transposition into every key. Dominant sevenths on I/IV/V are not flagged in progressions tagged "blues".

*Storage.* `progression_to_dict` / `progression_from_dict` use a versioned schema (currently 1). Older data is upgraded by registered migration steps, newer data is refused, and malformed data raises an error that names the failing path.

*Walking bass* writes one quarter note per beat: the root on each chord's first beat, chord tones between, and a chromatic approach note on the last beat before the next chord. It needs whole-beat chord lengths and assumes four-beat patterns; it has no swing or rhythmic variation.

**MIDI analysis.** Events are paired into notes (note-on with velocity 0 is a note-off; repeated notes pair first-on with first-off; stray offs, unreleased and zero-length notes produce warnings, not crashes) and mapped to beats and seconds through the tempo map. Analysis cuts the music into cells of one counted beat, half a bar or a bar (compound metres count dotted beats; time-signature changes start new bars; nothing is analysed after the last note ends). In each cell, notes sounding for less than 20% of it are treated as passing tones; the rest are identified with the same engine as everything else, retrying with one extra tone allowed only if nothing else fits. Adjacent cells with the same best chord merge. The key is the one you pass, otherwise the Krumhansl-Schmuckler estimate if it has at least three pitch classes; with no key there are no Roman numerals. Segments from MIDI (`origin "midi"`) are built from known pitches and are a different type from audio hypotheses.

*Hands* are suggestions with a recorded source ("auto" or "user"). Clearly low or high notes go left or right; notes near middle C follow the nearest recent note; a compact cluster stays in one hand; a hand never exceeds five simultaneous notes; the left hand never crosses above the right inside a cluster. Track numbers are ignored on purpose. Edits never modify the original assignment. Mute/solo: if anything is soloed only soloed, unmuted tracks sound; otherwise everything not muted.

**Audio interpretation.** Each region becomes a `ChordHypothesis` (origin "audio"), never a bare chord. The raw model score is exposed as `model_score` and is **never** called a probability: `confidence` is set only when the pipeline names the calibration that justifies the number. Close raw scores, a label that is not the top-scoring one, detected pitches that suggest another chord (shown as alternatives from "pitch_evidence"), a missing root or third, a bass note that implies an inversion or slash chord, very short regions, and label-only regions all produce warnings, and the first three mark the hypothesis "ambiguous". Unrecognised labels are kept verbatim with status "unrecognised_label"; nothing is remapped. Key context uses the chord-based ranking and states when it is uncertain. Corrections (relabel, retime, add, delete) return a new `CorrectedAnalysis`: the original estimate is never changed, each change is recorded with its before and after, and invalid edits (overlaps, bad labels) are rejected without altering anything. The audio feature extraction and model inference themselves belong to the audio worker (a later phase); this layer only interprets their output.

## Known limits
- The altered dominant (`7alt`) is defined as R 3 b5 b7 b9 #9 b13 with most tones omissible; other texts define it differently.
- `quartal3`/`quartal4` are stacks of fourths, not tertian chords; their symbols are non-standard.
- Dominant 11th and 13th formulas are the full stacks; real voicings usually omit the third or eleventh.
- Triple accidentals are unsupported (e.g. G### needs the enharmonic respelling).
- Identification covers only the chord types in the table; richer extensions need `max_extra_tones` and are flagged as extras.
- Chord-quality readings of two-note sonorities are deliberately refused.
- Template difficulty labels are authored judgments. Tritone substitution applies only to dominant 7th/9th/13th chords. The movement library is documented below.
- Voicing styles are rule-based; they produce valid, playable options, not a guarantee of what a particular pianist or genre would choose. Fingering is not generated.
- Hand assignment and chord segmentation are heuristics tested on synthetic material, not validated against human-annotated performances. MIDI sustain pedal is ignored, so pedalled passages read as their played notes.
- Key estimation assumes a major/minor tonal centre; modal or atonal music gives weak fits (warned).

## Movement library
`movements.py` builds a *movement*, one progression at up to four levels, from a small `MovementDefinition` (key, a template or custom chord symbols, tempo, tags, texts). Everything musical is derived with the same code as the rest of the engine (`realize`, `voice_progression`, `validate_progression`):

| Level | Chords | Voicing recipe |
|---|---|---|
| beginner | triads | `beginner` preset, root-position right hand preferred, "root position" search weights |
| intermediate | sevenths | `intermediate` preset, balanced weights |
| advanced | sevenths | `advanced` preset (shells, guide tones, rootless, drop-2), smooth weights, jazz parallels profile |
| expert | sevenths + tritone substitutes | `expert` preset, M9 tension allowed, smooth weights |

- **Substitutions** are applied at expert level only where a dominant 7/9/13 resolves down a fifth (V to I). A movement with no such chord keeps its dominants and says so in its variations. Substitutes are respelled with the fewest accidentals (D7, not E-double-flat 7; E7, not F-flat 7).
- **Custom chords** are used as written at every level: the author chose the vocabulary, so only the voicing differs.
- **Deterministic.** The same definition always builds the same result. What learners see is a *snapshot* frozen at publication (`generator_version` records the engine that made it), so improving the voicing engine later does not silently change reviewed content. Transposed views are built live and are labelled as such.
- **Publication needs** an author, a theory explanation, at least one tag, no validation errors in any level, and the engine's `publication` checks. Warnings do not block.
- **Status rules** (`TRANSITIONS`): draft, under review, approved, published, archived. Publishing requires approved. Unpublish returns to approved, restore returns an archived movement to draft.
- Limits: expert substitution is narrow by design; voicings are rule-based suggestions; practice text is a default unless the author writes their own; building all four levels takes about 1-3 s (the 12-bar blues about 3.4 s on the development machine), so the building routes are rate-limited.

## Audio Analyzer
See `docs/adr/0009-audio-analyzer.md`. The browser estimates chord regions from the sound; `audio_interpretation.py` interprets them (symbols, ambiguity, key, numerals, corrections) and never reports a confidence it has not been given a calibration for.

## MIDI Studio
See `docs/adr/0008-midi-studio.md`. The browser reads the file; the analysis service uses `midi_analysis.py` and the chord, key and Roman numeral code above.

## Lessons
See `docs/adr/0007-lessons.md`. `lessons.py` loads `data/lessons.json` and builds each example with the same engine that marks the exercises.

## Exercises
**Accepted answer forms.** The answer shown after a wrong attempt is always something the grader accepts when typed back (a test checks every exercise kind at every difficulty). Interval answers may carry their written name, `m3 (minor third)`; if the two halves disagree the answer is refused, not guessed. Answers to "Which major/minor key..." may end with the matching word (`D major`); a *wrong* word is marked incorrect and explained. A black key may be answered `D#`, `Eb` or `D# / Eb`.

The browser practice screen (`/theory`) uses these generators and the grader. Graded answers are recorded for progress (see `docs/adr/0006-exercise-attempts.md`).

`generate_exercise(kind, difficulty, seed)` returns what a learner sees; `validate_answer(exercise_id, answer)` grades it.

- **Stateless.** An id is `v1:<kind>:<difficulty>:<seed>`. Grading regenerates the exercise from the id, so the server stores nothing and the client never supplies (or sees) the answer before answering. Changing what any generator produces for a seed requires bumping `GENERATOR_VERSION`; old ids then fail with `unsupported_exercise_version` rather than silently meaning something else.
- **The engine decides.** Expected answers come from the same note, interval, scale, chord, numeral and cadence code as the rest of the platform, never from a language model. A generated example that could be read two ways (A C E G is Am7 and C6/A) is rejected and redrawn, and an answer that holds the same notes with the same bass is accepted as a valid reading. Cadence and chord-identification examples are cross-checked against `find_cadences` and `identify_chord` while generating.
- **Four levels of correct.** `correct`; `enharmonic` (right pitches, other spelling: counts as correct where the exercise cannot tell spellings apart, such as a highlighted key, and not where spelling is the point, such as spelling a scale); `partial` (right chord, missing slash bass); `incorrect`. Text that cannot be read at all is `unreadable` and explains the expected format. A list where text was expected is an error (`invalid_answer`), not a grade.
- **Feedback names the mistake**: which scale degree is misspelled, which notes are missing or extra, how many semitones the given interval spans against the real one.
- **Ear training** exercises have an empty `show`, prompts that do not contain the answer, and `play` events (notes, start and duration in beats) for the client's audio engine. Generated examples are deterministic.
- **Topics covered:** notes, intervals (identify and build), scales, key signatures, triads and seventh chords (build and identify), inversions, diatonic chords, Roman numerals (both directions), progressions, voice leading, cadences, secondary dominants, borrowed chords, extensions, substitutions, and ear training for intervals, chord quality and cadences. `list_kinds()` gives each kind's topic, objective and optional prerequisites.
- **Not here:** lesson prose, keyboard visualisation and audio playback belong to the lesson phase; this module supplies the examples and the checking.

## HTTP API
All routes are under `/api/v1/theory`, need a signed-in user, and are documented in the OpenAPI page (`/docs`). Requests reject unknown fields. Musical errors return HTTP 422 in the standard envelope with a stable `error.code` (for example `unknown_quality`, `invalid_inversion`, `unplayable_voicing`, `invalid_progression_data`); schema errors are `validation_error`.

| Route | Purpose |
|---|---|
| `POST notes/identify` | Name, MIDI number or frequency to a note; enharmonics; cents; configurable A4 and octave convention |
| `POST intervals` | Interval between two notes, or the note an interval above/below a root |
| `GET scales`, `POST scales/generate` | Scale or mode on any root, degrees, keyboard notes, optional diatonic chords, curated fingering when available |
| `GET chords/types`, `POST chords/construct` | Chord from symbol or root and type; inversion; notes and MIDI numbers; symbol style |
| `POST chords/identify` | Ranked readings or "no reliable label" |
| `POST keys/estimate`, `POST harmony/analyze` | Key candidates; Roman numerals, cadences, modulation candidates, chord relationships, phrase candidates |
| `GET progressions/templates`, `POST progressions/generate`, `transpose`, `validate` | Progression objects, optionally voiced; transposition; validation report |
| `POST voicings/generate`, `voicings/sequence`, `voice-leading/evaluate` | Options for one chord; best sequence; score someone else's voicings |
| `POST midi/analyze` | Chords, key, numerals and editable hand suggestions for note events; mute/solo |
| `POST audio/interpret` | Interpret the audio worker's chord estimates and apply corrections (no audio is processed here) |
| `GET exercises/kinds`, `POST exercises/generate`, `validate` | Exercises as above |

**Limits** (`validation.py`, also enforced in the schemas): 24 notes to identify, 64 chords per progression, 16 chords per voicing search, 80 candidates per chord, 200 voicings returned, 20,000 MIDI events, 2,000 audio regions, 200 corrections. Per-IP rate limits: 600 requests a minute overall and 30 a minute for the combinatorial routes (voicings, progressions, MIDI, audio).

**Measured worst cases** on the development machine: a 16-chord expert voicing search at 80 candidates about 3 s; a 20,000-event MIDI request of random dense notes (an adversarial case) about 2 s; 2,000 audio regions 0.3 s; everything else well under 0.2 s. A profile of the first version of MIDI analysis showed it re-scanning every note for every grid cell (177 s at 50,000 events); it now sweeps a window of sounding notes, and a test guards against the regression.

Scores in responses are rankings, not probabilities, and each response that has them says so (`score_meaning`, `evidence_note`).

## Known limits
- The altered dominant (`7alt`) is defined as R 3 b5 b7 b9 #9 b13 with most tones omissible; other texts define it differently.
- `quartal3`/`quartal4` are stacks of fourths, not tertian chords; their symbols are non-standard.
- Dominant 11th and 13th formulas are the full stacks; real voicings usually omit the third or eleventh.
- Triple accidentals are unsupported (e.g. G### needs the enharmonic respelling).
- Identification covers only the chord types in the table; richer extensions need `max_extra_tones` and are flagged as extras.
- Chord-quality readings of two-note sonorities are deliberately refused.
- Template difficulty labels are authored judgments. Tritone substitution applies only to dominant 7th/9th/13th chords. The movement library is documented below.
- Voicing styles are rule-based; they produce valid, playable options, not a guarantee of what a particular pianist or genre would choose. Fingering is not generated.
- Hand assignment and chord segmentation are heuristics tested on synthetic material, not validated against human-annotated performances. MIDI sustain pedal is ignored, so pedalled passages read as their played notes.
- Key estimation assumes a major/minor tonal centre; modal or atonal music gives weak fits (warned).
- Exercise difficulty levels are authored pools (which roots, qualities and intervals appear at each level), not measured against learner data. Exercise feedback is templated text, not adaptive. The ear-training material is generated as note events; how it sounds depends on the client's audio engine.
- The API serves signed-in users only. Larger MIDI files and anything that needs audio analysis are for background jobs (later phases).

## Still to build
The movement library, lessons and keyboard visualisation (later phases) use this engine. Not planned yet: augmented-sixth chords, modal (non-major/minor) key detection, computed fingering.
