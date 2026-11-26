# Interactive piano

Page: `/piano`. Logic lives in `frontend/lib/piano/` as small pure modules (unit-tested); the React
components in `frontend/components/piano/` only draw what those modules decide.

## What it does
- **88 keys, A0 to C8**, played with mouse or touch (several fingers at once, sliding across keys for a
  glissando, harder presses lower on a key), the computer keyboard (physical key positions, so any
  layout works), or a MIDI keyboard (Web MIDI: Chrome and Edge). Arrow keys move between keys and
  Enter or Space plays, so it is usable without a pointer.
- **Five synthesised sounds** (grand, electric piano, organ, strings, bells) that can be layered up to
  three at a time, with a volume, a sustain pedal (button, Space, or a MIDI pedal) and a stop button.
  They are generated with Web Audio, not recorded, so there are no sample files or licences to manage;
  they are approximations of the instruments and the interface says so.
- **Theory on the keys**, all from the theory API (nothing is worked out in the browser):
  - *Chord*: pick a root and type or type a symbol (`Dm7/C`), choose an inversion and octave, show the
    chord tones in every octave, or show a suggested two-hand voicing (left hand blue, right hand
    amber). Roots, intervals (R, 3, ♭7), bass notes and extra notes are marked.
  - *Scale*: any scale or mode, every octave, with scale degrees.
  - *What am I playing?*: names the keys you just played, including inversions and slash chords,
    lists other readings when the notes could be named more than one way, says so plainly when no
    chord name is reliable, and shows each reading on the keys. Ranking is described as a judgement,
    not a probability.
- **Spelling follows the theory.** F♯ major labels the F key E♯; G♭ major shows G♭, not F♯. Otherwise
  the keys follow your sharps/flats choice. Middle C can be called C3, C4 or C5, and A4 can be
  415 to 444 Hz.
- **Marks use shape as well as colour** (the bass note is a square) and every key's accessible name says
  its note, role, interval and hand.
- A **sticky stage** keeps the keyboard, a one-line readout ("Showing Cmaj7", "You played Am7, or
  C6/A") and the legend on screen while you use the controls below.

## Decisions
- **Marks have fixed colours, not theme colours.** The keys stay ivory and ebony in both themes (as on
  the instrument), so the marks on them must too. An earlier version used the theme's soft accent and
  its labels were unreadable in dark mode; the browser test now measures contrast.
- **Response types are written by hand and checked against real responses.**
  `backend/scripts/export_theory_fixtures.py` writes API responses into `lib/piano/__fixtures__/`;
  the tests assign them to the TypeScript types, so an API change fails `npm run typecheck`.
  (Generating the types from the OpenAPI document would be better once more screens use the API.)
- **Preferences** (labels, sharps or flats, key size, sounds, volume, tuning, octave convention) are kept
  in `localStorage` after the page loads, validated field by field on read.
- **No touch scrolling on the keys**: the keys capture touches for playing, so the keyboard is moved
  with the overview strip, the octave buttons, or the scroll bar.

## Testing
- `npm test`: 80+ unit tests for geometry and hit-testing, labels and spellings, key maps, held notes,
  sound plans, preferences, MIDI parsing, the highlight builder, and the API client (with a mocked
  `fetch`), plus server-render tests of the keyboard and the whole workspace.
- `frontend/e2e/`: a browser test against the real API in headless Chromium (see its README). It checks
  playing, the theory marks, identification, audio nodes starting, dark-theme contrast, and the sticky
  stage on a desktop and a phone. It is not in CI because it needs a browser.

## Known limits
- Browser sound could only be verified as "the audio graph builds and starts oscillators without
  errors"; how the sounds *sound*, and latency on real hardware, need ears and a real device.
- Not tested on Safari, Firefox or a physical phone or tablet, and not with a screen reader.
- Web MIDI is untested with a real device (the message decoding is unit-tested).
- The sounds are simple synthesis. A sampled grand piano would be more realistic but needs licensed or
  recorded samples and a download strategy.
- Some text in the self-hosted font renders with a gap before commas and full stops in the headless
  test browser (also on the existing dashboard); check it in a normal browser.
- Chord and scale lists come from the API when the page opens; with the API down the page shows an
  error and the keys still play, but there are no theory overlays.
