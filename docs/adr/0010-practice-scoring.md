# 0010 Advanced practice tools: plan and step 1 (scoring)

Phase 7 had no written scope. This is the build plan, in the order it will be built. Each step is finished, tested and documented before the next starts, and none is dropped.

| Step | What | Status |
|---|---|---|
| 7.1 | Performance scoring engine and `POST /api/v1/practice/score` | **done** |
| 7.2 | Practice clock in the browser: metronome, tempo scaling, count-in, loop regions, speed trainer (pure, tested functions) | **done** |
| 7.3 | Practice Room: uses 7.2, hand isolation, captures notes from a MIDI keyboard or the on-screen piano, scores them with 7.1 | **done** |
| 7.4 | Wait mode: the music waits for the right notes before moving on | **done** |
| 7.5 | Saved practice results and progress over time (per learner, owner-only) | **done** |
| 7.6 | MIDI Studio: save corrections and export edited MIDI | **done** |

## 7.1 Scoring

**Where it lives.** `music_theory/performance.py` (pure, no database), exposed by `POST /api/v1/practice/score` (signed-in users, rate limited). Scoring is stateless: nothing is stored by the call. Saving comes in 7.5.

**Input.** What should be played: explicit notes (MIDI pitch, start beat, duration, hand, chord index), or a published movement version chosen by slug, level, optional key and hand. What was played: note-on times (and optional note-off) in seconds. Also tempo (the movement's, or a slower practice tempo), the time of beat 0 (so a count-in is allowed), an optional known input latency, a level or an explicit timing window, an optional octave-equivalence switch, and an optional beat range so a loop is scored on its own.

**Output.** Per expected note: on time, early, late, missed or near miss, with the signed error in milliseconds. Extra notes with their beat. Per chord: complete or not, and how far apart its notes were played. Per hand: accuracy. Timing figures (mean, mean absolute, median, spread). Short plain-language feedback. The limits that apply, in the response.

**Decisions and why.**
- *Matching never lets one played note satisfy two expected notes.* The window is capped at half the gap to the next expected note of the same pitch, and the closest played note inside it wins. Otherwise fast repeated notes could be scored perfectly with half the presses.
- *Near misses are reported as such.* A missed note with an unmatched note one or two semitones away at about the same time reads as "you played F-sharp instead of F", which is more useful than a miss plus an unrelated extra.
- *No single grade.* The result gives counts and percentages and says how many notes they rest on.
- *A rush or drag tendency needs at least 8 hit notes and an average error of at least 20 ms.* Below that the response says there are too few notes to say. Both numbers are rules of thumb, not measured thresholds.
- *Level sets the window:* beginner 250 ms, intermediate 150, advanced 90, expert 60. These are teaching defaults, not standards; `window_ms` overrides them.
- *Two expected notes of the same pitch at the same time are refused*, because one keyboard cannot play both.

**Limits.**
- It judges notes and timing only. Touch, velocity, tone, pedalling and musicality are not scored.
- Timing includes any delay from the keyboard, browser or audio device unless `latency_ms` is given. A step later will measure it; until then a constant lag looks like dragging.
- Hand assignment comes from the movement data; it is not detected from what was played.
- For a loop, `offset_s` must be the time of beat 0 even when the player began mid-piece.

**Tests.** 40 engine tests (matching, window edges, repeated notes, count-in and latency, tempo, near misses, chords, hands, held length, tendency honesty, validation codes, determinism, and property tests that the counts always add up) and 27 API tests, counting parametrised cases (explicit and movement sources, hand and key selection, loops, validation, errors with stable codes)).

## 7.2 Practice clock and metronome

**Where it lives.** `frontend/lib/practice/clock.ts` (pure: no audio, no React, no real clock) and `frontend/lib/practice/metronome.ts` (a lookahead scheduler and the click sound). `PianoAudio` gained a read-only `context` getter so the metronome and the piano can share one audio clock.

**A practice plan** says how a piece is practised: base tempo and speed percentage, beats per bar, an optional loop, a number of passes (or open-ended), a count-in (once, or before every pass), and an optional speed trainer (start percentage, step, every N passes, target). The clock answers: when each pass starts, which beat is sounding at a given second, when each click falls, which notes sound in a pass (muted hands left out, notes cut at the loop end), and which values to send to the scoring API for a pass.

**Decisions and why.**
- *One timeline, in session seconds.* Seconds start at 0 when the plan starts, count-in included. The notes the player records are timed in the same seconds, so scoring needs no conversion.
- *Scoring hand-off is derived, not re-implemented.* `scoringParams(plan, pass)` returns the pass's tempo, the session time of beat 0 (even when a loop starts mid-piece) and the beat range. A test checks that `offset + beat * 60 / tempo` equals the second each note is scheduled, for every pass of a looped, counted-in, speed-ramped plan, which is the formula the scoring engine uses.
- *The audio clock keeps the time, not timers.* Browser timers run late and unevenly. The scheduler wakes every 25 ms, looks 200 ms ahead and hands each click to the audio clock with its exact time. If the page was frozen for longer than 100 ms, the missed clicks are dropped and counted, not played in a burst.
- *The bar grid belongs to the piece.* A loop that starts mid-bar still accents the piece's bar lines. Clicks fall on whole beats, so a loop that starts between beats clicks from the next whole beat.
- *Beats are the movement's own unit.* A bar holds the time signature's numerator, so 6/8 clicks six times a bar. Compound-meter feel (two big beats) is not modelled.
- *Limits are enforced and named.* Tempo 20 to 400 BPM, speed 10% to 200%, count-in up to 16 beats, at most 500 passes, loops of at least one beat inside the piece. `planProblems` lists every reason a plan cannot be played.

**Limits.**
- Nothing in the app uses this yet; the practice screen (7.3) wires it to the piano, the movement and scoring.
- It does not measure the delay between a key press and the browser hearing it. Until it does, scoring shows that delay as dragging.
- Starting playback needs a user gesture (a browser rule), which the practice screen will provide.
- The click is a synthesized sine blip. There is no choice of click sound.

**Tests.** 34 clock tests (tempo clamping, loop validation and snapping, plan checks, speed trainer, count-in and position, loops, clicks and accents, notes of a pass, scoring hand-off) and 13 scheduler and sound tests (ahead-of-time scheduling, exact times, end handling, stop and restart, dropped clicks, open-ended loops, count-in pitch, the click blip, zero volume), all on a fake clock with no real audio.

## 7.3 Practice Room (`/practice`)

One screen, three tabs, one shared keyboard. **Play along:** pick a movement, level, key and the hand(s) you play; set speed, count-in, metronome, an optional loop over a range of chords with a number of passes, and an optional speed trainer. The computer plays the other hand (or both, in "listen first"). Your notes, from the on-screen keys, the computer keyboard or a MIDI keyboard, are recorded in session seconds and, when the run ends, each *finished* pass is scored by the server (step 7.1) with the pass's own tempo, offset and beat range from the clock (step 7.2). Results show per-pass accuracy, timing tendency (only with enough notes), per-hand results, plain feedback, and the limits.

**Decisions.**
- *Sound and clicks share one audio clock.* Notes are scheduled one pass ahead with `PianoAudio.scheduleAt` at the scheduler's origin, so a loop of any length never schedules more than two passes of notes.
- *The sound delay is removed from scoring.* The browser's reported output latency is used as the default (editable). Without it a player in time with what they hear would look late. Keyboard hardware delay is not measured.
- *Only finished passes are scored.* Stopping mid-pass says so instead of scoring a partial pass. A run in which no key was pressed is not scored or saved.
- *Results are computed by the server*, not reported by the browser. Saving a pass sends only the session id and pass number; the stored figures come from the scoring response.
- *Payloads stay small:* only the notes near a pass (half a second either side) are sent, at most 30 passes per run.

## 7.4 Wait mode

The music waits until every note of the chord shown has been played (any order, any time); any other note counts as a wrong note on that chord, and playing a wanted note twice is not a mistake. A chord is "first time" if it had no wrong note. Chords that ask nothing of the chosen hand are skipped. The result is chords first time out of chords asked, plus wrong notes. Octave-equivalence is optional. `lib/practice/wait.ts` is pure.

## 7.5 Saved results and progress

`practice_attempts` (migration 0007) holds one row per scored pass or wait run: movement, level, key, hands, tempo, window, counts, mean error and tendency. **The notes played are never stored.** Endpoints: `POST /practice/score` with `save`, `POST /practice/wait-results`, `GET /practice/history` (latest 50 and per-movement-level-mode progress: attempts, best, latest, fastest tempo with 90% or better on 8+ notes), `DELETE /practice/attempts/{id}`, `DELETE /practice/history`. Results are owner-only: another learner's result looks like a missing one (404). The newest 2000 results per learner are kept. Limit: wait-mode results are reported by the browser (there is nothing to recompute on the server), so they are the learner's own record, not evidence for anyone else.

## 7.6 MIDI Studio: export and corrections

`ExportPanel` adds **Download edited MIDI**, **Save corrections** and **Load corrections**. The exported format-1 file carries a tempo-map track and one track per part after the person's merges and splits, named with the assigned hand; muted tracks are left out (and all non-solo tracks when any is soloed) unless asked; notes whose hand was corrected by hand go into "Left hand (corrected)" and "Right hand (corrected)" tracks. The corrections file holds choices only (track edits, track settings, hand corrections, key, grid, spelling), never the music, is limited to 1 MB, is checked field by field when loaded, and is refused if it was saved for a different file (resolution and note count). Limits: lyrics, controllers and pedal events are not in the exported file; per-note hand corrections only exist for sections that were analysed.

## Verification (end of Phase 7)

Tests were written and run once at the end, as requested. Backend: scoring (40 engine, 27 API), saved results (18), plus the existing suite. Frontend: clock (34), metronome (13), wait mode and recorder (12), MIDI writer, export and corrections (23). The Practice Room component and the Studio export panel are covered by the type checker and the production build, not by browser tests; they have not been exercised in a real browser with real audio or a MIDI keyboard.
