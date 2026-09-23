# Isolated staging on an existing production VPS (2026-09-23)

**Scope:** PostgreSQL + migration + loopback-only API on `sqdzy/flat-detector`, branch `feat/mvp-v0.2`. No external MCP, Telegram, or web scrapers. Reuse **none** of the existing FamilyCore databases or Docker volumes. `docker compose down -v`, `docker system prune`, and global daemon changes are expressly out of scope.

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
