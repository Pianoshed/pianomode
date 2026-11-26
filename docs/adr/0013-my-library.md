# 0013 My Library and the real dashboard

## What people can save

| Kind | What is stored | Opens in |
|---|---|---|
| MIDI project | the `.mid` file (up to 5 MB) and every choice made in MIDI Studio: track merges and splits, hand per track and per note, mute/solo, start bar, chord grid, spelling, key | `/midi?project=ID` |
| Audio analysis | **settings and corrections only**: chord set, stability, minimum length, key, spelling, ambiguity level, corrections, file name, length, a short summary. **Never the recording** | `/audio?project=ID` |
| Chord progression | which movement, key, level, hands and tempo | `/progressions/SLUG?key=..&level=..&hands=..&tempo=..` |

Why the audio is not kept: recordings are large (tens of MB), usually belong to someone else (a song someone is learning), and the Privacy page can honestly say recordings are never uploaded. To carry on, the person opens the same recording again; the saved settings are already in place, and the corrections are applied when the new recording is about the same length (within 1.5 s). If it is a different length they are skipped and the person is told.

## How it works

- `library_items` table (`kind`, `title`, `data` JSON, `file_name`, `file_size`, `last_opened_at`). `data` carries a version number and is owned by the web app; the server only checks it is a JSON object under 200 KB. MIDI files are in the storage folder (`PIANO_STORAGE_DIR`, default `./var/storage`; the `storage` volume in production) as `library/<user id>/<item id>`. File names are never taken from what the person typed, and every path is checked to stay inside the folder (`app/services/file_store.py`).
- A MIDI item is created in **one request** with the file as base64 (`file_base64`), so there is never a half-saved item. The server checks it really starts with `MThd`.
- **Saved data is untrusted when it comes back.** `restoreMidiProject`, `restoreAudioProject` and `restoreProgression` (`frontend/lib/library`) drop anything invalid, piece by piece, and fall back to the normal default, so a damaged or newer save can never stop a project opening.
- Everything is private to its owner. Someone else's id looks exactly like one that does not exist (404).
- **Limits per person** (Settings): 200 items, 5 MB per MIDI file, 100 MB of files in all, 200 KB of settings per item. Clear messages say what to delete.
- **When a plan has ended**, people can still open My Library, download their MIDI files and delete items (their own work should not be held hostage), but saving and renaming need an active plan, and opening an item in a studio goes through the paywall like the studio itself. Institution logins can save like anyone else.
- `GET /api/v1/library/{id}` also records "last opened", which feeds the dashboard's recent list.

## Dashboard

`GET /api/v1/dashboard` replaces the placeholders. It needs sign-in only (so it works after a plan ends) and returns: lessons in progress (with goals met out of total), the first lesson not started whose prerequisites are done (with the reason), the five most recently opened projects, the five most recently saved progressions, and answers/passes per day for the last 7 days (UTC days). "Practice activity" counts practice passes and theory answers; it is not minutes, because the system does not record how long someone practised.

## Fixed along the way

- After saving, the "Saved as ..." confirmation vanished: updating the studio's state re-created the Save control. Found by the browser test; the control is now keyed to the loaded file.
- Stale text said "nothing is saved" in MIDI Studio and the Audio Analyzer, and the Privacy page said files are not kept. All three now describe what is and is not stored.
- Backups now include the storage folder (saved MIDI files), not just the database.

## Not done

- Folders, tags, search or sharing of saved items; a library item is only ever for its owner.
- Saving the audio itself (would need storage costs and a rights policy).
- (Done later, see ADR 0014: deleting an account removes the person's saved files, and `scripts/cleanup_storage.py` finds files left behind by a crash.)
- Practice time in minutes.
