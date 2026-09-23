#!/usr/bin/env bash
# First-stage backup + isolated restore check for flat-detector's dedicated DB.
# No mutation to the live database schema or volumes, and no other Compose project.
set -Eeuo pipefail
umask 077

cd "$(dirname "${BASH_SOURCE[0]}")/.."

if [[ $(id -u) -ne 0 ]]; then
  echo 'ERROR: execute as root (sudo bash scripts/backup_verify.sh).' >&2
  exit 1
fi
if [[ ! -f .env || ! -f deploy/secrets/postgres_password_db ]]; then
  echo 'ERROR: existing flat-detector configuration/DB secret not found.' >&2
  exit 1
fi

DC=(docker compose --env-file .env)
"${DC[@]}" config --quiet
DB_CID="$("${DC[@]}" ps -q db)"
if [[ -z "$DB_CID" ]]; then
  echo 'ERROR: the flat-detector database container is not running.' >&2
  exit 1
fi
PROJECT="$(docker inspect --format '{{index .Config.Labels "com.docker.compose.project"}}' "$DB_CID")"
SERVICE="$(docker inspect --format '{{index .Config.Labels "com.docker.compose.service"}}' "$DB_CID")"
DB_HEALTH="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}missing{{end}}' "$DB_CID")"
if [[ "$PROJECT" != flat-detector || "$SERVICE" != db || "$DB_HEALTH" != healthy ]]; then
  printf 'ERROR: unexpected container identity or health: project=%s service=%s health=%s\n' \
    "$PROJECT" "$SERVICE" "$DB_HEALTH" >&2
  exit 1
fi

BACKUP_DIR="${FD_BACKUP_DIR:-/var/backups/flat-detector}"
if [[ "$BACKUP_DIR" != /* || -L "$BACKUP_DIR" ]]; then
  echo 'ERROR: backup directory must be an absolute path and not a symlink.' >&2
  exit 1
fi
install -d -o 0 -g 0 -m 0700 "$BACKUP_DIR"
if [[ $(stat -c %u "$BACKUP_DIR") != 0 ]]; then
  echo 'ERROR: backup directory is not owned by root.' >&2
  exit 1
fi
chmod 0700 "$BACKUP_DIR"

PARTIAL="$(mktemp "$BACKUP_DIR/flat_detector_$(date -u +%Y%m%dT%H%M%SZ)_XXXXXXXX.dump.partial")"
FINAL="${PARTIAL%.partial}"
VERIFY_DB="fd_restore_verify_$(date -u +%Y%m%d%H%M%S)_$(openssl rand -hex 4)"
if [[ ! "$VERIFY_DB" =~ ^fd_restore_verify_[0-9]{14}_[0-9a-f]{8}$ ]]; then
  echo 'ERROR: invalid test database name' >&2
  exit 1
fi
TEST_CREATED=0
FINISHED=0
cleanup() {
  result=$?
  trap - EXIT
  if [[ $TEST_CREATED == 1 ]]; then
    # Only ever drop the fresh, random, script-created verification database.
    if [[ "$VERIFY_DB" =~ ^fd_restore_verify_[0-9]{14}_[0-9a-f]{8}$ ]]; then
      docker exec -e "FD_VERIFY_DB=$VERIFY_DB" "$DB_CID" sh -ec '
        PGPASSWORD="$(cat /run/secrets/postgres_password)"; export PGPASSWORD
        dropdb -h 127.0.0.1 -U flat_detector --maintenance-db=flat_detector --if-exists "$FD_VERIFY_DB"
      ' >/dev/null 2>&1 || echo 'WARNING: manual cleanup may be needed for an isolated fd_restore_verify_* database.' >&2
    fi
  fi
  if [[ $FINISHED != 1 && -f "$PARTIAL" ]]; then
    rm -f -- "$PARTIAL"
  fi
  exit "$result"
}
trap cleanup EXIT

echo 'Backing up only flat-detector, with a compressed PostgreSQL custom archive...'
# The password remains within the database container and is never displayed.
docker exec "$DB_CID" sh -ec '
  PGPASSWORD="$(cat /run/secrets/postgres_password)"; export PGPASSWORD
  exec pg_dump -h 127.0.0.1 -U flat_detector -d flat_detector \
    --format=custom --compress=6 --no-owner --no-acl --lock-wait-timeout=5s
' > "$PARTIAL"

if [[ ! -s "$PARTIAL" ]]; then
  echo 'ERROR: pg_dump did not generate an archive.' >&2
  exit 1
fi
# This checks the custom-archive catalogue before any database mutations.
docker exec -i "$DB_CID" pg_restore --list < "$PARTIAL" > /dev/null
printf 'Archive generated and readable (%s bytes).\n' "$(stat -c %s "$PARTIAL")"

# Isolated test DB on the same PostgreSQL cluster. Never restore into flat_detector.
docker exec -e "FD_VERIFY_DB=$VERIFY_DB" "$DB_CID" sh -ec '
  PGPASSWORD="$(cat /run/secrets/postgres_password)"; export PGPASSWORD
  createdb -h 127.0.0.1 -U flat_detector --maintenance-db=flat_detector \
    --template=template0 "$FD_VERIFY_DB"
'
TEST_CREATED=1

docker exec -i -e "FD_VERIFY_DB=$VERIFY_DB" "$DB_CID" sh -ec '
  PGPASSWORD="$(cat /run/secrets/postgres_password)"; export PGPASSWORD
  exec pg_restore -h 127.0.0.1 -U flat_detector --dbname="$FD_VERIFY_DB" \
    --exit-on-error --single-transaction --no-owner --no-acl
' < "$PARTIAL"

# Check actual restored schema rather than only pg_restore's table of contents.
RESTORED_VERSION="$(docker exec -e "FD_VERIFY_DB=$VERIFY_DB" "$DB_CID" sh -ec '
  PGPASSWORD="$(cat /run/secrets/postgres_password)"; export PGPASSWORD
  psql -X -qAt -v ON_ERROR_STOP=1 -h 127.0.0.1 -U flat_detector -d "$FD_VERIFY_DB" \
    -c "SELECT version_num FROM public.alembic_version"
')"
if [[ "$RESTORED_VERSION" != 0001 ]]; then
  echo 'ERROR: restored schema has an unexpected Alembic version.' >&2
  exit 1
fi
RESTORED_TABLES="$(docker exec -e "FD_VERIFY_DB=$VERIFY_DB" "$DB_CID" sh -ec '
  PGPASSWORD="$(cat /run/secrets/postgres_password)"; export PGPASSWORD
  psql -X -qAt -v ON_ERROR_STOP=1 -h 127.0.0.1 -U flat_detector -d "$FD_VERIFY_DB" \
    -c "SELECT count(*) FROM information_schema.tables WHERE table_schema = '\''public'\'' AND table_name IN ('\''sources'\'', '\''listings'\'', '\''evidence'\'', '\''price_history'\'', '\''subscribers'\'', '\''outbox'\'', '\''recheck_jobs'\'', '\''bot_offset'\'')"
')"
if [[ "$RESTORED_TABLES" != 8 ]]; then
  echo 'ERROR: restored database is missing expected application tables.' >&2
  exit 1
fi

# Preserve the backup only after real restore succeeds; the test DB is deleted on EXIT.
chmod 0600 "$PARTIAL"
mv -- "$PARTIAL" "$FINAL"
FINISHED=1
printf 'Restored schema verified: 8 application tables, Alembic revision 0001.\n'
printf 'Backup location: %s\n' "$FINAL"
printf 'Backup SHA-256: '
sha256sum "$FINAL" | awk '{print $1}'
echo 'Isolated restore test passed. Local backup is UNENCRYPTED and must not be uploaded off-server as-is.'