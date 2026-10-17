"""
Runs with NO Gemini API key set, so `pytest` exercises the full pipeline
logic (extraction -> consistency -> pattern -> explainability -> storage)
for $0 and with no network calls. This is what you run before ever
spending real API quota, and what you can point to in your deck as
evidence of a tested, working prototype.
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

os.environ["CLAIMS_STORE_PATH"] = os.path.join(tempfile.mkdtemp(), "test_claims.json")

from app import storage, pipeline
from app.models import Claim


def make_claim(**overrides) -> dict:
    defaults = dict(
        claimant_id="CL-TEST-1",
        claimant_name="Test Claimant",
        address="1 Test Street, Test City",
        policy_number="POL-TEST-1",
        policy_start_date="2025-01-01",
        raw_text="Major front-end collision damage, vehicle undrivable.",
        file_urls=[],
    )
    defaults.update(overrides)
    return Claim(**defaults).model_dump()


def test_single_claim_processes_end_to_end():
    claim = make_claim()
    result = pipeline.process_claim(claim)

    assert result["status"] in ("flagged", "cleared")
    assert result["extracted"] is not None
    assert result["consistency"] is not None
    assert result["explainability"] is not None
    assert 0 <= result["explainability"]["risk_score"] <= 100
    # Mock extraction/consistency responses simulate a high-severity mismatch,
    # so with no pattern flags this should land as "flagged".
    assert result["status"] == "flagged"
    assert result["explainability"]["risk_tier"] == "moderate"


def test_agent_trace_is_logged_for_audit():
    claim = make_claim()
    result = pipeline.process_claim(claim)
    steps = [t["step"] for t in result["agent_trace"]]
    assert steps == ["extraction", "consistency", "pattern", "statistical", "retrieval", "explainability"]


def test_repeat_claimant_pattern_flag():
    # Seed two prior claims for the same claimant
    for i in range(2):
        c = make_claim(claimant_id="CL-REPEAT")
        c["claim_id"] = f"CG-PRIOR-{i}"
        c["extracted"] = {"incident_date": "2026-01-01"}
        storage.save_claim(c)

    claim = make_claim(claimant_id="CL-REPEAT")
    result = pipeline.process_claim(claim)

    flag_types = [f["type"] for f in result["pattern_flags"]]
    assert "repeat_claimant" in flag_types


def test_shared_address_ring_flag():
    other = make_claim(claimant_id="CL-OTHER", address="99 Ring Road, Ring City")
    other["claim_id"] = "CG-RING-0"
    storage.save_claim(other)

    claim = make_claim(claimant_id="CL-NEW", address="99 Ring Road, Ring City")
    result = pipeline.process_claim(claim)

    flag_types = [f["type"] for f in result["pattern_flags"]]
    assert "shared_address_ring" in flag_types


def test_clean_claim_with_no_flags_scores_low():
    """Directly exercises explainability_agent's scoring formula in isolation
    with an empty flag set, independent of the (fixed) mock extraction data."""
    from app.agents import explainability_agent
    result = explainability_agent.run(
        extracted={"incident_type": "Auto collision"},
        consistency={"consistency_flags": []},
        pattern_flags=[],
    )
    assert result["risk_score"] == 0
    assert result["risk_tier"] == "low"
    assert result["recommended_action"] == "Approve"


def test_pattern_agent_scoring_matches_explainability_formula():
    from app.agents import explainability_agent
    consistency_flags = [{"severity": "high"}, {"severity": "low"}]
    pattern_flags = [{"type": "repeat_claimant", "detail": "x"}]
    result = explainability_agent.run(
        extracted={}, consistency={"consistency_flags": consistency_flags}, pattern_flags=pattern_flags
    )
    # 35 (high) + 5 (low) + 25 (1 pattern flag) = 65 -> high
    assert result["risk_score"] == 65
    assert result["risk_tier"] == "high"


# ---------------------------------------------------------------------------
# Additional pattern_agent scenarios not covered above: policy-date anomaly,
# duplicate submission, and claim-frequency spike. These call pattern_agent
# directly (not through the mocked pipeline) since they depend on specific
# claim field combinations the mock extraction data doesn't produce.
# ---------------------------------------------------------------------------

def test_policy_date_anomaly_flag():
    from app.agents import pattern_agent
    claim = make_claim(policy_start_date="2026-07-10")
    claim["extracted"] = {"incident_date": "2026-07-05"}  # 5 days BEFORE policy start
    flags = pattern_agent.run(claim)
    types = [f["type"] for f in flags]
    assert "policy_date_anomaly" in types
    anomaly = next(f for f in flags if f["type"] == "policy_date_anomaly")
    assert "5 day" in anomaly["detail"]


def test_no_policy_date_anomaly_when_incident_after_start():
    from app.agents import pattern_agent
    claim = make_claim(policy_start_date="2025-01-01")
    claim["extracted"] = {"incident_date": "2026-07-05"}  # after policy start — fine
    flags = pattern_agent.run(claim)
    types = [f["type"] for f in flags]
    assert "policy_date_anomaly" not in types


def test_duplicate_submission_flag():
    from app.agents import pattern_agent
    original = make_claim(policy_number="POL-DUPTEST", raw_text="Identical narrative text.")
    original["claim_id"] = "CG-ORIGINAL"
    storage.save_claim(original)

    resubmission = make_claim(policy_number="POL-DUPTEST", raw_text="Identical narrative text.")
    flags = pattern_agent.run(resubmission)
    types = [f["type"] for f in flags]
    assert "duplicate_submission" in types


def test_no_duplicate_flag_for_different_narrative():
    from app.agents import pattern_agent
    original = make_claim(policy_number="POL-DUPTEST2", raw_text="First incident narrative.")
    original["claim_id"] = "CG-ORIGINAL-2"
    storage.save_claim(original)

    different = make_claim(policy_number="POL-DUPTEST2", raw_text="A completely different incident.")
    flags = pattern_agent.run(different)
    types = [f["type"] for f in flags]
    assert "duplicate_submission" not in types


def test_claim_frequency_spike_flag():
    from app.agents import pattern_agent
    claimant = "CL-FREQ-TEST"
    # Two prior claims within the 45-day window
    for i, d in enumerate(["2026-06-01", "2026-06-20"]):
        c = make_claim(claimant_id=claimant)
        c["claim_id"] = f"CG-FREQ-{i}"
        c["extracted"] = {"incident_date": d}
        storage.save_claim(c)

    claim = make_claim(claimant_id=claimant)
    claim["extracted"] = {"incident_date": "2026-07-14"}  # within 45 days of both
    flags = pattern_agent.run(claim)
    types = [f["type"] for f in flags]
    assert "claim_frequency_spike" in types


def test_no_frequency_spike_when_claims_far_apart():
    from app.agents import pattern_agent
    claimant = "CL-FREQ-TEST-2"
    for i, d in enumerate(["2025-01-01", "2025-06-01"]):  # far outside any 45-day window
        c = make_claim(claimant_id=claimant)
        c["claim_id"] = f"CG-SPREAD-{i}"
        c["extracted"] = {"incident_date": d}
        storage.save_claim(c)

    claim = make_claim(claimant_id=claimant)
    claim["extracted"] = {"incident_date": "2026-07-14"}
    flags = pattern_agent.run(claim)
    types = [f["type"] for f in flags]
    assert "claim_frequency_spike" not in types


# ---------------------------------------------------------------------------
# Explainability scoring — medium and low severity paths, and the tier
# boundaries themselves (previously only "high" and "empty" were tested).
# ---------------------------------------------------------------------------

def test_medium_severity_scores_into_moderate_tier():
    from app.agents import explainability_agent
    result = explainability_agent.run(
        extracted={}, consistency={"consistency_flags": [{"severity": "medium"}]}, pattern_flags=[]
    )
    assert result["risk_score"] == 15
    assert result["risk_tier"] == "low"  # 15 < 30 threshold


def test_low_severity_alone_stays_low_tier():
    from app.agents import explainability_agent
    result = explainability_agent.run(
        extracted={}, consistency={"consistency_flags": [{"severity": "low"}]}, pattern_flags=[]
    )
    assert result["risk_score"] == 5
    assert result["risk_tier"] == "low"
    assert result["recommended_action"] == "Approve"


def test_score_caps_at_100():
    from app.agents import explainability_agent
    consistency_flags = [{"severity": "high"}] * 5  # 5 * 35 = 175, should cap at 100
    result = explainability_agent.run(
        extracted={}, consistency={"consistency_flags": consistency_flags}, pattern_flags=[]
    )
    assert result["risk_score"] == 100
    assert result["risk_tier"] == "high"


def test_tier_boundary_moderate_starts_at_30():
    from app.agents import explainability_agent
    # 2 medium flags = 30, should be exactly the moderate threshold
    result = explainability_agent.run(
        extracted={}, consistency={"consistency_flags": [{"severity": "medium"}, {"severity": "medium"}]},
        pattern_flags=[]
    )
    assert result["risk_score"] == 30


def test_retrieval_flag_contributes_20_points_to_score():
    from app.agents import explainability_agent
    retrieval_flags = [{"type": "similar_to_flagged_claim", "detail": "x", "related_claim_ids": ["CG-001"]}]
    result = explainability_agent.run(
        extracted={}, consistency={"consistency_flags": []}, pattern_flags=[],
        statistical_flags=[], retrieval_flags=retrieval_flags,
    )
    assert result["risk_score"] == 20
    assert result["risk_tier"] == "low"  # below the 30-point moderate threshold on its own


def test_retrieval_flag_combined_with_pattern_flag_crosses_into_moderate():
    from app.agents import explainability_agent
    pattern_flags = [{"type": "repeat_claimant", "detail": "x", "related_claim_ids": []}]
    retrieval_flags = [{"type": "similar_to_flagged_claim", "detail": "x", "related_claim_ids": ["CG-001"]}]
    result = explainability_agent.run(
        extracted={}, consistency={"consistency_flags": []}, pattern_flags=pattern_flags,
        statistical_flags=[], retrieval_flags=retrieval_flags,
    )
    # 25 (pattern) + 20 (retrieval) = 45 -> moderate
    assert result["risk_score"] == 45
    assert result["risk_tier"] == "moderate"
    assert result["risk_tier"] == "moderate"


# ---------------------------------------------------------------------------
# Pipeline error handling — verifies a failure mid-pipeline is caught,
# logged to the audit trace, and leaves the claim in "error" status rather
# than crashing silently or leaving stale/partial data marked as processed.
# ---------------------------------------------------------------------------

def test_pipeline_marks_claim_as_error_on_agent_failure(monkeypatch):
    from app.agents import extraction_agent

    def broken_extraction(*args, **kwargs):
        raise RuntimeError("Simulated Gemini API failure")

    monkeypatch.setattr(extraction_agent, "run", broken_extraction)

    claim = make_claim()
    try:
        pipeline.process_claim(claim)
        assert False, "expected pipeline.process_claim to raise"
    except RuntimeError:
        pass

    saved = storage.get_claim(claim["claim_id"])
    assert saved["status"] == "error"
    error_steps = [t for t in saved["agent_trace"] if t["step"] == "error"]
    assert len(error_steps) == 1
    assert "Simulated Gemini API failure" in error_steps[0]["output"]["message"]


# ---------------------------------------------------------------------------
# Storage layer edge cases — exclude_claim_id correctness, matters because
# every pattern_agent check relies on these not matching a claim against
# itself.
# ---------------------------------------------------------------------------

def test_find_by_claimant_excludes_self():
    claim = make_claim(claimant_id="CL-SELFTEST")
    storage.save_claim(claim)
    results = storage.find_by_claimant("CL-SELFTEST", exclude_claim_id=claim["claim_id"])
    assert claim["claim_id"] not in [c["claim_id"] for c in results]


def test_find_by_address_excludes_self():
    claim = make_claim(address="1 Self Exclude Street")
    storage.save_claim(claim)
    results = storage.find_by_address("1 Self Exclude Street", exclude_claim_id=claim["claim_id"])
    assert claim["claim_id"] not in [c["claim_id"] for c in results]


# ---------------------------------------------------------------------------
# Vehicle number cross-check — declared (by claimant) vs detected (by
# Extraction Agent reading the evidence photo). Deliberately only evaluated
# when a declared_vehicle_number is actually present (see pattern_agent.py's
# comment) — WHETHER one is required at all is enforced separately, at the
# API layer (see tests/test_api.py), not here.
# ---------------------------------------------------------------------------

def test_no_vehicle_check_when_declared_number_absent():
    """Backward-compatibility guarantee: a claim that never touches this
    feature (declared_vehicle_number unset) gets zero new flags — this is
    what keeps every pre-existing test in this file passing unchanged."""
    from app.agents import pattern_agent
    claim = make_claim(claim_type="auto")  # no declared_vehicle_number at all
    claim["extracted"] = {"incident_date": "2026-01-01"}  # no detected_vehicle_number either
    flags = pattern_agent.run(claim)
    types = [f["type"] for f in flags]
    assert "vehicle_number_undetected" not in types
    assert "vehicle_number_mismatch" not in types


def test_no_vehicle_check_for_non_auto_claim_even_with_declared_number():
    from app.agents import pattern_agent
    claim = make_claim(claim_type="home", declared_vehicle_number="DL3CAB1234")
    claim["extracted"] = {"incident_date": "2026-01-01"}
    flags = pattern_agent.run(claim)
    types = [f["type"] for f in flags]
    assert "vehicle_number_undetected" not in types
    assert "vehicle_number_mismatch" not in types


def test_vehicle_number_undetected_flag():
    from app.agents import pattern_agent
    claim = make_claim(claim_type="auto", declared_vehicle_number="DL3CAB1234")
    claim["extracted"] = {"incident_date": "2026-01-01", "detected_vehicle_number": None}
    flags = pattern_agent.run(claim)
    types = [f["type"] for f in flags]
    assert "vehicle_number_undetected" in types


def test_vehicle_number_mismatch_flag():
    from app.agents import pattern_agent
    claim = make_claim(claim_type="auto", declared_vehicle_number="DL3CAB1234")
    claim["extracted"] = {"incident_date": "2026-01-01", "detected_vehicle_number": "MH12XY9999"}
    flags = pattern_agent.run(claim)
    types = [f["type"] for f in flags]
    assert "vehicle_number_mismatch" in types
    mismatch = next(f for f in flags if f["type"] == "vehicle_number_mismatch")
    assert "DL3CAB1234" in mismatch["detail"] and "MH12XY9999" in mismatch["detail"]


def test_vehicle_number_match_produces_no_flag():
    from app.agents import pattern_agent
    claim = make_claim(claim_type="auto", declared_vehicle_number="DL 3C AB 1234")
    # detected number formatted differently (spacing/hyphens) but same underlying value —
    # the comparison normalizes both before comparing, so this should NOT be flagged.
    claim["extracted"] = {"incident_date": "2026-01-01", "detected_vehicle_number": "DL-3CAB-1234"}
    flags = pattern_agent.run(claim)
    types = [f["type"] for f in flags]
    assert "vehicle_number_mismatch" not in types
    assert "vehicle_number_undetected" not in types


# ---------------------------------------------------------------------------
# Server-side risk score verification — the whole point of this fix. A real
# Gemini call is instructed to self-report a score, but that self-report is
# NEVER trusted blindly: explainability_agent.run() must always override it
# with the deterministic Python computation, since risk_tier directly
# drives claim["status"] in pipeline.py, not just displayed text.
# ---------------------------------------------------------------------------

def test_gemini_self_reported_score_is_overridden_by_deterministic_computation(monkeypatch):
    """Simulates what a REAL (non-mock) Gemini call would return — including
    a deliberately WRONG self-reported score — and confirms the agent
    ignores it in favor of the verified Python calculation. This is the
    scenario MOCK_MODE alone can never test, since the mock always agrees
    with itself by construction."""
    from app.agents import explainability_agent

    def fake_gemini_call(model, system_prompt, user_content, mock_response):
        # Simulates a real API response that got the score wrong — e.g.
        # model drift, or simply not following the formula precisely.
        return {
            "risk_score": 12,          # deliberately wrong — should be overridden
            "risk_tier": "low",        # deliberately wrong — should be overridden
            "rationale": "A plausible-sounding but miscalculated rationale from Gemini.",
            "recommended_action": "Approve",  # also wrong for a high-risk case
        }

    monkeypatch.setattr(explainability_agent, "call_gemini_json", fake_gemini_call)

    consistency_flags = [{"issue": "mismatch", "confidence": 0.9, "severity": "high"}]
    pattern_flags = [{"type": "repeat_claimant", "detail": "x", "related_claim_ids": []}]

    result = explainability_agent.run(
        extracted={}, consistency={"consistency_flags": consistency_flags},
        pattern_flags=pattern_flags, statistical_flags=[],
    )

    # 35 (high consistency) + 25 (1 pattern flag) = 60 -> moderate, NOT the
    # fake "12 / low" Gemini claimed to have computed.
    assert result["risk_score"] == 60
    assert result["risk_tier"] == "moderate"
    assert result["recommended_action"] == "Request additional documentation"
    # The rationale IS still taken from Gemini's real output — that's the
    # one field genuine free generation adds value for.
    assert result["rationale"] == "A plausible-sounding but miscalculated rationale from Gemini."


def test_gemini_missing_rationale_falls_back_to_generated_one(monkeypatch):
    from app.agents import explainability_agent

    def fake_gemini_call(model, system_prompt, user_content, mock_response):
        return {"risk_score": 999, "risk_tier": "nonsense", "recommended_action": "???"}  # no rationale key at all

    monkeypatch.setattr(explainability_agent, "call_gemini_json", fake_gemini_call)

    result = explainability_agent.run(
        extracted={}, consistency={"consistency_flags": []}, pattern_flags=[], statistical_flags=[],
    )
    assert result["risk_score"] == 0
    assert result["risk_tier"] == "low"
    assert result["rationale"]  # never blank, even when Gemini's response omitted it entirely


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-v"]))
