"""
Tests the Retrieval Agent (ClaimGuard AI's RAG layer) in isolation.
Covers the below-threshold guard, genuine similarity ranking via real
TF-IDF + cosine similarity (not mocked math), and the new deterministic
similar_to_flagged_claim signal — including that it does NOT fire for a
similar claim that was never flagged, which is the case that would make
this a noisy, untrustworthy signal if it were wrong.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.agents import retrieval_agent


def _claim(claim_id, raw_text, risk_tier=None, status="cleared"):
    c = {"claim_id": claim_id, "raw_text": raw_text, "status": status}
    if risk_tier:
        c["explainability"] = {"risk_tier": risk_tier}
    return c


def test_returns_empty_with_no_history_at_all():
    current = _claim("CG-NEW", "Car was stolen from a parking garage overnight.")
    result = retrieval_agent.find_similar_claims(current, [])
    assert result == []  # nothing to retrieve against


def test_finds_similar_claim_with_just_a_single_prior_claim():
    # Unlike Benford's Law/Isolation Forest, pairwise text similarity needs
    # no statistical sample size — even ONE prior claim is a valid, genuine
    # comparison. This is the realistic early-demo case (2nd claim ever
    # submitted) and must not be silently suppressed.
    current = _claim("CG-NEW", "Vehicle stolen overnight from a secured parking garage, police FIR filed.")
    history = [_claim("CG-001", "Vehicle stolen overnight from a secured parking garage, FIR attached.", status="cleared")]
    result = retrieval_agent.find_similar_claims(current, history)
    assert len(result) == 1
    assert result[0]["claim_id"] == "CG-001"
    assert result[0]["similarity"] > 0.5


def test_finds_genuinely_similar_claim_by_narrative_text():
    current = _claim("CG-NEW", "Vehicle stolen overnight from a secured parking garage, police FIR filed.")
    history = [
        _claim("CG-001", "Vehicle stolen overnight from a secured parking garage, FIR attached.", status="cleared"),
        _claim("CG-002", "Kitchen flooded due to a burst pipe, water damage to flooring.", status="cleared"),
        _claim("CG-003", "Minor fender scrape in a parking lot, low-speed collision.", status="cleared"),
    ]
    results = retrieval_agent.find_similar_claims(current, history, top_k=3)
    assert results  # genuinely found something
    assert results[0]["claim_id"] == "CG-001"  # the real near-duplicate narrative ranks first
    assert results[0]["similarity"] > results[1]["similarity"]  # real ranking, not arbitrary order


def test_similarity_flag_fires_for_match_to_a_flagged_claim():
    current = _claim("CG-NEW", "Vehicle stolen overnight from a secured parking garage, police FIR filed.")
    history = [
        _claim("CG-001", "Vehicle stolen overnight from a secured parking garage, FIR attached.",
               risk_tier="high", status="flagged"),
        _claim("CG-002", "Kitchen flooded due to a burst pipe, unrelated narrative text here.", status="cleared"),
    ]
    output = retrieval_agent.run(current, history)
    flag_types = [f["type"] for f in output["retrieval_flags"]]
    assert "similar_to_flagged_claim" in flag_types
    assert output["retrieval_flags"][0]["related_claim_ids"] == ["CG-001"]


def test_no_flag_when_similar_claim_was_never_flagged():
    # Same high-similarity narrative, but the matching past claim was
    # CLEARED, not flagged — this must NOT raise similar_to_flagged_claim,
    # otherwise the signal would just mean "any similar wording", which
    # is not what it claims to detect.
    current = _claim("CG-NEW", "Vehicle stolen overnight from a secured parking garage, police FIR filed.")
    history = [
        _claim("CG-001", "Vehicle stolen overnight from a secured parking garage, FIR attached.",
               risk_tier="low", status="cleared"),
        _claim("CG-002", "Kitchen flooded due to a burst pipe, unrelated narrative text here.", status="cleared"),
    ]
    output = retrieval_agent.run(current, history)
    assert output["retrieval_flags"] == []
    assert output["similar_claims"]  # still surfaced as RAG context, just not flagged


def test_no_flag_for_dissimilar_claims_even_if_history_has_flagged_ones():
    current = _claim("CG-NEW", "Laptop screen cracked when dropped at home, replacement needed.")
    history = [
        _claim("CG-001", "Vehicle stolen overnight from a secured parking garage, FIR attached.",
               risk_tier="high", status="flagged"),
        _claim("CG-002", "Kitchen flooded due to a burst pipe, water damage to flooring.", status="cleared"),
    ]
    output = retrieval_agent.run(current, history)
    assert output["retrieval_flags"] == []


def test_excludes_itself_from_its_own_history():
    current = _claim("CG-SELF", "Vehicle stolen overnight from a secured parking garage, police FIR filed.")
    history = [
        current,  # pipeline.py saves the claim before calling this agent, so it's in its own history pool
        _claim("CG-001", "Vehicle stolen overnight from a secured parking garage, FIR attached.", status="cleared"),
        _claim("CG-002", "Kitchen flooded due to a burst pipe, water damage to flooring.", status="cleared"),
    ]
    results = retrieval_agent.find_similar_claims(current, history)
    assert all(r["claim_id"] != "CG-SELF" for r in results)


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-v"]))
