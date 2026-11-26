# 0009 Audio Analyzer

## What it is, and what it is not
A small, transparent chord estimator that runs in the browser, feeding the server's interpretation layer. It is **not** a trained model. It measures how much of each of the twelve pitch classes is sounding (chroma), matches that to major, minor, dominant 7, major 7 and minor 7 chord templates, smooths the result over time, and reports regions. The server turns those regions into hypotheses (symbol, alternatives, ambiguity, key, Roman numerals) and applies a person's corrections.

## Decisions
**Run the signal processing on the person's device.** Decoding (`AudioContext.decodeAudioData`), mixing to mono and resampling to 11,025 Hz (`OfflineAudioContext`), chroma and chord decoding all happen in the browser, in slices with progress and a Cancel button. The recording is never uploaded; only chord regions are sent. This also meets the rule that expensive audio work must not run inside a normal request handler. Limits: 40 MB, 10 minutes, 0.5 seconds minimum, each refused with a reason.

**Harmonics are handled, carefully.** A note also sounds at 2x, 3x, 4x... its frequency. The 3rd, 5th, 6th and 7th partials land on other pitch classes (the third of a major chord has a 3rd partial on the chord's major seventh), which made plain triads look like seventh chords. A spectral peak is counted at 30% of its size when a peak at least 2.2 times stronger sits at 1/3, 1/5, 1/6 or 1/7 of its frequency. Two simpler versions were tried and both failed on measurement: counting any peak with a parent present deleted real chord tones (a flat seventh sits near the bass note's 7th partial), and discounting a bass note's 5th and 6th partials deleted the chord's own third and fifth. A bass note therefore only discounts 3rd and 7th partials. Each of the three rules is protected by a test that fails when it is removed.

**Thresholds come from measurements, not from making the screen look good.** On clean synthesised chords every genuine chord tone has at least 0.35 of the strongest pitch class's energy and no other pitch class has more than 0.13, so a pitch counts as evidence at 0.25. The nearest rival chord trails the right one by at least 0.037, so the ambiguity margin is 0.03 (the server's default of 0.1 would have flagged every region). Both are documented in the code, and the margin is a visible setting ("uncertainty warnings: fewer / normal / more"). A seventh-chord prior that was added early was measured to hurt once harmonics were handled, and was removed.

**No confidence is invented.** Scores are average cosine similarities between the audio and each template. They rank candidates against each other. They are shown as "raw score (not a probability)", the server returns `confidence: null` and `calibration: null`, and the screen never shows a percentage (a browser test checks). Uncertainty is shown in the interface: a question mark and dashed outline for an ambiguous region, a dotted outline and "no chord" for silence or noise, an orange outline for a chord the person set.

**Corrections are applied on the server, in order, and checked before they are kept.** A relabel, retime, add or delete is sent with the ordered list of corrections and kept only if the server accepts it. The original estimate stays available ("Originally heard as ..."). Moving the boundary between two chords needs two retimes in a particular order (the region giving up time first), or the server rejects an overlap; that order is a tested function. Changing how the audio is listened to (chord types, stability, shortest chord) replaces the estimate, so it asks before discarding corrections.

## Evidence
All accuracy claims below come from **synthesised audio**, where the right answer is known:
- 60 of 60 chord types and roots (five qualities, twelve roots) are identified exactly, with exactly the right pitches reported.
- ii-V-I-vi in all twelve keys and I-V-vi-IV in all twelve keys: right chords in order, with chord changes found within a third of a second.
- A recording tuned 25 cents sharp, a chord under moderate noise, silence, and pure noise (reported as no chord, never as a chord) behave as intended.
- A real 44.1 kHz stereo WAV file goes through the browser's own decoder and resampler in the browser test.

**It has not been evaluated on real recordings**, so there is no accuracy figure for real music and none should be quoted. Real recordings add vocals, drums, reverb, vibrato, tuning drift, inharmonic piano strings and dense mixes, all of which are known to lower accuracy for chroma-matching.

## Limits
- Five chord qualities only; no suspended, diminished, augmented, extended or altered chords, so these are misread as the nearest of the five.
- A bare melody note, a power chord or a chord with a missing third cannot be named reliably, and the engine says so.
- Plain C and C major seventh are closer than most pairs; the harmonic handling widens the gap but real instruments can blur it again. The alternatives list shows this.
- Chord changes are found from time, not from the beat; there is no tempo or beat tracking, no key-change detection and no handling of tuning far from 440 Hz (more than about 40 cents off is read as the wrong pitch class).
- No separation of drums or vocals (the spec's optional harmonic-percussive separation and a dedicated recognition model are not implemented).
- Corrections and settings last for the visit: nothing is saved.
- The keyboard shows the estimated chord in a standard position. It does not show the notes actually in the recording.

## Next, if accuracy matters
A trained chord-recognition model, run as a background job (the job queue exists), evaluated on a held-out set of real recordings with a reported accuracy and, only then, calibration of its scores. This estimator can remain as the fallback and as the explanation layer.
