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

In the isolated execution environment used for this delivery: **39 tests passed, 1 real-PostgreSQL integration test intentionally skipped** (no PostgreSQL server/Docker locally). MCP SDK 2.2.0 and psycopg 3.3.6 were downloaded from the completed verified `environment-collector` Drive record and installed with `--no-index` into a **fresh isolated virtualenv** (`pip check`: no broken requirements). All four MCP tools were exercised through an actual SDK Client against synthetic SQLite data; ASGI Streamable HTTP initialize returned **200 on loopback** and denied a foreign Host with **421**. Docker, live Telegram, private tunnel and real PostgreSQL remain untested here. A GitHub Actions CI PostgreSQL service integration gate is included but will only run after source is pushed. See [implementation status](docs/IMPLEMENTATION_STATUS.md).

## Safety and rollout

Read [deployment guide](docs/DEPLOYMENT.md) and [source rights](docs/SOURCE_POLICY.md) before enabling network access or the Telegram profile. `FD_DEMO_MODE=true` imports three **fictional** listings; `FD_DEMO_DELIVERY=false` prevents synthetic listings from being delivered externally. No real CIAN/Avito/Domclick adapter is enabled or implemented. API feed does not grant publisher rights by itself.

Avoid making MCP publicly accessible. A local Host/Origin allowlist is not authorization; a tunnel MUST verify the owner's identity before exposing the MCP endpoint to ChatGPT. The optional `FD_MCP_ALLOWED_HOSTS` setting only supports exact whitelisted hosts.

Project docs: [specification](docs/SPEC.md), [architecture](docs/ARCHITECTURE.md), [source policy](docs/SOURCE_POLICY.md), [test plan](docs/TEST_PLAN.md), [deployment](docs/DEPLOYMENT.md), [status](docs/IMPLEMENTATION_STATUS.md).

## Dependency and PostgreSQL evidence

See [reproducible offline MCP dependencies](docs/OFFLINE_DEPENDENCIES.md) and [pending live PostgreSQL CI gate](docs/POSTGRESQL_CI.md). They document what was actually validated and what still requires the remote PostgreSQL CI job.
