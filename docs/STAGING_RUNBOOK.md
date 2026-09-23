# Isolated staging on an existing production VPS (2026-09-23)

**Scope:** PostgreSQL + migration + loopback-only API on `sqdzy/flat-detector`, branch `feat/mvp-v0.2`. No external MCP, Telegram, or web scrapers. Reuse **none** of the existing FamilyCore databases or Docker volumes. `docker compose down -v`, `docker system prune`, and global daemon changes are expressly out of scope.

## Verified one-command recovery and staging gate (preferred)

**Root cause of the repeated VPS failure:** the VPS fast-forwarded to commit `e93a06f` but then ran `docker compose up --no-build migrate` **without rebuilding** the previously created `flat-detector-app:staging` image. Docker documentation requires `docker compose build web` whenever the Dockerfile/source changes. `--no-build` explicitly suppresses rebuilding, so a stale image still lacks `PYTHONPATH=/app`. The previous GitHub CI passed because it built a fresh image; this divergence is reproducible from command semantics, not a new Alembic defect.

Use the repository script instead of manually skipping the build command. It requires an *already healthy* flat-detector database and both existing secret files; it never rotates credentials, removes volumes, enables Telegram/MCP/feeds, or touches other Docker projects. It validates the Compose config, **builds web**, verifies the resulting shared image has `PYTHONPATH=/app`, runs a **networkless, secretless Python import probe**, recreates only the failed migration, aborts if migration exit code is nonzero, and launches the loopback API only after success.

```bash
cd /opt/flat-detector
git status --short
git pull --ff-only origin feat/mvp-v0.2
bash scripts/staging_up.sh
```

The same script is executed by GitHub Actions against a disposable PostgreSQL Compose database. For extra read-only evidence *before* the rebuild, inspect the cached image environment without revealing secrets:

```bash
docker image inspect flat-detector-app:staging \
  --format '{{range .Config.Env}}{{println .}}{{end}}' | grep '^PYTHONPATH=' || true
```

An absent `PYTHONPATH=/app` confirms the older cached image. The script should not be invoked on a new host before provisioning separate database secrets and bringing up the flat-detector database. It intentionally does not restart or manipulate the existing database.

## First review and resource gate (read-only)

```bash
free -h
df -h /
docker stats --no-stream --format 'table {{.Name}}\t{{.MemUsage}}\t{{.CPUPerc}}'
ss -lntp | grep -E ':(8005|8765)[[:space:]]' || true
```

On the reported VPS: 3.8 GiB total RAM, 2.5 GiB available, 35 GiB free disk, ports 8005/8765 not occupied as checked. Other production containers exist, so deploy off-peak, stop on memory pressure, never expose an address outside `127.0.0.1`.

## Checkout (dedicated path, no effects on other stacks)

```bash
sudo mkdir -p /opt/flat-detector
sudo git clone --branch feat/mvp-v0.2 --single-branch https://github.com/sqdzy/flat-detector.git /opt/flat-detector
cd /opt/flat-detector
sudo cp .env.example .env
```

If the directory already exists, do NOT run clone over it; inspect that exact checkout instead. Before updating later, inspect `git status`, pin a reviewed commit and avoid `git reset --hard`.

## Secrets (run as root in the checkout, no terminal echo of values)

The app container is UID/GID 10001:10001, while the PostgreSQL Alpine image uses a different user. Docker Compose file secrets are implemented as bind mounts and cannot reliably override host file permissions using a `mode:` attribute. A single mode-0600 file would be unreadable by one of the containers. This deployment keeps **two independent host files** with identical generated password and permissions specific to each target process. Never loosen secret modes or mount the whole secret directory into all containers.

```bash
sudo -i
cd /opt/flat-detector
umask 077
install -d -o root -g root -m 0700 deploy/secrets
# Confirm exact UID/GID from the same pinned image before assigning its secret.
docker pull postgres:17.11-alpine3.23
PG_UID=$(docker run --rm --entrypoint id postgres:17.11-alpine3.23 -u postgres)
PG_GID=$(docker run --rm --entrypoint id postgres:17.11-alpine3.23 -g postgres)
case "$PG_UID:$PG_GID" in *[!0-9:]*|'') echo 'Invalid postgres UID/GID'; exit 1;; esac
# Only generate new credentials for a fresh database. NEVER overwrite on an established deployment.
test ! -e deploy/secrets/postgres_password_app && test ! -e deploy/secrets/postgres_password_db || { echo 'Secrets exist; STOP'; exit 1; }
secret=$(openssl rand -hex 32)
printf '%s\n' "$secret" > deploy/secrets/postgres_password_app
printf '%s\n' "$secret" > deploy/secrets/postgres_password_db
unset secret
chown 10001:10001 deploy/secrets/postgres_password_app
chown "$PG_UID:$PG_GID" deploy/secrets/postgres_password_db
chmod 0400 deploy/secrets/postgres_password_app deploy/secrets/postgres_password_db
# The telegram profile remains OFF. Empty token file avoids optional-file validation errors.
test ! -e deploy/secrets/telegram_token || { echo "Telegram token file exists; STOP without overwriting"; exit 1; }
install -o 10001 -g 10001 -m 0400 /dev/null deploy/secrets/telegram_token
chmod 0600 .env
exit
```

**WARNING:** the UID-probe commands must return numeric values, and the PostgreSQL DB/app secrets must contain the same value. The shell commands above only work on a **new** deployment. Never regenerate the password against an existing volume.

## Gate, build and start (no Telegram/MCP)

```bash
cd /opt/flat-detector
sudo docker compose --env-file .env config --quiet
sudo docker compose --env-file .env build web
# This tags the shared flat-detector-app:staging image used by web, migrate and all optional workers.
# Scope only to this Compose project, starting the database first.
sudo docker compose --env-file .env up -d db
sudo docker compose --env-file .env ps db
sudo docker compose --env-file .env up -d --no-build migrate
CID="$(sudo docker compose --env-file .env ps -a -q migrate)"
test -n "$CID"
EXIT_CODE="$(sudo docker wait "$CID")"
printf 'Migration exit code: %s\n' "$EXIT_CODE"
test "$EXIT_CODE" -eq 0
sudo docker compose --env-file .env up -d --no-build web
sudo docker compose --env-file .env ps
curl --fail --show-error --silent http://127.0.0.1:8005/health/live
curl --fail --show-error --silent http://127.0.0.1:8005/health/ready
sudo docker compose --env-file .env logs --tail=60 db migrate web
```

`/health/ready` proves database connectivity, not a ready Telegram bot, source permission, safe scrape, backup, or public MCP auth. If an existing container becomes unhealthy, **stop only this project** (`docker compose --env-file .env stop web db`); do not delete its volumes, restart Docker or touch FamilyCore. Capture filtered error logs without passwords.

## Follow-up gates (not part of first launch)

1. Verify a dedicated encrypted PostgreSQL backup + restore exercise; use `pg_dump` / `pg_restore` only for this new database.
2. Telegram: user-owned BotFather token in `deploy/secrets/telegram_token` under UID 10001; explicit private opt-in tests, no demo sends by default.
3. MCP: private identity-verifying HTTPS proxy/tunnel with negative unauthorized tests; local port 8765 alone is **not authorization**.
4. Approved partner feed: documentary `search,store,notify` permission and an egress firewall to block DNS-rebinding / internal network access before any external fetch.

## Recovery: missing `flat-detector-migrate:latest` after building only web

Older revisions used a Compose-generated image name per service. `build web` created `flat-detector-web:latest`, but starting `migrate` with `--no-build` failed because `flat-detector-migrate:latest` did not exist. This version gives all Python services the same image tag `flat-detector-app:staging`, avoiding duplicate builds. On an already cloned deployment, retain existing `.env`, `deploy/secrets/*` and DB volume. After checking `git status --short`, run `git pull --ff-only origin feat/mvp-v0.2`, then `docker compose --env-file .env config --quiet` and `docker compose --env-file .env build web`. Only then repeat the migrate / web steps above. **Never** recreate passwords or use `down -v` to address a missing image.

## Migration fix after initial `ModuleNotFoundError: No module named flat_detector`

Revision after `919f153` sets Docker `PYTHONPATH=/app` and Alembic `prepend_sys_path = .` because the Alembic CLI's script directory may replace the working directory in Python's module lookup. This is a packaging/entrypoint issue, **not evidence that PostgreSQL must be reset**. Confirm an unchanged database and secrets; only fast-forward the source branch, validate Compose, rebuild the *shared application image*, and recreate **only the failed migrate service**:

```bash
cd /opt/flat-detector
git status --short
git pull --ff-only origin feat/mvp-v0.2
docker compose --env-file .env config --quiet
docker compose --env-file .env build web
docker compose --env-file .env up -d --no-deps --no-build --force-recreate migrate
CID="$(docker compose --env-file .env ps -a -q migrate)"
test -n "$CID"
EXIT_CODE="$(docker wait "$CID")"
echo "Migration exit code: $EXIT_CODE"
test "$EXIT_CODE" -eq 0
# Only after exit 0:
docker compose --env-file .env up -d --no-build web
curl -fsS --max-time 5 http://127.0.0.1:8005/health/live
curl -fsS --max-time 5 http://127.0.0.1:8005/health/ready
```

Do not recreate the database, change passwords, call `down -v`, or touch the FamilyCore Compose project. If migration fails again, collect only scrubbed migration log lines and stop before starting web.
