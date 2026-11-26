# Deploying to a real server

This takes you from an empty server to a live site with HTTPS, backups and the first admin account. Read `docs/adr/0012-security-and-deployment.md` for why things are set up this way.

**What was and was not tested.** The Caddy config, the backup/restore scripts, the database migrations and the production web build were run for real while writing this. The Docker images and `docker-compose.prod.yml` could not be run where this was written (no Docker there), so expect to fix small things on your first deploy. CI builds both images on every push to catch the obvious ones.

## 1. What you need

- A server running Ubuntu 24.04 (2 CPU cores and 4 GB of memory is a sensible start), in a region near your users. A normal cloud VPS is fine.
- A domain name (for example `piano.yourdomain.com`) whose DNS **A record points at the server's IP address**. Caddy cannot get the HTTPS certificate until it does.
- Accounts: **Paystack** (live keys need your business verified), **Resend** (with your sending domain verified: Resend shows the DNS records to add), and optionally **Sentry**.

## 2. Prepare the server

```bash
# as a normal user with sudo, after logging in with an SSH key
sudo apt update && sudo apt install -y docker.io docker-compose-v2 git ufw
sudo ufw allow OpenSSH && sudo ufw allow 80 && sudo ufw allow 443 && sudo ufw enable
sudo usermod -aG docker $USER   # log out and in again afterwards
```

Turn off SSH password login (use keys only) and have Ubuntu install security updates by itself: `sudo apt install -y unattended-upgrades && sudo dpkg-reconfigure -plow unattended-upgrades` (answer Yes). Kernel updates need a reboot now and then (`/var/run/reboot-required` appears when one is waiting); `docker compose` services restart on their own (`restart: unless-stopped`). Only ports 22, 80 and 443 should be open; the database, Redis and API are deliberately not published.

## 3. Configure

```bash
git clone <your repository> piano && cd piano
cp .env.production.example .env
nano .env        # fill in every line; make secrets with: openssl rand -hex 32 (POSTGRES_PASSWORD, REDIS_PASSWORD, PIANO_SECRET_KEY)
```

The app refuses to start in production if the secret key is short or default, Paystack or Resend keys are missing, the site address is not `https://`, or the proxy count is not set. Those checks are there so a half-finished setup fails loudly instead of running unsafely.

## 4. Start

```bash
docker compose -f docker-compose.prod.yml up -d --build
docker compose -f docker-compose.prod.yml ps          # everything "running"/"healthy"
curl https://piano.yourdomain.com/api/health/ready    # {"status":"ok",...}
```

The first start applies the database migrations by itself.

Then load the built-in chord movements and create your admin:

```bash
docker compose -f docker-compose.prod.yml exec api python -m scripts.seed_movements
# register an account on the site and open the verification email, then:
docker compose -f docker-compose.prod.yml exec api python -m scripts.make_admin you@yourdomain.com
```

Sign out and in again; **People**, **Billing Admin** and **Content Admin** appear in the menu. (Admins cannot be created from the website on purpose.)

**Turn on two-factor straight away.** In production administrators must use it before any admin tool opens: go to Account Settings, Set up two-factor, add the key to an authenticator app, type the code, and save the ten recovery codes somewhere safe. If a phone is lost, run `docker compose -f docker-compose.prod.yml exec api python -m scripts.make_admin you@yourdomain.com --reset-2fa` and set it up again.

## 5. Connect Paystack

1. Put the **live** secret key (`sk_live_...`) in `.env` as `PIANO_PAYSTACK_SECRET_KEY` and run `docker compose -f docker-compose.prod.yml up -d`.
2. In the Paystack dashboard, Settings > API Keys & Webhooks, set the **Webhook URL** to `https://piano.yourdomain.com/api/v1/billing/webhooks/paystack`.
3. Before announcing anything, make one real payment of the smallest plan yourself and check: access starts, the payment shows in Billing Admin as "Paystack", and (if you refund yourself in the Paystack dashboard) nothing else breaks. Try a bank-transfer payment too if you offer it.

**Optional: automatic renewal.** Off by default. Before enabling `PIANO_AUTO_RENEWAL_ENABLED`, follow "Not verified against real Paystack" in `docs/adr/0016-automatic-renewal.md` with test keys.

## 6. Backups (do not skip)

A `backup` service writes a compressed database backup, and an archive of saved files, into `./backups` every day at 02:00 UTC and keeps 14 days. **That is on the same server**, so a lost server loses the backups too. `deploy/offsite.sh` copies them elsewhere every day, checks the copy, and fails loudly if there is no backup from the last 26 hours (so a silently broken backup job cannot hide behind old files). Setup, once:

```bash
sudo apt install -y rclone
rclone config            # make a remote for your storage (Google Drive, S3, Backblaze...)
                         # then a second remote of type "crypt" on top of it, called "offsite":
                         # backups contain email addresses and progress, so encrypt them before upload.
                         # Write the crypt password down somewhere that is not this server.
crontab -e               # add (03:30 is after the 02:00 backup):
30 3 * * * cd /home/YOU/piano && OFFSITE_REMOTE=offsite:piano-backups OFFSITE_PING_URL=https://hc-ping.com/YOUR-ID ./deploy/offsite.sh >> /home/YOU/offsite.log 2>&1
```

`OFFSITE_PING_URL` is optional: with a free monitor such as healthchecks.io it emails you when the script stops succeeding. Test it once by hand (`OFFSITE_REMOTE=offsite:piano-backups ./deploy/offsite.sh`) and look at the files arriving. A copy you have never restored from is a hope, not a backup: do the restore practice below using a file pulled back from the remote.

**Practise restoring before you need to.** On a spare machine or a throwaway database:

```bash
docker compose -f docker-compose.prod.yml stop api worker beat
docker compose -f docker-compose.prod.yml run --rm -v $PWD/deploy:/deploy:ro -v $PWD/backups:/backups \
  -e PGHOST=db -e PGUSER=piano -e PGPASSWORD=$(grep ^POSTGRES_PASSWORD .env | cut -d= -f2) -e PGDATABASE=piano \
  --entrypoint /deploy/restore.sh backup /backups/piano-YYYYMMDDTHHMMSSZ.dump
docker compose -f docker-compose.prod.yml up -d
```

`restore.sh` replaces what is in the target database, so never run it against live data by accident. The daily backup also makes a `piano-files-*.tar.gz` of the `storage` volume, which holds the MIDI files people save in My Library; restore it with `tar -xzf piano-files-XXXX.tar.gz -C <the storage folder>`. Restore the database and the files from the same day so they match.

## 7. Watching it

- **Is it up?** Point an uptime monitor (UptimeRobot, Better Stack, etc.) at `https://piano.yourdomain.com/api/health/ready` and have it message you. It checks the database.
- **Errors:** set `PIANO_SENTRY_DSN` and you get an alert with the stack trace for any crash. No cookies, passwords or personal details are sent. Every API error also carries a `request_id` that you can search for in the logs: `docker compose -f docker-compose.prod.yml logs api | grep REQUESTID`.
- **Disk:** logs are capped at about 50 MB per service, but check `df -h` now and then, especially `./backups`.
- **Emails:** in Billing Admin, "Send plan-ending emails now" is a quick way to confirm Resend works.

## 8. Checking capacity

`python -m scripts.loadtest` (see its header) makes fifty or more pretend people sign in and use the app and reports timings, errors and, with `ps`, memory. Run it from a **different machine** against a **test copy** of the site (it creates accounts ending `@loadtest.invalid`; `clean` removes them), then size the server from what you see. Results from this project's one-core test box are in `docs/adr/0014-accounts-admin-and-load.md`; they are not a prediction for yours. Tune `PIANO_MAX_CONCURRENT_HASHES` (password hashes at once, per process) to roughly the number of CPU cores.

## 9. Updating

```bash
./deploy/update.sh
```

It takes a backup, pulls the new code, rebuilds, waits until `/api/health/ready` answers, and puts the previous code back if it does not (it says so, and tells you to restore the backup if the new version had changed the database). Migrations run on start. It refuses to run if you have edited the code on the server.

Doing it by hand is the same as before: `git pull` then `docker compose -f docker-compose.prod.yml up -d --build`, after `docker compose -f docker-compose.prod.yml exec backup /deploy/backup.sh`.

**What updates itself, and what does not**

| Thing | How | You still have to |
|---|---|---|
| Ubuntu security patches | `unattended-upgrades` (section 2) | reboot when asked |
| Python (hash-locked), npm, Docker base image and GitHub Actions versions | Dependabot opens a pull request each Monday (`.github/dependabot.yml`); CI tests, builds and audits each one | read and merge the green ones, then run `./deploy/update.sh` |
| New vulnerabilities in what we already use | CI runs `pip-audit` and `npm audit` every Monday and fails loudly | fix when it fails |
| Caddy, Postgres, Redis images | Dependabot watches the tags in the compose files | `update.sh` rebuilds; for the compose images run `docker compose -f docker-compose.prod.yml pull` first |
| Dead sessions and one-time links | Celery beat deletes them daily at 03:30 UTC | nothing |
| Renewals (if enabled), plan-ending emails, backups | beat at 06:00 and 07:00 UTC, backup service at 02:00 UTC | run `deploy/offsite.sh` from cron (section 6) |
| The site's own code | **not automatic, on purpose** | run `./deploy/update.sh` |

Deploying new code with nobody watching is a choice you can make later. If you do, run `update.sh` from cron during working hours, for example `0 10 * * 2 cd /home/YOU/piano && ./deploy/update.sh >> /home/YOU/update.log 2>&1`, and keep the uptime monitor from section 7. A major Postgres version (16 to 17) is never an automatic update: it needs a dump and restore.

## 10. Before you tell anyone

- [ ] DNS points at the server and `https://` works with no browser warning
- [ ] `.env` is filled in, is **not** in git, and only you can read it (`chmod 600 .env`)
- [ ] The legal pages (`/terms`, `/privacy`, `/refunds`) show your real company name and support email, **and a Nigerian lawyer has read them**. The refund policy is a default; change it to what you will actually do
- [ ] A test payment worked end to end and the webhook is set
- [ ] Sign-up verification and password-reset emails arrive (check spam, too)
- [ ] You restored a backup at least once
- [ ] The uptime monitor and Sentry both reach you
- [ ] You have an admin account and one other person knows how to reach the server
- [ ] You saved a MIDI project in My Library, reopened it, and found it again in a backup's files archive
- [ ] An administrator turned on two-factor and kept the recovery codes
- [ ] You made a full refund in Paystack test mode and saw the access taken back (or the audit log say "needs review")
- [ ] You made a test institution (buy the 10-seat plan, create a login, sign in with it on two devices)

## What is and is not covered

Covered: HTTPS with automatic certificates and HSTS; the API, database and Redis are not reachable from the internet; the app runs as a non-root user; a content-security policy and other browser security headers (a stricter nonce-based script policy is available behind `CSP_ENFORCE_STRICT`, `docs/adr/0017-strict-csp.md`); per-person rate limits that work behind the proxy and for students sharing one connection; the web and API versions have no known vulnerabilities at the time of writing (`pip-audit` / `npm audit`, re-checked weekly by CI, with Dependabot proposing updates); daily backups; admin two-factor sign-in; app containers with no Linux capabilities and no privilege escalation; refusal to start with unsafe settings.

Not covered, and worth doing as you grow: a staging site that mirrors production; off-server log storage; database replication or a managed database with point-in-time recovery; a formal penetration test; a hardware-key (WebAuthn) second factor; load testing at your expected size (the load tool has only been run on a one-core test box). Code rollback is automatic in `update.sh`; database rollback is a restore.
