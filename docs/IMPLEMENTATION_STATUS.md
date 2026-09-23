# Implementation status — 2026-09-23

**Release stage:** reviewed MVP; CI proven with real PostgreSQL and Dockerized migration/API smoke. VPS staging passed the guarded staging script: user supplied real-host output proving shared image import, Alembic migration exit 0 and both loopback endpoints responding. Backup/isolated restore on that VPS not yet performed; no Telegram, MCP tunnel or live sources activated.

| Slice | Implemented | Tested here | Remaining gate |
|---|---|---|---|
| Schema + Alembic | Initial models and connection-injectable migration | SQLite upgrade/current/down | PostgreSQL 17 CI and VPS Docker startup passed; independent local backup/restore proof still pending |
| Permission gate | Deny-by-default, mandatory nonempty permission proof, time-bounded scope; expired/disabled source excluded at publish time | Yes, unit | Confirm actual legal authorization; operator-supplied evidence is not an audit |
| Collector | Fixed-origin approved JSON feed; 1 MiB/50 cap, no redirects, 403/429 fail closed; ignores remote geo claims | HTTPX MockTransport test only | Approved real provider, egress firewall/DNS rebinding protection, integration and quota test |
| Geographical review | Owner-only in-process route approval for near-Moscow stations; address edit invalidates approval | Yes, unit | Verified routing provider, audited admin UI/CLI and approved polygons |
| Telegram | Explicit two-step opt-in, settings, unsubscribe/delete, long-polling via Bot API | Command/HTTP mock | Real private-bot Telegram test and documented privacy notice |
| Delivery | Timezone scheduler, durable outbox; 429 retry; crash-recovery marks stale CLAIMED → UNCERTAIN | Mock SQLite and crash-recovery regression passed | PostgreSQL 17 concurrency CI passed; rate limiting for larger audiences |
| Read-only MCP | Four SDK v2 tools, no URL fetching/subscriber access, explicit loopback Host allowlist | SDK 2.2.0 real in-process Client calls for four tools; local HTTP initialize 200 / unexpected Host 421 | Identity-enforcing private tunnel and negative auth checks on real server |
| Docker | 7 base services + optional authorized_feed profile, loopback host bindings, file secrets | YAML/static parse only | VPS runtime confirmed; revisit post-launch health and database backup |
| Real site scraping | None. No disabled major marketplace is contacted. | N/A | Separate authorization for each specific source before implementation |

**Testing:** 39 passed, 1 skipped (real PostgreSQL requires CI/staging). SDK 2.2.0 Client in-memory and ASGI HTTP Host checks passed, plus synthetic opt-in, demo no-send, claim-recovery and mock send. Coverage: **84%** including the MCP server; this is not full-system integration coverage. Tests do not prove real estate availability.

**Environment Collector — resolved:** Existing [run 35897661034](https://github.com/sqdzy/environment-collector/actions/runs/35897661034), attempt 2, completed successfully after owner restored `ghrunner` rclone OAuth. Verified downloaded Drive artifact `pip-wheelhouse-py3.13.5-linux-x86_64-46b939e8cdca3a71` (record state `complete`, outer ZIP SHA-256 `d61e262249a26e87d8746462ddbe157c9f6c97ac7b211165fedc6255e7cf1345`, all inner SHA256SUMS passed). A **fresh clean** Python 3.13.5 virtualenv installed `mcp==2.2.0` + `psycopg[binary]==3.3.6` offline and passed `pip check`. Full app dependencies are not bundled into that wheelhouse. No credentials were obtained or logged.

**GitHub status:** MVP source published as draft PR #1 on branch `feat/mvp-v0.2`, commit `72287f8ec80575e5bce3f1837b698060893b8780`. [GitHub CI run 35910378865](https://github.com/sqdzy/flat-detector/actions/runs/35910378865) passed 40 tests including PostgreSQL 17, 84% line coverage. New staging security change separates per-container password files and validates Compose syntax in CI; recheck PR run for this next commit.

## Runtime issue discovered and fixed during actual SDK testing

The Python MCP 2.2.0 `TransportSecuritySettings` default Host allowlist is empty in this runtime; using `streamable_http_app()` without an explicit allowlist returned HTTP **421 even for localhost**. We now always configure exact loopback Host entries `127.0.0.1:8765` and `localhost:8765`, plus any owner-provided exact tunnel hosts, with DNS-rebinding protection enabled. `httpx.ASGITransport` + real MCP HTTP initialization returned 200 on the allowed Host and 421 on an unexpected external Host. This is **not** substitute authentication for a remote tunnel.

## VPS bootstrap and backup gate

The owner showed `Reviewed image import: OK`, `Migration exit code: 0`, and `Dockerized migration and both loopback health endpoints passed` on the actual VPS after commit `fae2c5f`. Web container initially reported `health: starting`, expected directly after creation; a later `healthy` status is still to be confirmed. Added `scripts/backup_verify.sh` for dedicated DB custom-format backup, a real isolated restore proof and protected local storage, plus an Actions integration gate and [backup guide](BACKUP_RUNBOOK.md). Do not claim the VPS backup itself has run until the owner executes the script and reports successful verification.

## 2026-09-24 — verified private bot pilot and source-research rollout

The owner confirmed a real BotFather token stored on the VPS and the private polling bot responding to /start, /subscribe, /confirm, /settings, /budget, /timezone and /hour. Automatic daily sender/scheduler, live source fetch and external MCP remain disabled. The operator-only `flat_detector.pilot` produces a zero-side-effect dry-run or, only on explicit `--send` and exactly one active consenting subscriber, a single fictional Telegram sample. The operator must verify that the sole consenting user is them before invoking --send. See [source research](SOURCE_DISCOVERY_2026-09-24.md) for verified official channels and unresolved licensing/partner search access; never conflate own-account API with global buyer search. Backup tooling is optional and outside the user's current three-stage rollout request.
