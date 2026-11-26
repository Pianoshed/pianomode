# 0008 MIDI Studio

## Decisions
**Read the file in the browser.** A Standard MIDI File reader (`frontend/lib/midi/smf.ts`) parses the file on the person's device. Only note events, tempo and time signature are sent to the existing analysis endpoint, and nothing is stored. The reader refuses what it cannot read correctly, with plain messages: not a MIDI file, format 2, SMPTE timing, over 5 MB, over 256 tracks, truncated, no notes. Damaged but partly readable files keep what could be read and say so.

**The server does the music theory.** Chords, key, Roman numerals and suggested hands come from the same engine as the rest of the platform. The browser only draws and plays them. A chord region that cannot be named reliably is shown as "?" / "no reliable label"; an ambiguous one is marked with a question mark and its alternatives are offered. Key results are labelled estimates, and scores are described as rankings, not probabilities.

**Hands are the person's call.** Hand suggestions are the engine's guesses and are drawn lighter than decisions. A hand edit on one note wins over a track assigned to a hand, which wins over the guess. The engine's note ids are positions in a sorted list and change when the section or tracks change, so edits are kept in the browser, keyed by each note's start tick, pitch and channel, and applied on top of what the server returns. They are never sent to the server, so changing a hand never costs a request.

**A track is not a hand.** Tracks start with no hand set. Tagging a track left or right sets the hand of its notes; "both" and "not a hand" force nothing. Drum-only tracks are muted by default. Merge and split are done in the browser by changing which track a note is on before the request is built.

**Files over the event limit are analysed in sections.** The analysis endpoint takes 20,000 events (10,000 notes). A larger file is cut at bar lines into the widest sections that fit; the tempo and time signature in effect at the section start are carried over; a note that runs past the end of a section is cut there. The person steps between sections.

**Playback feeds the audio engine a second at a time.** The engine caps its voices when notes are scheduled, so scheduling a whole piece at once would cut the early notes. Playback hands over about a second ahead, in small pumps.

**MIDI analysis has its own rate limit** (60 a minute; other heavy routes keep 30) because the Studio re-analyses on every mute, merge or setting change. If the server still asks for a pause the Studio says so and retries twice, then stops and explains.

**Sticky panels no longer hide focused controls.** A hook sets the page's `scroll-padding-top` to the height of the sticky keyboard panel, so a control scrolled into view stops below it. This fixed the same defect on the piano page and the movement player.

## Limits
- Playback uses the platform's piano sounds at one loudness: it ignores MIDI velocity, pedal, controllers and programs. It is for checking the music, not a MIDI renderer.
- Each section of a large file is analysed on its own, so its key is estimated separately unless a key is chosen.
- Hand edits and track changes last for the visit. They are not saved and corrected MIDI cannot be exported yet.
- Pairing of overlapping notes of the same pitch is first-on-first-off, as in the analysis service. Unusual files may pair differently from a particular sequencer.
- Time is shown in bars and seconds from the file's tempo map; a file with no tempo is played at 120 BPM and says so.
- The roll is drawn on a canvas. It is reachable from the keyboard (arrows, L, R, Enter) and the chord timeline is a real list of buttons, but a screen reader does not get every note of a long piece.
