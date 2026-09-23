# flat-detector · Khimki pilot implementation

**Locally tested MVP v0.2, not deployed. No real estate marketplace is scraped and no Telegram message has been sent.** The source-rights gate defaults to disabled until the owner provides a permitted data channel. Original [spec](docs/SPEC.md) is wider than this initial implementation.

## Delivered code

- SQLAlchemy records and Alembic migration: registered sources, listings, evidence, prices, subscribers, outbox and recheck drafts.
- Mandatory permission proof, expiry and required `search,store,notify` scopes before ingest **and** before recommending listings. 403/429 do not imply a removed apartment.
- A fixed-URL JSON partner feed adapter (`flat_detector/collector.py`) tested against fake in-memory HTTPS transport; optionally run via `flat_detector/feed_cli.py` and the disabled-by-default `approved_feed` Compose profile. Untrusted feed input never grants geographic approval or route data. A separately reviewed route is invalidated when an address changes.
- Telegram bot commands `/start`, `/subscribe`, `/confirm`, `/settings`, `/budget`, `/timezone`, `/hour`, `/digest`, `/stop`, `/delete_me`, plus autonomous timezone-aware daily scheduler and durable outbox. No subscription without confirmation; no blind replay after an uncertain send.
- Four private read-only MCP SDK v2 tools: `list_active_listings`, `get_listing_evidence`, `get_source_health`, `preview_daily_digest`. Owner-only recheck logic exists but is deliberately **not registered** as an MCP tool. No universal shell, arbitrary HTTP fetcher or subscriber IDs are exposed.
- Docker Compose profiles, pinned requirements, GitHub CI with ephemeral PostgreSQL service, actual MCP SDK + HTTP Host protection integration tests, synthetic data import, mock HTTP tests and separate security/deployment documentation.
- A restart-recovery step marks stale `CLAIMED` deliveries as `UNCERTAIN` instead of silently replaying potentially accepted Telegram messages.

## Test locally

```bash
python3 -m pip install -r requirements-dev.txt  # on a machine with approved package access
PYTHONPATH=. python3 -m pytest -q --cov=flat_detector --cov-report=term-missing
python3 -m compileall -q flat_detector
```

In the isolated execution environment used for this delivery: **39 tests passed, 1 real-PostgreSQL integration test intentionally skipped** (no PostgreSQL server/Docker locally). MCP SDK 2.2.0 and psycopg 3.3.6 were downloaded from the completed verified `environment-collector` Drive record and installed with `--no-index` into a **fresh isolated virtualenv** (`pip check`: no broken requirements). All four MCP tools were exercised through an actual SDK Client against synthetic SQLite data; ASGI Streamable HTTP initialize returned **200 on loopback** and denied a foreign Host with **421**. Docker, live Telegram, private tunnel and real PostgreSQL remain untested here. The first [GitHub Actions CI run](https://github.com/sqdzy/flat-detector/actions/runs/35910378865) completed successfully with **40 passed**, including real PostgreSQL 17 migrations and concurrency, and **84% line coverage**. This is CI evidence, not Docker staging or live-service approval. See [implementation status](docs/IMPLEMENTATION_STATUS.md).

## Idempotent staging recovery on existing VPS

After updating `feat/mvp-v0.2`, do not invoke `up --no-build migrate` until the common image has been rebuilt. For the existing initialized, healthy flat-detector DB, use `bash scripts/staging_up.sh`: this performs a checked image build, networkless import smoke, migration gate, and loopback health checks, without touching any other Docker project. Full details: [staging runbook](docs/STAGING_RUNBOOK.md).

## Verified database backup

For the initialized staging deployment only, run `sudo bash scripts/backup_verify.sh`. It creates a root-only local PostgreSQL custom-format archive and tests restoration into a randomly named isolated verification database on the same flat-detector PostgreSQL cluster. It does **not** recreate or overwrite the live database and does not interact with any other Compose project. Review [the backup and recovery guide](docs/BACKUP_RUNBOOK.md) first. **This unencrypted on-host backup is not an off-site disaster recovery solution**.

## One-recipient Telegram delivery proof (owner-invoked only)

The bot already supports real private opt-in; the standalone `flat_detector.pilot` tests a **single** actual Telegram `sendMessage` without enabling the automated scheduler/sender or writing synthetic properties to PostgreSQL. It refuses to run unless the database has **exactly one** active subscriber with recorded consent. Confirm that this sole subscriber is your own chat before using `--send`.

```bash
cd /opt/flat-detector
git status --short
git pull --ff-only origin feat/mvp-v0.2
docker compose --env-file .env build web
docker compose --env-file .env --profile telegram run --rm --no-deps -T bot python -m flat_detector.pilot
# Inspect dry-run output before explicitly sending one fictional sample:
docker compose --env-file .env --profile telegram run --rm --no-deps -T bot python -m flat_detector.pilot --send
```

Both commands operate on the same single local project database; the first is read-only and does not read the Telegram token. The second sends **one** marked fictional example to that **sole** consenting subscriber and redacts error details to prevent leaking the token. Never retry after an ambiguous network failure without first checking the actual chat. There are no actual listings yet.

## Source access research

[Verified source-channel research (2026-09-24)](docs/SOURCE_DISCOVERY_2026-09-24.md) distinguishes approved publisher/partner APIs from permission for global buyer-oriented search. CIAN, Avito and Domclick real-estate search collection remains disabled pending confirmed access rights; until then use manual own observations and explicitly distinguish **unverified** links from active listings.

## Safety and rollout

Read [deployment guide](docs/DEPLOYMENT.md) and [source rights](docs/SOURCE_POLICY.md) before enabling network access or the Telegram profile. `FD_DEMO_MODE=true` imports three **fictional** listings; `FD_DEMO_DELIVERY=false` prevents synthetic listings from being delivered externally. No real CIAN/Avito/Domclick adapter is enabled or implemented. API feed does not grant publisher rights by itself.

Avoid making MCP publicly accessible. A local Host/Origin allowlist is not authorization; a tunnel MUST verify the owner's identity before exposing the MCP endpoint to ChatGPT. The optional `FD_MCP_ALLOWED_HOSTS` setting only supports exact whitelisted hosts.

Project docs: [specification](docs/SPEC.md), [architecture](docs/ARCHITECTURE.md), [source policy](docs/SOURCE_POLICY.md), [test plan](docs/TEST_PLAN.md), [deployment](docs/DEPLOYMENT.md), [status](docs/IMPLEMENTATION_STATUS.md).

## Dependency and PostgreSQL evidence

See [reproducible offline MCP dependencies](docs/OFFLINE_DEPENDENCIES.md), [passed PostgreSQL CI gate](docs/POSTGRESQL_CI.md) and [isolated staging runbook](docs/STAGING_RUNBOOK.md). Deploy only the database and loopback API first; separate app/DB secret files avoid unsafe shared permissions.
