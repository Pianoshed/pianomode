#!/bin/sh
# Update a running production server: back up, pull, rebuild, wait until the site answers, and
# put the old code back if it does not.
#
#   ./deploy/update.sh            # update to the latest on the current branch
#
# Run from the project folder on the server. Needs git, docker and curl. It never touches .env or
# the data volumes. To run it unattended, see "Updating" in docs/deployment.md.
set -eu
cd "$(dirname "$0")/.."
COMPOSE="docker compose -f docker-compose.prod.yml"
: "${HEALTH_TIMEOUT:=180}"

[ -f .env ] || { echo "no .env here: run this from the project folder" >&2; exit 2; }
DOMAIN=$(grep '^DOMAIN=' .env | cut -d= -f2-)
[ -n "$DOMAIN" ] || { echo "DOMAIN is not set in .env" >&2; exit 2; }
grep -q '^REDIS_PASSWORD=.' .env || {
  echo "REDIS_PASSWORD is missing in .env (added in this version). Add one: echo REDIS_PASSWORD=\$(openssl rand -hex 32) >> .env" >&2
  exit 2
}
URL="https://$DOMAIN/api/health/ready"

git diff --quiet && git diff --cached --quiet || { echo "local changes in the code: commit or stash them first" >&2; exit 2; }
before=$(git rev-parse HEAD)
git fetch --quiet
if [ "$before" = "$(git rev-parse '@{u}')" ]; then
  echo "already up to date ($before)"
  exit 0
fi

echo "1/4 backup"
$COMPOSE exec -T backup /deploy/backup.sh

echo "2/4 pull"
git pull --ff-only --quiet

waited() {  # 0 when the site answers "ok" within HEALTH_TIMEOUT seconds
  t=0
  while [ "$t" -lt "$HEALTH_TIMEOUT" ]; do
    curl -fsS --max-time 5 "$URL" 2>/dev/null | grep -q '"status":"ok"' && return 0
    sleep 5; t=$((t + 5))
  done
  return 1
}

echo "3/4 rebuild"
$COMPOSE up -d --build --remove-orphans

echo "4/4 check $URL"
if waited; then
  docker image prune -f > /dev/null
  echo "updated: $before -> $(git rev-parse HEAD)"
  exit 0
fi

echo "NEW VERSION DID NOT COME UP: going back to $before" >&2
git reset --hard --quiet "$before"   # safe: we checked there were no local changes
$COMPOSE up -d --build --remove-orphans
if waited; then
  echo "rolled back to $before. If the new version changed the database, restore the backup (docs/deployment.md, section 6)." >&2
else
  echo "STILL DOWN after rollback. Look at: $COMPOSE logs --tail=100 api" >&2
fi
exit 1
