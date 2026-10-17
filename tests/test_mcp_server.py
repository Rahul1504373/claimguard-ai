"""
Tests mcp_server.py over a REAL stdio transport — spawning it as a
subprocess and talking to it via the actual MCP client/session protocol,
exactly as Claude Desktop or any other MCP client would. Not an in-process
shortcut: this is the same connection mechanism a real client uses.

IMPORTANT: this file requires the `mcp` package, which is NOT in
requirements.txt (see requirements-mcp.txt and mcp_server.py's module
docstring for why they're kept in separate environments — `mcp` conflicts
with this project's pinned FastAPI/starlette versions). Run this file from
venv-mcp, not the main venv:

    source venv-mcp/bin/activate
    pytest tests/test_mcp_server.py -v

It is deliberately excluded from the main `pytest tests/` run for that
reason — running it from the main venv will fail at the import line below
with "No module named 'mcp'", which is expected, not a bug.
"""
import asyncio
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

try:
    from mcp.client.stdio import stdio_client, StdioServerParameters
    from mcp import ClientSession
except ImportError:
    pytest.skip("requires the `mcp` package — run from venv-mcp, see module docstring", allow_module_level=True)

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def _extract(result):
    if result.structured_content is not None:
        return result.structured_content
    return json.loads(result.content[0].text)


@pytest.fixture
def seeded_store(tmp_path):
    """Seeds an isolated claims store with 2 real claims (one a near-duplicate
    narrative of the other) via the actual pipeline logic — not hand-built
    fixtures — so the MCP tools are tested against genuine pipeline output."""
    store_path = str(tmp_path / "mcp_test_claims.json")
    os.environ["CLAIMS_STORE_PATH"] = store_path
    os.environ["GEMINI_API_KEY"] = ""  # MOCK_MODE

    from app import storage, pipeline
    from app.models import Claim

    claim_a = Claim(
        claim_type="home", claimant_id="CL-A", claimant_name="Claimant A", address="1 A St",
        policy_number="POL-A", policy_start_date="2025-01-01",
        raw_text="Vehicle stolen overnight from a secured parking garage, police FIR filed and attached.",
    ).model_dump()
    pipeline.process_claim(claim_a)

    claim_b = Claim(
        claim_type="home", claimant_id="CL-B", claimant_name="Claimant B", address="2 B St",
        policy_number="POL-B", policy_start_date="2025-01-01",
        raw_text="Car was stolen overnight from a secured parking garage, FIR has been filed and attached.",
    ).model_dump()
    pipeline.process_claim(claim_b)

    return store_path, claim_a["claim_id"], claim_b["claim_id"]


def test_mcp_server_over_real_stdio_transport(seeded_store):
    store_path, claim_a_id, claim_b_id = seeded_store

    async def _run():
        params = StdioServerParameters(
            command=sys.executable,
            args=[os.path.join(PROJECT_ROOT, "mcp_server.py")],
            cwd=PROJECT_ROOT,
            env={**os.environ, "CLAIMS_STORE_PATH": store_path, "GEMINI_API_KEY": ""},
        )
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                tools = await session.list_tools()
                tool_names = {t.name for t in tools.tools}
                assert tool_names == {"get_claim", "list_flagged_claims", "get_portfolio_analytics", "search_similar_claims"}

                flagged = _extract(await session.call_tool("list_flagged_claims", {"limit": 10}))["result"]
                assert len(flagged) == 2
                flagged_ids = {c["claim_id"] for c in flagged}
                assert flagged_ids == {claim_a_id, claim_b_id}

                claim = _extract(await session.call_tool("get_claim", {"claim_id": claim_a_id}))
                assert claim["claim_id"] == claim_a_id

                missing = _extract(await session.call_tool("get_claim", {"claim_id": "CG-NOPE"}))
                assert "error" in missing

                analytics = _extract(await session.call_tool("get_portfolio_analytics", {}))
                assert analytics["total_claims"] == 2
                assert analytics["retrieval_flag_type_counts"].get("similar_to_flagged_claim") == 1

                similar = _extract(await session.call_tool(
                    "search_similar_claims",
                    {"narrative_text": "Car taken overnight from a locked garage, FIR filed.", "top_k": 2},
                ))["result"]
                assert len(similar) == 2
                assert similar[0]["similarity"] > similar[1]["similarity"]

    asyncio.run(_run())


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
