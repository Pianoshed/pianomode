# 0015 Automated upkeep and a security review

A review of the README against the code, and of the security setup and the updating process.

## Found

- **Nothing proposed dependency updates.** CI audited weekly and failed on a known vulnerability, but a person had to notice, find the new version and edit the pins. Added `.github/dependabot.yml`: weekly pull requests for pip, npm, both Dockerfiles' base images, the compose images and the GitHub Actions. CI runs on each.
- **Updating the server was a manual three-command routine with no check and no way back.** Added `deploy/update.sh`: backup, `git pull --ff-only`, rebuild, wait for `/api/health/ready`, and reset to the previous commit if it never answers. It cannot undo a database migration; the message says to restore the backup.
- **Dead rows were never deleted.** Sessions and one-time links (with the IP address and browser name) grew without limit. Added `maintenance.purge_expired` to Celery beat (03:30 UTC): sessions expired or revoked more than 30 days ago, links expired or used more than 7 days ago. Audit log and payments are never touched. Test: `tests/test_maintenance.py`.
- **CORS allowed every method and header** with credentials. Now only the methods and the two headers the web app sends. (Same-origin and `Origin` checks were already in place.)
- **App containers had default Linux capabilities.** The prod compose file now drops all capabilities and sets `no-new-privileges` on api, worker, beat and web. Not run here (no Docker); CI validates the file, and the first deploy will show any problem.
- **CI token** could write to the repository. The workflow now has `permissions: contents: read`.
- **Docs and README had drifted:** phase 5, 8 and 9 status lines and the "not covered" list still said things already built (saving and export, administration, two-factor) were missing; `deployment.md` had two "section 9"s. Corrected.
- Dev compose: `beat` wrote its schedule file into a folder it does not own; now `/tmp`, like production.

- **Redis had no password.** It was only on the private network, but it holds the rate-limit counters and the job queue, so anything that got a foothold on that network could clear limits. Production now sets `REDIS_PASSWORD` (`--requirepass`), the API refuses to start in production if `PIANO_REDIS_URL` has no password, and Redis has a healthcheck.

- **Python dependencies were pinned by version only.** A tampered or re-uploaded package at the same version would have installed silently. `backend/requirements.in` (what we depend on) is now compiled to `requirements.txt` with every package, direct and indirect, pinned with SHA-256 hashes; the Dockerfile installs with `--require-hashes`, and pip enforces the same in CI and development because the file contains hashes. `requirements-dev.in` compiles to `requirements-dev.txt` the same way. The versions locked are the ones the tests already ran against. To change a dependency: edit the `.in` file, then `pip-compile --generate-hashes --strip-extras --allow-unsafe -o requirements.txt requirements.in` (and the dev equivalent), run the tests, commit both. Dependabot understands this layout and proposes both files together.

## Checked and fine

Argon2id with a concurrency cap and timing-equalised unknown-email path; session and link tokens stored only as hashes; password change/reset revokes sessions; `Origin` required on state-changing requests with a cookie; Paystack webhook HMAC-SHA512, compared in constant time, amounts re-verified with Paystack; two-factor secrets encrypted, recovery codes hashed and single-use, rate-limited; production refuses unsafe settings; HSTS, CSP, frame and sniffing headers; the database, Redis and API ports are not published.

## Still open (be honest about these)

- Nothing deploys new code by itself. That is deliberate (see `docs/deployment.md`).
- The CSP still allows inline scripts by default. A strict nonce-based policy is built and verified on the server output but needs a browser check before you enable it (`docs/adr/0017-strict-csp.md`).
- Backups are still only on the same server until **you** set up `deploy/offsite.sh` (needs your own storage account and an rclone crypt password, so it cannot be done for you). The script copies and verifies them and fails when the newest backup is older than 26 hours.
- No penetration test, staging site or log shipping.
