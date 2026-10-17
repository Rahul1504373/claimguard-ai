"""
ClaimGuard AI — Deterministic-Agent Evaluation Harness
========================================================

WHAT THIS SCRIPT DOES
----------------------
Runs all 42 claims in claimguard_synthetic_claims.json through the REAL
Pattern Agent + Statistical Agent + Retrieval Agent (RAG — TF-IDF based,
also deterministic/free, added alongside RBAC in a later iteration) + the
deterministic risk-scoring formula (the same compute_deterministic_score()
used in production), and compares the resulting risk_tier against each
claim's `intended_flag` ground-truth label from the dataset. Reports
genuine, computed precision/recall/accuracy — not fabricated or assumed
numbers. Claims are processed in order and each one's computed status is
saved before moving to the next, exactly like the real pipeline, so the
Retrieval Agent's "was this similar past claim flagged?" check sees real,
already-computed history — not ground-truth labels leaking into the
comparison.

WHAT THIS SCRIPT DELIBERATELY DOES NOT EVALUATE, AND WHY
----------------------------------------------------------
It does NOT run the Extraction Agent or Consistency Agent (the two
Gemini-backed, multimodal stages). Two hard blockers make that impossible
to do honestly in this environment:

1. MOCK_MODE (no GEMINI_API_KEY configured) makes call_gemini_json() return
   a FIXED, hardcoded canned response for every single claim, regardless of
   input (see app/agents/extraction_agent.py / consistency_agent.py —
   MOCK_RESPONSE is a constant). Running the mocked pipeline against 42
   different claims would score 42 identical outputs against 42 different
   ground truths — a meaningless, misleading "accuracy" number.

2. The dataset's damage_photo fields are PLACEHOLDER FILENAMES
   (claimguard_dataset_methodology.md says so explicitly) — no actual image
   files exist for these 42 claims. Even with a real API key, there is
   nothing for Gemini's vision input to analyze.

So: this harness evaluates exactly what it can genuinely evaluate for
free — the two deterministic, non-LLM agents (Pattern + Statistical) and
the score/tier arithmetic — using the dataset's own ground-truth fields
(incident_date, claimed_amount, etc.) as a stand-in for "assume extraction
was perfect," so the deterministic logic can be isolated and measured on
its own. The 6 pure consistency-mismatch claims (CG-025 through CG-029,
which rely SOLELY on Gemini vision catching a narrative/photo mismatch)
are reported separately as "out of scope" rather than folded into the
headline accuracy number as false negatives — because failing to catch
them here is not a pattern/statistical agent failure, it's simply outside
what these two agents are designed to catch.

A genuine evaluation of the Gemini-backed stages would require: a real
GEMINI_API_KEY, actual photo files (one per claim, matching or deliberately
mismatching each damage_description), and would consume real API quota.
That is a legitimate next step but a different piece of work from this one.
"""
import json
import os
import sys
import tempfile

# Isolate this eval's claim store from any real app data — never touch
# data/claims_store.json.
_eval_store_path = os.path.join(tempfile.gettempdir(), "claimguard_eval_store.json")
if os.path.exists(_eval_store_path):
    os.remove(_eval_store_path)
os.environ["CLAIMS_STORE_PATH"] = _eval_store_path
os.environ.setdefault("GEMINI_API_KEY", "")  # force MOCK_MODE — irrelevant here since we bypass extraction/consistency

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import storage
from app.agents import pattern_agent, statistical_agent, retrieval_agent, explainability_agent

DATASET_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "claimguard_synthetic_claims.json")

# Claims whose ONLY intended signal is a pure photo/narrative mismatch —
# these require the Consistency Agent's real Gemini vision call, which this
# harness cannot run (see module docstring). Excluded from the headline
# accuracy metric and reported separately.
CONSISTENCY_ONLY_OUT_OF_SCOPE = {"CG-025", "CG-026", "CG-027", "CG-028", "CG-029"}
# CG-030 is deliberately NOT in this set: per the dataset notes, it also
# carries genuine shared_address_ring membership, which Pattern Agent CAN
# and should catch independently of the consistency mismatch.


def build_pipeline_claim(raw: dict) -> dict:
    """
    Maps a dataset record to the claim shape pattern_agent/statistical_agent
    expect, using the dataset's own ground-truth incident_date and
    claimed_amount as a stand-in for "extraction," since we are not running
    the real Extraction Agent in this harness (see module docstring).
    """
    return {
        "claim_id": raw["claim_id"],
        "claimant_id": raw["claimant_id"],
        "address": raw["address"],
        "policy_number": raw["policy_number"],
        "policy_start_date": raw["policy_start_date"],
        "incident_date": raw["incident_date"],
        "raw_text": raw["damage_description"],
        "claim_type": None,  # vehicle-number cross-check is a separate feature, not present in this dataset
        "declared_vehicle_number": None,
        "extracted": {
            "incident_date": raw["incident_date"],
            "claimed_amount": raw["claimed_amount"],
        },
    }


def ground_truth_should_flag(raw: dict) -> bool:
    return raw.get("intended_flag", "none").strip().lower() != "none" and not raw["intended_flag"].lower().startswith("none")


def main():
    with open(DATASET_PATH) as f:
        dataset = json.load(f)
    claims = dataset["claims"]

    rows = []
    for raw in claims:
        claim = build_pipeline_claim(raw)

        # Sequential processing (CG-001 first) mirrors production: pattern
        # checks compare each new claim against everything already saved.
        pattern_flags = pattern_agent.run(claim)
        claim["pattern_flags"] = pattern_flags
        storage.save_claim(claim)

        claim_history = storage.list_claims()
        statistical_flags = statistical_agent.run(claim, claim_history)

        retrieval = retrieval_agent.run(claim, claim_history)
        retrieval_flags = retrieval["retrieval_flags"]

        scored = explainability_agent.compute_deterministic_score(
            consistency_flags=[],  # Consistency Agent not evaluated here — see module docstring
            pattern_flags=pattern_flags,
            statistical_flags=statistical_flags,
            retrieval_flags=retrieval_flags,
        )

        # Save the computed status BEFORE the next claim is processed — same
        # ordering as the real pipeline (app/pipeline.py) — so Retrieval
        # Agent's "was the similar past claim actually flagged?" check for
        # later claims reflects real computed history, not ground truth.
        claim["status"] = "flagged" if scored["risk_tier"] in ("moderate", "high") else "cleared"
        claim["explainability"] = {"risk_tier": scored["risk_tier"], "risk_score": scored["risk_score"]}
        storage.save_claim(claim)

        predicted_flagged = scored["risk_tier"] in ("moderate", "high")
        expected_flagged = ground_truth_should_flag(raw)
        out_of_scope = raw["claim_id"] in CONSISTENCY_ONLY_OUT_OF_SCOPE

        rows.append({
            "claim_id": raw["claim_id"],
            "intended_flag": raw.get("intended_flag", "none"),
            "expected_flagged": expected_flagged,
            "predicted_flagged": predicted_flagged,
            "risk_tier": scored["risk_tier"],
            "risk_score": scored["risk_score"],
            "pattern_flag_types": [f["type"] for f in pattern_flags],
            "statistical_flag_types": [f["type"] for f in statistical_flags],
            "retrieval_flag_types": [f["type"] for f in retrieval_flags],
            "similar_claims": retrieval["similar_claims"],
            "out_of_scope": out_of_scope,
        })

    os.remove(_eval_store_path)
    return rows


def summarize(rows):
    in_scope = [r for r in rows if not r["out_of_scope"]]
    out_of_scope = [r for r in rows if r["out_of_scope"]]

    tp = sum(1 for r in in_scope if r["expected_flagged"] and r["predicted_flagged"])
    fp = sum(1 for r in in_scope if not r["expected_flagged"] and r["predicted_flagged"])
    tn = sum(1 for r in in_scope if not r["expected_flagged"] and not r["predicted_flagged"])
    fn = sum(1 for r in in_scope if r["expected_flagged"] and not r["predicted_flagged"])

    accuracy = (tp + tn) / len(in_scope) if in_scope else 0
    precision = tp / (tp + fp) if (tp + fp) else None
    recall = tp / (tp + fn) if (tp + fn) else None

    return {
        "total_claims": len(rows),
        "in_scope_claims": len(in_scope),
        "out_of_scope_claims": len(out_of_scope),
        "true_positives": tp, "false_positives": fp,
        "true_negatives": tn, "false_negatives": fn,
        "accuracy": accuracy, "precision": precision, "recall": recall,
        "rows": rows,
    }


if __name__ == "__main__":
    rows = main()
    summary = summarize(rows)
    print(json.dumps(summary, indent=2))
