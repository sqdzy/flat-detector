# Live PostgreSQL validation — staged in CI, not yet executed

`tests/test_postgres_integration.py` is deliberately **skipped** locally unless `FD_PG_INTEGRATION_DSN` specifies `postgresql+psycopg://...`. SQLite cannot substitute for `SELECT ... FOR UPDATE SKIP LOCKED` or verify PostgreSQL schema behavior.

The repository includes `.github/workflows/test.yml`, which starts a disposable PostgreSQL 17 service. After pushing the code, CI must:

1. Install the pinned project and development dependencies in Python 3.13.
2. Create a uniquely named test schema, inject an existing PostgreSQL connection into Alembic and run the real migration `upgrade head`.
3. Seed **synthetic** approved-feed facts and one explicitly consenting synthetic subscriber.
4. Queue a digest once; a second sequential queue must not create a duplicate.
5. Block a fake Telegram sender after the first worker persists its claim, try a second worker with a separate real PostgreSQL connection, and require `EMPTY` from the competing worker.
6. Release the first worker and require exactly one successful fake message, then `downgrade base` and verify the tables are removed.
7. Drop the temporary schema even if a test fails.

The CI database password is an ephemeral dummy for test containers only. It must never be reused for production. **No outgoing Telegram requests, marketplace collection or production DB access** are made by this test. A passed CI status will be evidence of PostgreSQL migration/concurrency for this code revision only; it does not prove full live deployment.

Until the CI job has been observed successful, real PostgreSQL migration and concurrent delivery remain a deployment gate.
