import logging
from app.config import settings
from app.gemini_client import call_gemini_json

logger = logging.getLogger("claimguard.explainability_agent")

SYSTEM_PROMPT = """You are writing a risk assessment summary for an insurance claims adjuster.
Given the extracted claim data, consistency flags, pattern flags,
statistical flags, and retrieved similar past claims below, produce a
clear, professional rationale a human adjuster can act on and defend to a
compliance reviewer.

RETRIEVED CONTEXT: The "Similar past claims" list was found by a retrieval
step that compares this claim's narrative against historical claims
(RAG — retrieval-augmented generation). If any similar claim is relevant to
your rationale (e.g. this claim resembles a past claim that was flagged),
reference it by its claim_id. Do not invent similarities beyond what's
listed — only cite what's actually in that list.

CURRENCY: All monetary amounts in this system are in Indian Rupees (INR).
Always write amounts using the ₹ symbol or the word "rupees" — never $ or
any other currency symbol, regardless of how the number is formatted in
the input data.

Compute a risk_score (0-100) using this weighting, and BASE your output only
on this formula — do not invent a different score:
- Each "high" severity consistency flag: +35
- Each "medium" severity consistency flag: +15
- Each "low" severity consistency flag: +5
- Each pattern flag (any type): +25
- Each statistical flag (Benford's Law nonconformity or Isolation Forest outlier): +15
- Each retrieval flag (similar_to_flagged_claim): +20
- Base score: 0
Cap at 100.

risk_tier: "low" if score < 30, "moderate" if 30-64, "high" if >= 65.

Return JSON:
{
  "risk_score": number,
  "risk_tier": "low" | "moderate" | "high",
  "rationale": string,
  "recommended_action": string
}
"""


def compute_deterministic_score(
    consistency_flags: list[dict], pattern_flags: list[dict], statistical_flags: list[dict],
    retrieval_flags: list[dict] = None,
) -> dict:
    """
    The single source of truth for risk_score/risk_tier/recommended_action —
    used for BOTH the mock path and, critically, the REAL Gemini path too.

    Why this matters beyond mock mode: Gemini is instructed to apply this
    same formula and asked to self-report a score, but nothing previously
    verified it actually did. risk_tier isn't just displayed text — it
    directly sets claim["status"] to flagged/cleared in pipeline.py — so an
    ungrounded or miscalculated self-reported score would silently produce
    a wrong claim status, not just a cosmetic number. A fixed-formula
    calculation is arithmetic, not reasoning over unstructured evidence, so
    per this project's own architecture principle (Gemini for evidence
    reasoning, deterministic logic for what needs to be reliable and
    auditable), this is computed here in Python and treated as
    authoritative — never left to free generation, in mock OR real mode.

    retrieval_flags weighting (+20, between pattern's +25 exact-signal
    weight and statistical's +15 anomaly weight): a narrative-similarity
    match to a past flagged claim (see app/agents/retrieval_agent.py) is a
    real signal but a softer one than an exact rule match (duplicate
    policy_number, shared address) — it can be coincidental phrasing
    overlap, not necessarily fraud — so it's weighted accordingly rather
    than treated as equally conclusive.
    """
    retrieval_flags = retrieval_flags or []
    score = 0
    for f in consistency_flags:
        score += {"high": 35, "medium": 15, "low": 5}.get(f.get("severity"), 0)
    score += 25 * len(pattern_flags)
    score += 15 * len(statistical_flags)
    score += 20 * len(retrieval_flags)
    score = min(score, 100)
    tier = "low" if score < 30 else "moderate" if score < 65 else "high"
    action = "Escalate to SIU" if tier == "high" else "Request additional documentation" if tier == "moderate" else "Approve"
    return {"risk_score": score, "risk_tier": tier, "recommended_action": action}


def _fallback_rationale(consistency_flags: list[dict], pattern_flags: list[dict],
                         statistical_flags: list[dict], retrieval_flags: list[dict], computed: dict) -> str:
    """Used for mock mode, and as a safety net if Gemini's response is
    missing a rationale entirely — never left blank."""
    reasons = (
        [f.get("issue", "") for f in consistency_flags]
        + [f.get("detail", "") for f in pattern_flags]
        + [f.get("detail", "") for f in statistical_flags]
        + [f.get("detail", "") for f in retrieval_flags]
    )
    reasons = [r for r in reasons if r]
    return (
        f"Risk score {computed['risk_score']}/100 ({computed['risk_tier']}). "
        + (" ".join(reasons) if reasons else "No issues detected.")
    )


def run(extracted: dict, consistency: dict, pattern_flags: list[dict], statistical_flags: list[dict] = None,
        retrieval_flags: list[dict] = None, similar_claims: list[dict] = None) -> dict:
    statistical_flags = statistical_flags or []
    retrieval_flags = retrieval_flags or []
    similar_claims = similar_claims or []
    consistency_flags = consistency.get("consistency_flags", [])

    computed = compute_deterministic_score(consistency_flags, pattern_flags, statistical_flags, retrieval_flags)
    mock_response = {
        **computed,
        "rationale": _fallback_rationale(consistency_flags, pattern_flags, statistical_flags, retrieval_flags, computed),
    }

    user_content = [
        f"Extracted data: {extracted}",
        f"Consistency flags: {consistency_flags}",
        f"Pattern flags: {pattern_flags}",
        f"Statistical flags: {statistical_flags}",
        f"Retrieval flags: {retrieval_flags}",
        f"Similar past claims (RAG context — cite only what's listed here): {similar_claims}",
    ]

    result = call_gemini_json(
        model=settings.EXPLAINABILITY_MODEL,
        system_prompt=SYSTEM_PROMPT,
        user_content=user_content,
        mock_response=mock_response,
    )

    # Authoritative override — applies in BOTH mock and real modes, so the
    # returned risk_score/risk_tier/recommended_action are always the
    # verified, reproducible Python computation, never Gemini's
    # self-reported (and unverified) numbers. Only the rationale text is
    # taken from Gemini's actual output, since that's where free generation
    # genuinely adds value — synthesizing a readable, evidence-cited
    # narrative is not something a fixed formula can do.
    reported_score = result.get("risk_score")
    if reported_score != computed["risk_score"]:
        logger.warning(
            f"Gemini's self-reported risk_score ({reported_score}) did not match the "
            f"deterministic calculation ({computed['risk_score']}) — using the deterministic "
            f"value. This is expected occasionally (model drift) and is exactly why the score "
            f"is never trusted from free generation alone."
        )

    result["risk_score"] = computed["risk_score"]
    result["risk_tier"] = computed["risk_tier"]
    result["recommended_action"] = computed["recommended_action"]
    if not result.get("rationale"):
        result["rationale"] = _fallback_rationale(consistency_flags, pattern_flags, statistical_flags, retrieval_flags, computed)

    return result
