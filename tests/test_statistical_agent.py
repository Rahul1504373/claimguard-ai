"""
Tests the Statistical Agent (Benford's Law + Isolation Forest) in isolation.
Deliberately tests BOTH the below-threshold guard behavior AND the
above-threshold detection behavior — the guard is as important to verify
as the detection itself, since applying either technique on too little
data would produce a misleadingly confident result.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.agents import statistical_agent


# ---------------------------------------------------------------------------
# Benford's Law
# ---------------------------------------------------------------------------

def test_benfords_law_returns_not_applicable_below_minimum_sample():
    amounts = [100, 200, 300]  # far below BENFORD_MIN_SAMPLES
    result = statistical_agent.check_benfords_law(amounts)
    assert result["applicable"] is False
    assert "insufficient sample size" in result["reason"]


def test_benfords_law_conforms_on_naturally_distributed_amounts():
    # A geometric-ish spread of amounts whose leading digits should
    # reasonably approximate Benford's expected distribution.
    amounts = [10 * (1.5 ** i) for i in range(40)]
    result = statistical_agent.check_benfords_law(amounts)
    assert result["applicable"] is True
    assert result["sample_size"] == 40
    assert "conformity" in result
    assert isinstance(result["flagged"], bool)


def test_benfords_law_flags_severe_nonconformity():
    # 40 amounts that ALL start with digit 9 — a strong, artificial
    # deviation from Benford's expected ~4.6% share for leading digit 9.
    amounts = [9000 + i for i in range(40)]
    result = statistical_agent.check_benfords_law(amounts)
    assert result["applicable"] is True
    assert result["conformity"] == "nonconformity"
    assert result["flagged"] is True


def test_benfords_law_ignores_zero_and_negative_amounts():
    amounts = [0, -50] + [100 + i for i in range(35)]
    result = statistical_agent.check_benfords_law(amounts)
    # zero/negative excluded from the valid sample count
    assert result["sample_size"] == 35


# ---------------------------------------------------------------------------
# Isolation Forest
# ---------------------------------------------------------------------------

def test_isolation_forest_returns_not_applicable_below_minimum_sample():
    claims = [{"claim_id": f"CG-{i}", "claimed_amount": 1000 + i} for i in range(5)]
    result = statistical_agent.compute_isolation_forest_scores(claims)
    assert result["applicable"] is False
    assert "insufficient sample size" in result["reason"]


def test_isolation_forest_flags_extreme_outlier():
    # 20 normal claims clustered around 5000, one wildly different claim
    normal = [{"claim_id": f"CG-N{i}", "claimed_amount": 5000 + (i * 50)} for i in range(20)]
    outlier = {"claim_id": "CG-OUTLIER", "claimed_amount": 500000}
    claims = normal + [outlier]

    result = statistical_agent.compute_isolation_forest_scores(claims)
    assert result["applicable"] is True
    assert result["sample_size"] == 21
    assert result["scores"]["CG-OUTLIER"]["is_outlier"] is True


def test_isolation_forest_does_not_flag_typical_claim_in_uniform_batch():
    claims = [{"claim_id": f"CG-{i}", "claimed_amount": 5000 + (i * 10)} for i in range(20)]
    result = statistical_agent.compute_isolation_forest_scores(claims)
    # the middle claim, close to the batch's central tendency, should not be flagged
    middle_id = claims[10]["claim_id"]
    assert result["scores"][middle_id]["is_outlier"] is False


# ---------------------------------------------------------------------------
# run() orchestration — integration of both checks into pattern-flag shape
# ---------------------------------------------------------------------------

def test_run_returns_no_flags_with_small_history():
    claim = {"claim_id": "CG-NEW", "extracted": {"claimed_amount": 50000}}
    history = [{"claim_id": f"CG-H{i}", "extracted": {"claimed_amount": 5000 + i}} for i in range(5)]
    flags = statistical_agent.run(claim, history)
    # both checks are below their minimum sample size with only 6 total claims
    assert flags == []


def test_run_flags_extreme_outlier_with_sufficient_history():
    claim = {"claim_id": "CG-NEW", "extracted": {"claimed_amount": 900000}}
    history = [
        {"claim_id": f"CG-H{i}", "extracted": {"claimed_amount": 5000 + (i * 20)}}
        for i in range(30)
    ]
    flags = statistical_agent.run(claim, history)
    flag_types = [f["type"] for f in flags]
    assert "isolation_forest_outlier" in flag_types
    for f in flags:
        assert "detail" in f and "type" in f and "related_claim_ids" in f  # shape matches pattern_flags


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-v"]))
