"""Runs as soon as the production MCP Python SDK v2 is available locally."""
import pytest

@pytest.mark.asyncio
async def test_four_registered_readonly_tools_in_memory():
    import importlib.util
    if importlib.util.find_spec("mcp.server") is None:
        pytest.skip("Local MCP 2.x wheel is not yet available")
    from mcp import Client
    from flat_detector.mcp_server import mcp
    async with Client(mcp) as client:
        discovered=await client.list_tools()
        tools={tool.name:tool for tool in discovered.tools}
        assert set(tools)=={
            "list_active_listings","get_listing_evidence","get_source_health","preview_daily_digest"
        }
        assert all(t.annotations and t.annotations.read_only_hint for t in tools.values())
