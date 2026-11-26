# Piano Learning Platform

Build order follows the master prompt's section numbers.

| Phase | Scope (consolidated master prompt) | Status |
|---|---|---|
| 1 Foundation | Repo, Docker, DB + migrations, API structure, authentication, design system, test setup | **done** |
| 2 Music theory engine | Notes, intervals, scales, chords, symbols, identification, keys, progressions, voicings, voice leading | **done**: notes through MIDI/audio interpretation, exercises, chord relationships, phrase interpretation, curated scale fingering, and the typed `/api/v1/theory` API (see `docs/music-theory.md`) |
| 3 Interactive piano | 88 keys, audio engine, 5 sounds, layering, chord dots, labels | **done** (see `docs/piano.md`) |
| 4 Learning + progressions | Lessons, progression library, practice controls, progress | **done**: chord-movement library (`docs/adr/0005-movement-library.md`), theory exercise practice with recorded progress (`0006`), and 16 lessons (`0007`). Educators and admins write lessons, and admins define extra scales, in the admin screen (`docs/music-theory.md`); the 16 built-in lessons stay read only |
| 5 MIDI Studio | Import MIDI, track controls, chord timeline, piano roll, hand correction, playback | **done** (see `docs/adr/0008-midi-studio.md`). Corrections can be saved to My Library (`0013`) and exported as MIDI (`0010`) |
| 6 Audio Analyzer | Upload audio, estimated chords on a timeline, alternatives, corrections | **done as a simple estimator** (see `docs/adr/0009-audio-analyzer.md`): works on clear recordings, tested on synthesised audio only, no trained model yet |
| 7 Advanced practice tools | Practice scoring, metronome/loops, Practice Room, wait mode, saved results, MIDI save/export | **done** (`docs/adr/0010-practice-scoring.md`): scoring engine and API, practice clock and metronome, Practice Room (`/practice`), wait mode, saved results and progress, MIDI Studio export and corrections |
| 8 Subscription + administration | Individual and institution plans, Paystack payments, seat logins | **done**: subscriptions (`docs/adr/0011-subscriptions.md`) and wider administration: People screen, audit log, admin two-factor, receipts, upgrades and refunds (`docs/adr/0014-accounts-admin-and-load.md`) |
| 9 Security, testing, deployment | Hardening, HTTPS deployment, backups, CI, legal pages | **done, with limits** (`docs/deployment.md`, `docs/adr/0012-security-and-deployment.md`, `docs/adr/0015-automated-upkeep.md`): load-test tool exists but has only been run on a one-core test box, no staging site, no penetration test, legal pages are drafts that need a lawyer |

## What exists now
Working: FastAPI app factory, typed settings, stable error format, SQLAlchemy models + Alembic migration, job lifecycle service with enforced transitions, health/readiness endpoints, job status/cancel endpoints, Celery wiring, Docker Compose (Postgres, Redis, MinIO, API, worker, web), CI, Next.js strict-TypeScript shell with Tailwind.

Also working: registration with email verification, sign-in/out with server-side sessions, password reset and change, profile update, account closure, per-IP and per-email rate limits, backend role checks, owner-scoped jobs, and the web pages for all of it (see `docs/adr/0003-authentication.md` for decisions and limits).

Also working: the interactive piano at `/piano`, and the music-theory engine and its HTTP API (notes, intervals, scales, chords, identification, keys and Roman numerals, progressions, voicings and voice leading, MIDI analysis, audio-estimate interpretation, generated exercises), with automated tests.

Also working: the Audio Analyzer at `/audio` (open a WAV/MP3/M4A/OGG file, get estimated chords with alternatives, a key estimate and Roman numerals, hear the recording with the keyboard following, and correct chords and their times; it always says estimates are estimates), MIDI Studio at `/midi` (open a .mid file, see its notes and chords on a timeline and piano roll, hear it with the keyboard following along, mute/solo/merge/split tracks, and correct which hand plays which note), the lessons at `/learn` (objectives, explanation, examples built by the theory engine and shown on the keyboard with audio, and practice goals whose progress comes from your real exercise answers), the Music Theory practice screen (`/theory`): 23 exercise kinds at four levels, marked by the engine, with per-kind counts remembered between visits. And the chord-movement library: `/progressions` (browse, play, compare levels, isolate a hand, change key) and `/admin` for educators and admins (create, edit, check, preview, submit, approve, publish, unpublish, archive, with a revision history).

Also working: individual and institution subscriptions paid through Paystack (naira, prepaid months; opt-in automatic renewal is built but off), a free trial, per-person institution logins with a seat cap and one device at a time, and the access check on the learning tools (see `docs/adr/0011-subscriptions.md`; needs `PIANO_PAYSTACK_SECRET_KEY`), a Billing Admin page for bank transfers, email through Resend (needs `PIANO_RESEND_API_KEY`), and daily plan-ending reminder emails.

Also working: a production setup (Caddy HTTPS, non-root images, daily database and saved-file backups with a tested restore, and `deploy/offsite.sh` to copy them (encrypted) off the server and alert when they stop), security headers and a content-security policy, per-person rate limits behind the proxy, error reporting (optional Sentry), terms/privacy/refund pages, and `scripts/make_admin.py` for the first admin.

Also working: **My Library** (save and reopen MIDI projects, audio analyses and chord progressions) and a dashboard built from real activity (`docs/adr/0013-my-library.md`).

Also working: account export, change email and self-service deletion; an admin People screen with an add-only audit log; two-factor sign-in (required for admins in production); receipts, prorated institution upgrades and refund handling; library search and storage cleanup; and a load-test tool (`docs/adr/0014-accounts-admin-and-load.md`).

Also working: automated upkeep (`docs/adr/0015-automated-upkeep.md`): Dependabot pull requests for every dependency and base image, a weekly CI vulnerability audit, a daily clean-up of dead sessions and links, daily plan-ending emails and backups, and `deploy/update.sh` (backup, update, health check, roll back on failure).

Also built, **off by default**: a strict nonce-based Content-Security-Policy (`CSP_ENFORCE_STRICT`, `docs/adr/0017-strict-csp.md`; needs a browser check first), and opt-in automatic card renewal (`PIANO_AUTO_RENEWAL_ENABLED`, `docs/adr/0016-automatic-renewal.md`). It is tested against a fake Paystack only; try it with Paystack test keys before switching it on.

Partial refunds are built, with a 14-day window and a repeat-refund warning that an admin must confirm and that is logged (`docs/adr/0018-partial-refunds.md`).

Not yet: a staging site, a penetration test, off-server backups and log storage (you set these up: `docs/deployment.md`), a trained chord-recognition model and a tested accuracy figure on real recordings. No job kinds are registered yet.

## Run in production
See `docs/deployment.md`. To update a live server: `./deploy/update.sh`.

## Run (development)
```
cp .env.example .env
docker compose up --build
# Dev emails (verification and reset links) are printed in the API logs: docker compose logs -f api
# API docs: http://localhost:8000/docs   Web: http://localhost:3000
```
Frontend: `cd frontend && npm install && npm test && npm run dev`

Publish the built-in movements (safe to repeat): `cd backend && python -m scripts.seed_movements`

Backend tests without Docker: `cd backend && pip install -r requirements-dev.txt && pytest`

Python dependencies are hash-locked: edit `backend/requirements.in` (or `requirements-dev.in`), then recompile with `pip-compile --generate-hashes --strip-extras --allow-unsafe -o requirements.txt requirements.in` (see `docs/adr/0015-automated-upkeep.md`).
