# Piano end-to-end test

Drives the real web app and the real API in headless Chromium: sign in, play keys with the mouse
(including a glissando), the computer keyboard and chords, check the theory marks, identification
(including the ambiguous and no-chord cases), scale spelling, two-hand colouring, audio nodes
actually starting, preferences, dark-theme contrast, the sticky stage on desktop and phone.

```
# terminal 1 (backend dir): API on in-memory SQLite with a verified learner
python scripts/e2e_server.py
# terminal 2 (frontend dir): production build, served on :3000
npm run build && npm run start
# terminal 3 (frontend/e2e): the browser test; saves screenshots to /tmp/shots
npm install && node piano.e2e.mjs
```

Notes
- It removes `--disable-web-security` from the bundled Chromium's flags. With that flag the browser
  omits the `Origin` header on same-origin POSTs, which the API's CSRF check (correctly) refuses.
- Not in CI because it needs a browser; the unit, render and API tests cover the logic in CI.

## Movement library test
`node movements.e2e.mjs` (same three-terminal setup; the e2e API server also creates an educator,
`teacher@example.com`, and publishes the built-in movements). It checks browsing and search, the four
levels, compare, hand isolation, playback starting real audio, transposition spelling, the learner
being refused on admin routes, a phone-width layout, and an educator creating, editing, checking and
publishing a movement that then appears for learners.

## Theory practice test
`node theory.e2e.mjs` (same setup). It works out the right answer to "name the highlighted key" from the
keyboard's own labels and checks the engine marks it correct, checks unreadable answers are not recorded,
answers a chord-building question by pressing keys, plays an ear-training exercise (real audio), checks
progress survives a reload, and checks the phone layout.

## Lessons test
`node learn.e2e.mjs` (same setup). It checks the curriculum and its grouping, engine-built examples on the
keyboard (notes, Roman numerals, a clicked chord), real audio from Play, the prerequisite advice, the
lesson to practice link opening the right exercise, then answers five exercises through the real UI and
checks the lesson becomes Practised and the suggested next lesson moves on. Also checks the phone layout.

## MIDI Studio test
`node midi.e2e.mjs` (same setup). Loads the built-in example and real `.mid` files written by an independent
Python writer (`backend/scripts/make_test_midi.py` regenerates them), then checks: the chords and numerals,
alternative readings on the keyboard, hand editing by mouse and keyboard (and that it costs no request),
mute/solo/merge/split reaching the server correctly, hand tags, playback and the playhead, one-hand playback,
bad files (not MIDI, SMPTE), an oversized file analysed in sections, a rate limit that is explained and
recovered from, that a control scrolled into view is not hidden by the sticky panel, and the phone layout.

## Audio Analyzer test
`node audio.e2e.mjs` (same setup). Builds its own WAV files in Node (independent of the app's synthesiser): a
44.1 kHz stereo file goes through the browser's real decoder and resampler. Checks the example's chords,
that every chord is described as an estimate with no percentage anywhere, the keyboard showing the heard
chord, relabel/move-boundary/split/join/remove/add corrections (including the order the server needs),
that the server's refusal of an unreadable chord is shown and nothing is kept, the confirm step before
settings replace corrections, playback with the keyboard following, the key being honestly uncertain for
a progression that fits two keys, silence reported as no chord, bad/too-short/too-long files refused with
reasons, cancelling a long analysis, and the phone layout.

## Production-build checks

`security.e2e.mjs` and `subscription.e2e.mjs` run against the production build: build with
`NEXT_OUTPUT=standalone npm run build`, copy `.next/static` and `public` next to
`.next/standalone/server.js`, start it with `PORT=3000 API_INTERNAL_URL=http://localhost:8000 node server.js`,
start the e2e API server (`backend/scripts/e2e_server.py`) and run `node e2e/security.e2e.mjs`.
It fails on any Content-Security-Policy violation, console error or failed request on every main page.
