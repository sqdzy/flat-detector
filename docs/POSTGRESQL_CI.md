# Live PostgreSQL validation — passed in GitHub Actions on 2026-09-23

`tests/test_postgres_integration.py` is deliberately **skipped** locally unless `FD_PG_INTEGRATION_DSN` specifies `postgresql+psycopg://...`. SQLite cannot substitute for `SELECT ... FOR UPDATE SKIP LOCKED` or verify PostgreSQL schema behavior.

The repository includes `.github/workflows/test.yml`, which starts a disposable PostgreSQL 17 service. After publishing, [GitHub CI run 35910378865](https://github.com/sqdzy/flat-detector/actions/runs/35910378865) completed with **40 passed** and **84% line coverage**. Its ephemeral PostgreSQL 17 integration test performed:

1. Install the pinned project and development dependencies in Python 3.13.
2. Create a uniquely named test schema, inject an existing PostgreSQL connection into Alembic and run the real migration `upgrade head`.
3. Seed **synthetic** approved-feed facts and one explicitly consenting synthetic subscriber.
4. Queue a digest once; a second sequential queue must not create a duplicate.
5. Block a fake Telegram sender after the first worker persists its claim, try a second worker with a separate real PostgreSQL connection, and require `EMPTY` from the competing worker.
6. Release the first worker and require exactly one successful fake message, then `downgrade base` and verify the tables are removed.
7. Drop the temporary schema even if a test fails.

The CI database password is an ephemeral dummy for test containers only. It must never be reused for production. **No outgoing Telegram requests, marketplace collection or production DB access** are made by this test. A passed CI status will be evidence of PostgreSQL migration/concurrency for this code revision only; it does not prove full live deployment.

The ephemeral PostgreSQL CI gate is **passed for commit `72287f8ec80575e5bce3f1837b698060893b8780`**. Real staging remains a separate gate: Docker Compose config/build/health, scoped secrets and backup/restore must be validated on the target VPS. Any later commit requires its own green CI run.
