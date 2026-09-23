#!/usr/bin/env bash
# Staging-only, repeatable gate for an EXISTING initialized database.
# No external profiles, no secret rotation, no volume or daemon mutations.
set -Eeuo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

if [[ ! -f .env || ! -f deploy/secrets/postgres_password_app || ! -f deploy/secrets/postgres_password_db ]]; then
  echo 'ERROR: initialized .env and BOTH existing database secret files are required; nothing changed.' >&2
  exit 1
fi
if [[ ! -f Dockerfile || ! -f alembic.ini ]]; then
  echo 'ERROR: run the script from a complete flat-detector checkout.' >&2
  exit 1
fi
if ! grep -Eq '^ENV .*PYTHONPATH=/app( |$)' Dockerfile || ! grep -Fxq 'prepend_sys_path = .' alembic.ini; then
  echo 'ERROR: repository does not contain the reviewed Python import-path fix; update source first.' >&2
  exit 1
fi

DC=(docker compose --env-file .env)
IMAGE='flat-detector-app:staging'
"${DC[@]}" config --quiet

DB_CID="$("${DC[@]}" ps -q db)"
if [[ -z "$DB_CID" ]]; then
  echo 'ERROR: database container is not running; inspect docker compose ps db.' >&2
  exit 1
fi
DB_HEALTH="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}missing{{end}}' "$DB_CID")"
if [[ "$DB_HEALTH" != healthy ]]; then
  printf 'ERROR: database is not healthy (%s); do not attempt migration.\n' "$DB_HEALTH" >&2
  exit 1
fi

printf 'Building reviewed application image from checkout %s ...\n' "$(git rev-parse --short HEAD)"
"${DC[@]}" build web

# Prevent the previous failure mode: --no-build reusing a stale pre-fix image.
if ! docker image inspect "$IMAGE" --format '{{range .Config.Env}}{{println .}}{{end}}' | grep -Fxq 'PYTHONPATH=/app'; then
  echo "ERROR: $IMAGE lacks PYTHONPATH=/app after build; stopping before migration." >&2
  exit 1
fi
# Offline import probe without secrets or database access.
docker run --rm --network none --entrypoint python "$IMAGE" -c \
  'import os, flat_detector; assert os.getenv("PYTHONPATH") == "/app"; print("Reviewed image import: OK")'

"${DC[@]}" up -d --no-deps --no-build --force-recreate migrate
MIGRATE_CID="$("${DC[@]}" ps -a -q migrate)"
if [[ -z "$MIGRATE_CID" ]]; then
  echo 'ERROR: migration container was not created; web will NOT start.' >&2
  exit 1
fi
MIGRATE_EXIT="$(docker wait "$MIGRATE_CID")"
printf 'Migration exit code: %s\n' "$MIGRATE_EXIT"
if [[ "$MIGRATE_EXIT" != 0 ]]; then
  echo 'ERROR: migration failed; web will NOT start. See: docker compose --env-file .env logs --tail=60 migrate' >&2
  exit 1
fi

"${DC[@]}" up -d --no-deps --no-build web
for attempt in $(seq 1 30); do
  if curl -fsS --max-time 3 http://127.0.0.1:8005/health/live >/dev/null 2>&1 && \
     curl -fsS --max-time 3 http://127.0.0.1:8005/health/ready >/dev/null 2>&1; then
    echo 'Dockerized migration and both loopback health endpoints passed.'
    "${DC[@]}" ps db migrate web
    exit 0
  fi
  sleep 2
done

echo 'ERROR: loopback health checks failed; inspect only flat-detector logs. No other stack was touched.' >&2
"${DC[@]}" ps db migrate web >&2
exit 1