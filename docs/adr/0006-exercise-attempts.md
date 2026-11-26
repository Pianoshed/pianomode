# 0006 Recording exercise attempts

## Decisions
**Exercises stay stateless; only results are stored.** An exercise id (`v1:kind:difficulty:seed`) regenerates the exact question, so nothing about the question needs saving. Each graded answer stores user, exercise id, kind, difficulty, status and whether it was correct. It does not store the learner's typed answer or the question text.

**Unreadable answers are not attempts.** If the engine cannot parse an answer (for example `???` as a chord symbol) the learner is asked again and nothing is recorded, so a typo cannot lower someone's record.

**Progress is plain counts.** The API returns attempts, correct answers, and the last 10 attempts per kind and difficulty. There is deliberately no "mastered" label: nothing yet shows what threshold would be meaningful.

**Recording happens in the existing validate route.** The route already required sign-in, so the API surface did not grow for recording; `GET /api/v1/theory/exercises/progress` is the only new route, and it returns only the caller's own rows.

## Limits and consequences
- The same exercise answered twice counts twice.
- Only the most recent 5,000 attempts per learner are considered when summarising.
- Deactivating an account keeps its attempts (the user row is kept); a hard delete would remove them through the foreign key.
- Prerequisite advice on the screen is soft: it names kinds the learner has not tried and never blocks anything.
- A practice screen is not a lesson. Explanatory lessons (objectives, worked examples, difficulty progression across topics) are still to be built.
