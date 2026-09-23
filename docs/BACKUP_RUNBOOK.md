# Staging PostgreSQL backup and isolated restore proof

**Status:** script and CI gate provided; live VPS proof requires the owner to run it. Scope: flat-detector's dedicated PostgreSQL 17. This is a first local recovery check, not production disaster recovery.

## Method and safety

The script follows the official [PostgreSQL 17 pg_dump](https://www.postgresql.org/docs/17/app-pgdump.html) and [pg_restore](https://www.postgresql.org/docs/17/app-pgrestore.html) documentation. It makes a consistent compressed custom-format backup of the named **flat_detector** database (not all databases or Docker volumes), validates the archive catalogue, creates an unpredictably named independent verification database from template0, restores the archive with --exit-on-error and --single-transaction, verifies Alembic revision `0001` and eight expected application tables, then drops only that temporary verification database.

- Must run **as root on the designated flat-detector VPS**. It checks Docker Compose labels `flat-detector/db` and database health before any operations. Only this Compose project's DB is inspected.
- Existing `.env`, database secret and PostgreSQL container are reused; credentials are read inside the DB container and never shown.
- Root-owned backup directory: `/var/backups/flat-detector`, mode 0700. Individual archive mode 0600, random name, checksum printed but **never post archive contents or secret files in chat**.
- No `docker compose down`, no `down -v`, no live database restore or deletion. There is a temporary **new** test database on the *same isolated flat-detector PostgreSQL server*, not on FamilyCore.
- If restore fails, script exits nonzero; no backup is marked verified. A cleanup warning requires checking `fd_restore_verify_*` test DBs before rerunning. Do not blindly drop databases yourself.
- PostgreSQL `pg_dump` backs up a single database and excludes cluster-wide roles/tablespace configuration; the current Compose stack provisions the owner role. Long-term restore planning must cover deploy configuration and secrets **separately** in a secure secret manager.

## First VPS run (no Telegram or MCP)

```bash
cd /opt/flat-detector
git status --short
git pull --ff-only origin feat/mvp-v0.2
git log -1 --oneline
docker compose --env-file .env ps db web
curl -fsS --max-time 5 http://127.0.0.1:8005/health/ready
sudo bash scripts/backup_verify.sh
```

Do **not** run any database setup, secret creation, migrations or fresh staging build just to run this backup script. If `git status --short` lists uncommitted work, stop and inspect before pulling.

Expected final messages: `Restored schema verified: 8 application tables, Alembic revision 0001.`, a root-only backup file path and SHA-256, then `Isolated restore test passed`. The backup directory must not be served over HTTP, automatically uploaded to Google Drive or checked into Git.

## Remaining prerequisites before real subscribers

1. An **encrypted, access-controlled off-site copy**, a retention policy and a restore test on a truly separate PostgreSQL instance or replacement host.
2. Protect application state and configuration outside the dump, especially both matching DB credential files and any future Telegram token. Do not put these credentials in this repository, in a chat or inside a plaintext Drive object.
3. Only later enable a separately approved private Telegram pilot and authenticated external MCP tunnel. A successful backup does not authorize collection from unapproved listing websites.

## CI proof

The PR workflow uses a disposable PostgreSQL 17 Compose service, runs the same `scripts/staging_up.sh` and then `sudo ... scripts/backup_verify.sh` with a disposable local backup directory. Passing CI proves this exact backup/restore scenario against synthetic CI data; it does **not** prove backups are recoverable after VPS disk failure.
