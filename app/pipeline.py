from app import storage
from app.models import now_iso
from app.agents import (
    extraction_agent, consistency_agent, pattern_agent, statistical_agent,
    retrieval_agent, explainability_agent,
)


def _log(claim: dict, step: str, output: dict | list):
    claim["agent_trace"].append({"step": step, "output": output, "timestamp": now_iso()})


def process_claim(claim: dict) -> dict:
    """Runs claim through Extraction -> Consistency -> Pattern -> Statistical
    -> Retrieval (RAG) -> Explainability, saving progress after each step so
    partial results survive a mid-pipeline crash and the audit trail is
    always accurate up to the point of failure."""
    claim["status"] = "processing"
    storage.save_claim(claim)

    try:
        extracted = extraction_agent.run(claim["raw_text"], claim["file_urls"])
        claim["extracted"] = extracted
        _log(claim, "extraction", extracted)
        storage.save_claim(claim)

        consistency = consistency_agent.run(extracted, claim["file_urls"])
        claim["consistency"] = consistency
        _log(claim, "consistency", consistency)
        storage.save_claim(claim)

        pattern_flags = pattern_agent.run(claim)
        claim["pattern_flags"] = pattern_flags
        _log(claim, "pattern", pattern_flags)
        storage.save_claim(claim)

        claim_history = storage.list_claims()  # comparison pool for statistical + retrieval checks
        statistical_flags = statistical_agent.run(claim, claim_history)
        claim["statistical_flags"] = statistical_flags
        _log(claim, "statistical", statistical_flags)
        storage.save_claim(claim)

        retrieval = retrieval_agent.run(claim, claim_history)
        claim["similar_claims"] = retrieval["similar_claims"]
        claim["retrieval_flags"] = retrieval["retrieval_flags"]
        _log(claim, "retrieval", retrieval)
        storage.save_claim(claim)

        explainability = explainability_agent.run(
            extracted, consistency, pattern_flags, statistical_flags,
            retrieval_flags=retrieval["retrieval_flags"],
            similar_claims=retrieval["similar_claims"],
        )
        claim["explainability"] = explainability
        _log(claim, "explainability", explainability)

        claim["status"] = "flagged" if explainability["risk_tier"] in ("moderate", "high") else "cleared"
        claim["updated_at"] = now_iso()
        storage.save_claim(claim)

    except Exception as e:
        claim["status"] = "error"
        _log(claim, "error", {"message": str(e)})
        storage.save_claim(claim)
        raise

    return claim
