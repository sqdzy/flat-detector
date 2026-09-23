# Implementation status — 2026-09-23

**Release stage:** reviewed MVP; CI proven with real PostgreSQL and Dockerized migration/API smoke. VPS staging pending successful run of guarded staging script; no Telegram, MCP tunnel or live sources activated.

| Slice | Implemented | Tested here | Remaining gate |
|---|---|---|---|
| Schema + Alembic | Initial models and connection-injectable migration | SQLite upgrade/current/down | PostgreSQL 17 CI passed; backup/restore and staged Docker runtime still pending |
| Permission gate | Deny-by-default, mandatory nonempty permission proof, time-bounded scope; expired/disabled source excluded at publish time | Yes, unit | Confirm actual legal authorization; operator-supplied evidence is not an audit |
| Collector | Fixed-origin approved JSON feed; 1 MiB/50 cap, no redirects, 403/429 fail closed; ignores remote geo claims | HTTPX MockTransport test only | Approved real provider, egress firewall/DNS rebinding protection, integration and quota test |
| Geographical review | Owner-only in-process route approval for near-Moscow stations; address edit invalidates approval | Yes, unit | Verified routing provider, audited admin UI/CLI and approved polygons |
| Telegram | Explicit two-step opt-in, settings, unsubscribe/delete, long-polling via Bot API | Command/HTTP mock | Real private-bot Telegram test and documented privacy notice |
| Delivery | Timezone scheduler, durable outbox; 429 retry; crash-recovery marks stale CLAIMED → UNCERTAIN | Mock SQLite and crash-recovery regression passed | PostgreSQL 17 concurrency CI passed; rate limiting for larger audiences |
| Read-only MCP | Four SDK v2 tools, no URL fetching/subscriber access, explicit loopback Host allowlist | SDK 2.2.0 real in-process Client calls for four tools; local HTTP initialize 200 / unexpected Host 421 | Identity-enforcing private tunnel and negative auth checks on real server |
| Docker | 7 base services + optional authorized_feed profile, loopback host bindings, file secrets | YAML/static parse only | Docker Compose config/build/health check on staging and file permission check |
| Real site scraping | None. No disabled major marketplace is contacted. | N/A | Separate authorization for each specific source before implementation |

**Testing:** 39 passed, 1 skipped (real PostgreSQL requires CI/staging). SDK 2.2.0 Client in-memory and ASGI HTTP Host checks passed, plus synthetic opt-in, demo no-send, claim-recovery and mock send. Coverage: **84%** including the MCP server; this is not full-system integration coverage. Tests do not prove real estate availability.

**Environment Collector — resolved:** Existing [run 35897661034](https://github.com/sqdzy/environment-collector/actions/runs/35897661034), attempt 2, completed successfully after owner restored `ghrunner` rclone OAuth. Verified downloaded Drive artifact `pip-wheelhouse-py3.13.5-linux-x86_64-46b939e8cdca3a71` (record state `complete`, outer ZIP SHA-256 `d61e262249a26e87d8746462ddbe157c9f6c97ac7b211165fedc6255e7cf1345`, all inner SHA256SUMS passed). A **fresh clean** Python 3.13.5 virtualenv installed `mcp==2.2.0` + `psycopg[binary]==3.3.6` offline and passed `pip check`. Full app dependencies are not bundled into that wheelhouse. No credentials were obtained or logged.

**GitHub status:** MVP source published as draft PR #1 on branch `feat/mvp-v0.2`, commit `72287f8ec80575e5bce3f1837b698060893b8780`. [GitHub CI run 35910378865](https://github.com/sqdzy/flat-detector/actions/runs/35910378865) passed 40 tests including PostgreSQL 17, 84% line coverage. New staging security change separates per-container password files and validates Compose syntax in CI; recheck PR run for this next commit.

## Runtime issue discovered and fixed during actual SDK testing

The Python MCP 2.2.0 `TransportSecuritySettings` default Host allowlist is empty in this runtime; using `streamable_http_app()` without an explicit allowlist returned HTTP **421 even for localhost**. We now always configure exact loopback Host entries `127.0.0.1:8765` and `localhost:8765`, plus any owner-provided exact tunnel hosts, with DNS-rebinding protection enabled. `httpx.ASGITransport` + real MCP HTTP initialization returned 200 on the allowed Host and 421 on an unexpected external Host. This is **not** substitute authentication for a remote tunnel.
