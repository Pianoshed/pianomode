# 0004 Theory API and generated exercises

## Decisions
**Sign-in required.** Every theory route needs a session. The product is account-based, and some routes are combinatorial (voicing search, MIDI analysis), so an anonymous endpoint would be an easy way to burn CPU. Per-IP rate limits apply on top (600/min overall, 30/min for the heavy routes).

**Synchronous, bounded, no audio inference.** Theory calculations run in the request, but every collection has a limit (`music_theory/validation.py`, mirrored in the schemas) chosen from measured worst cases. Audio analysis is a background job; `/audio/interpret` only interprets estimates a worker already produced. Anything over the limits (long MIDI files) is for a job, not a bigger request.

**Stateless exercise ids.** `v1:<kind>:<difficulty>:<seed>` regenerates the exercise, so grading needs no database row and the browser never holds the answer. The cost: a generator change for an existing seed must bump `GENERATOR_VERSION`, and exercises cannot (yet) record attempts or progress; that belongs with the lessons phase, which can store attempts keyed by exercise id.

**Errors.** `TheoryError` maps to HTTP 422 with its own stable `code` in the standard envelope; `generation_failed` (our fault) is 500. Wrong-shaped answers are errors; understandable-but-unreadable answers are graded `unreadable`, so the interface can ask again.

**Stored progressions** go through `migrate_progression_data` before parsing, so older saved content keeps loading.

## Consequences
- The web client can be generated from the OpenAPI document; responses are typed.
- A hosted audio worker can call the same interpretation endpoint's service function without HTTP.
- Raising a limit is a deliberate change to one constant plus its schema twin, and should come with a new measurement.
