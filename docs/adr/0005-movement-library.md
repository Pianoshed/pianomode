# 0005 Chord-movement library and content workflow

## Decisions
**Store the definition, derive the notes.** A movement is saved as a small definition (key, template or chords, tempo, tags, texts). The four levels are built by the theory engine, so voicings are never hand-typed, always playable and always validated.

**Freeze what was reviewed.** Publishing stores the built result as a snapshot and learners read the snapshot. A later engine change cannot alter published content; the snapshot records `generator_version`. Transposed views are built live (`live: true`) because they were never reviewed, and the page says so.

**Review before publication.** Statuses are draft, under review, approved, published, archived. Publishing needs *approved* and passes the publication checks (author, explanation, tag, no validation errors at any level). A published movement cannot be edited (unpublish first), editing after review returns it to draft, and edits carry the revision they started from so two editors cannot overwrite each other. Every change is appended to the movement's history.

**Permissions are server-side.** Admin routes require the educator or admin role. The web page hides itself from other users, but the API refuses them regardless (tested, and checked in the browser test).

**Seeding goes through the same gate.** `scripts/seed_movements.py` publishes the built-in templates using the normal build and publication checks. A template that failed them would be reported, not forced through.

## Limits and consequences
- Any educator or admin can perform every transition; there is no separate reviewer role or four-eyes rule yet.
- The edit form supports template-based movements. Custom-chord movements can be created and edited through the API only.
- Learner lists are filtered in memory after a bounded query (500 rows). That is fine for hundreds of movements, not for tens of thousands.
- Editing a published movement requires a short period when it is not visible. This is deliberate.
- Progress tracking (what a learner has practised) is not built; it belongs with lessons.
