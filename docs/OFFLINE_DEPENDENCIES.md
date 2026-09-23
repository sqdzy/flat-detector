# Verified dependency provenance (2026-09-23)

This record describes a **working, standalone MCP + PostgreSQL driver wheelhouse** (NOT a complete application installation image).

- Builder: `sqdzy/environment-collector`, existing run `35897661034`, attempt 2, after its rclone OAuth was restored. The runner used Python 3.13.5, pip 25.1.1, target Linux x86_64.
- Exact requested packages: `mcp==2.2.0`, `psycopg[binary]==3.3.6`.
- Artifact key: `pip-wheelhouse-py3.13.5-linux-x86_64-46b939e8cdca3a71`.
- Google Drive: `Environment Collector/v1/base/pip`.
- Archive SHA-256: `d61e262249a26e87d8746462ddbe157c9f6c97ac7b211165fedc6255e7cf1345`.
- Complete record has `state=complete`, `transport.type=single` and both internal/remote checksum proof flags set. Independently downloaded record, sidecar and ZIP through Google Drive; archive size and SHA matched, and `sha256sum -c SHA256SUMS` matched **every** inner file.
- A new clean venv (not inheriting global packages) installed both exact packages **without network**, then `pip check` reported `No broken requirements found`; imports succeeded. This confirms only the specified subset, not `fastapi`, `SQLAlchemy`, `alembic`, `pytest` or all transitives of the whole project.
- Local app unit suite used an isolated MCP wheel venv with the pre-installed shared Python test packages. No secret/token from rclone was materialized.

## Reproduce on a compatible Linux x86_64 / Python 3.13.5 host

The following assumes `rclone` is configured for the environment-collector account. Transfer the files from the exact Drive artifact directory to a temporary path. From that path:

```bash
sha256sum -c pip-wheelhouse-py3.13.5-linux-x86_64-46b939e8cdca3a71.sha256
unzip -q pip-wheelhouse-py3.13.5-linux-x86_64-46b939e8cdca3a71.zip -d bundle
(cd bundle && sha256sum -c SHA256SUMS)
python3.13 -m venv .mcp-deps-venv
.mcp-deps-venv/bin/python -m pip install --no-index \
  --find-links="$(pwd)/bundle/wheelhouse" -r bundle/requirements.txt
.mcp-deps-venv/bin/python -m pip check
```

For a complete offline application or Docker build, build a **separate exact requirements.txt wheelhouse** including FastAPI, SQLAlchemy and Alembic, or use the repo's ordinary pinned internet installation when policy permits. Never claim this smaller artifact is enough to deploy the full stack offline.
