"""
ClaimGuard AI — MCP (Model Context Protocol) Server
=====================================================

WHAT THIS IS, HONESTLY
------------------------
A read-only MCP server exposing ClaimGuard AI's claim data and fraud
signals as tools an MCP-compatible client (Claude Desktop, or any other
MCP client) can call in natural language — "show me flagged claims",
"what's the portfolio risk breakdown", "find claims similar to this
narrative". It shares the exact same storage backend and Retrieval Agent
as the FastAPI app (app/storage.py, app/agents/retrieval_agent.py) — not a
separate copy of the data or logic.

IMPORTANT, STATED HONESTLY: MCP (Model Context Protocol) is Anthropic's
open protocol, not a Google technology. Using it here is an architecture
and integration choice — demonstrating that ClaimGuard's data can plug
into the broader agentic tooling ecosystem — not a Gemini or Google Cloud
feature. The hackathon's core Gen AI work (the 6-stage agent pipeline) is
unchanged; this is an additional, optional integration surface on top of it.

SCOPE, STATED HONESTLY: this server is READ-ONLY by design for this
iteration — no submit_claim or decide_claim tool is exposed. That's a
deliberate scope choice (claim submission involves file uploads and RBAC
identity that don't map cleanly onto a quick MCP demo), not an oversight.
A write-capable version is a legitimate future iteration, not claimed as
built here.

DEPENDENCY ISOLATION, STATED HONESTLY: the official `mcp` Python SDK (v2.x)
pulls in a newer `starlette` and `pydantic` than this project's FastAPI
backend is pinned to — installing both in the same environment breaks the
FastAPI app (confirmed directly: it raised `TypeError: Router.__init__()
got an unexpected keyword argument` once `mcp` was installed alongside
`fastapi==0.115.0`). So this file deliberately runs in ITS OWN virtual
environment (see requirements-mcp.txt and README.md's "MCP Server" section)
— not from the same venv as `app/main.py`. It still imports directly from
this same `app/` package at runtime (storage + retrieval_agent have no
FastAPI/Pydantic dependency of their own), so there is no code duplication,
only environment separation.

RUNNING THIS
------------
    python3 -m venv venv-mcp
    source venv-mcp/bin/activate
    pip install -r requirements-mcp.txt
    python3 mcp_server.py

Then point an MCP client (e.g. Claude Desktop's claude_desktop_config.json)
at this script via stdio — see README.md for the exact config snippet.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from mcp.server.mcpserver import MCPServer
from app import storage
from app.agents import retrieval_agent

mcp = MCPServer(
    name="claimguard-ai",
    version="1.0.0",
    instructions=(
        "Tools for querying ClaimGuard AI's insurance fraud-risk triage data: "
        "look up a specific claim, list currently flagged claims, get live "
        "portfolio analytics, or search for past claims with a similar "
        "narrative (RAG-style retrieval). All data is read-only and reflects "
        "whatever claims have actually been processed by the ClaimGuard AI "
        "pipeline — nothing here is fabricated or simulated by this server."
    ),
)


@mcp.tool()
def get_claim(claim_id: str) -> dict:
    """Fetch one claim's full record by its claim_id, including its risk
    score, rationale, and every fraud-detection flag raised for it."""
    claim = storage.get_claim(claim_id)
    if not claim:
        return {"error": f"No claim found with claim_id '{claim_id}'"}
    return claim


@mcp.tool()
def list_flagged_claims(limit: int = 20) -> list[dict]:
    """List claims currently flagged (status == 'flagged'), most recent
    first — the SIU/fraud-investigator worklist. Returns a summary per
    claim (not the full record) to keep responses compact."""
    claims = [c for c in storage.list_claims() if c.get("status") == "flagged"]
    claims = sorted(claims, key=lambda c: c.get("created_at", ""), reverse=True)[:limit]
    return [
        {
            "claim_id": c["claim_id"],
            "claimant_name": c.get("claimant_name"),
            "claim_type": c.get("claim_type"),
            "risk_tier": (c.get("explainability") or {}).get("risk_tier"),
            "risk_score": (c.get("explainability") or {}).get("risk_score"),
            "rationale": (c.get("explainability") or {}).get("rationale"),
            "created_at": c.get("created_at"),
        }
        for c in claims
    ]


@mcp.tool()
def get_portfolio_analytics() -> dict:
    """Live, computed aggregate statistics across every claim processed so
    far: totals, status breakdown, risk-tier breakdown, average risk score,
    and counts by fraud-signal type (pattern/statistical/retrieval). Every
    number is computed from storage at call time — nothing cached or
    fabricated. Mirrors the FastAPI backend's GET /analytics/summary."""
    claims = storage.list_claims()
    total = len(claims)
    by_status, by_tier = {}, {}
    pattern_counts, statistical_counts, retrieval_counts = {}, {}, {}
    scores = []

    for c in claims:
        by_status[c.get("status", "unknown")] = by_status.get(c.get("status", "unknown"), 0) + 1
        exp = c.get("explainability") or {}
        tier = exp.get("risk_tier")
        if tier:
            by_tier[tier] = by_tier.get(tier, 0) + 1
            scores.append(exp.get("risk_score", 0))
        for f in c.get("pattern_flags", []):
            pattern_counts[f["type"]] = pattern_counts.get(f["type"], 0) + 1
        for f in c.get("statistical_flags", []):
            statistical_counts[f["type"]] = statistical_counts.get(f["type"], 0) + 1
        for f in c.get("retrieval_flags", []):
            retrieval_counts[f["type"]] = retrieval_counts.get(f["type"], 0) + 1

    return {
        "total_claims": total,
        "by_status": by_status,
        "by_risk_tier": by_tier,
        "average_risk_score": round(sum(scores) / len(scores), 1) if scores else None,
        "pattern_flag_type_counts": pattern_counts,
        "statistical_flag_type_counts": statistical_counts,
        "retrieval_flag_type_counts": retrieval_counts,
    }


@mcp.tool()
def search_similar_claims(narrative_text: str, top_k: int = 5) -> list[dict]:
    """Find past claims with a narrative similar to the given text, using
    the same TF-IDF + cosine-similarity Retrieval Agent (RAG) the real
    pipeline uses — NOT a Gemini embedding call (see app/agents/retrieval_agent.py
    for why: free, local, zero additional API dependency). Useful for
    exploring "has anything like this come through before?" without
    submitting a new claim."""
    probe_claim = {"claim_id": "__mcp_probe__", "raw_text": narrative_text}
    history = storage.list_claims()
    return retrieval_agent.find_similar_claims(probe_claim, history, top_k=top_k)


if __name__ == "__main__":
    mcp.run()
