"""HTTP transport smoke: real MCP initialize works locally, rejects foreign Host."""
import httpx
import pytest
from flat_detector.mcp_server import app

INITIALIZE = {
    "jsonrpc": "2.0", "id": 1, "method": "initialize",
    "params": {"protocolVersion": "2025-06-18", "capabilities": {},
               "clientInfo": {"name": "flat-detector-http-test", "version": "1.0"}}
}
HEADERS = {"accept": "text/event-stream, application/json", "content-type": "application/json"}


@pytest.mark.asyncio
async def test_local_mcp_http_succeeds_but_unexpected_host_fails():
    transport = httpx.ASGITransport(app=app)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8765") as client:
            allowed = await client.post("/mcp", json=INITIALIZE, headers=HEADERS)
            assert allowed.status_code == 200
            assert '"capabilities"' in allowed.text
        async with httpx.AsyncClient(transport=transport, base_url="http://attacker.invalid:8765") as client:
            denied = await client.post("/mcp", json=INITIALIZE, headers=HEADERS)
            assert denied.status_code == 421
