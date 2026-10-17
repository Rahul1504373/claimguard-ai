"""
Tests the FastAPI layer directly (routing, request/response shapes, error
codes) — separate from test_pipeline.py, which tests the agent pipeline in
isolation. Runs in the same $0 MOCK_MODE (no Gemini key needed).
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
os.environ["CLAIMS_STORE_PATH"] = os.path.join(tempfile.mkdtemp(), "test_api_claims.json")
os.environ["USERS_STORE_PATH"] = os.path.join(tempfile.mkdtemp(), "test_api_users.json")
# Rate limiting (10/minute in production) is not otherwise tested here —
# it's covered manually via curl in the UAT workbook, where its in-memory
# state can be observed against real wall-clock time. Raised here so the
# growing number of POST /claims calls in this single test session (all
# sharing one in-memory limiter instance) don't trip it and produce
# unrelated 429s.
os.environ["RATE_LIMIT_SUBMIT"] = "1000/minute"
os.environ["RATE_LIMIT_LOGIN"] = "1000/minute"

from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

# This entire file predates RBAC and exercises the adjuster workflow
# (submit on behalf of any claimant, list/view all claims, record
# decisions) — so it authenticates once as the seeded "adjuster1" demo
# account and reuses that token as a default header for every request
# below. Role-specific behavior (end_user's own-claims restriction,
# investigator/analyst/admin permissions) is covered separately in
# tests/test_rbac.py, not by changing this file's existing assertions.
_login_resp = client.post("/auth/login", json={"username": "adjuster1", "password": "Adjuster@123"})
assert _login_resp.status_code == 200, _login_resp.text
client.headers.update({"Authorization": f"Bearer {_login_resp.json()['access_token']}"})


def test_health_endpoint():
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_submit_claim_returns_full_processed_result():
    resp = client.post(
        "/claims",
        data={
            "claim_type": "home",
            "claimant_id": "CL-API-1",
            "claimant_name": "API Test Claimant",
            "address": "1 API Test Street",
            "policy_number": "POL-API-1",
            "policy_start_date": "2025-01-01",
            "raw_text": "Test claim narrative for API testing.",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] in ("flagged", "cleared")
    assert body["explainability"] is not None
    assert len(body["agent_trace"]) == 6  # extraction, consistency, pattern, statistical, retrieval, explainability


def test_get_claim_by_id_after_submission():
    submit_resp = client.post(
        "/claims",
        data={
            "claim_type": "home",
            "claimant_id": "CL-API-2",
            "claimant_name": "Second Claimant",
            "address": "2 API Test Street",
            "policy_number": "POL-API-2",
            "policy_start_date": "2025-01-01",
            "raw_text": "Another test narrative.",
        },
    )
    claim_id = submit_resp.json()["claim_id"]

    get_resp = client.get(f"/claims/{claim_id}")
    assert get_resp.status_code == 200
    assert get_resp.json()["claim_id"] == claim_id


def test_get_nonexistent_claim_returns_404():
    resp = client.get("/claims/CG-DOES-NOT-EXIST")
    assert resp.status_code == 404


def test_list_claims_returns_array():
    resp = client.get("/claims")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_decision_endpoint_records_adjuster_action():
    submit_resp = client.post(
        "/claims",
        data={
            "claim_type": "home",
            "claimant_id": "CL-API-3",
            "claimant_name": "Third Claimant",
            "address": "3 API Test Street",
            "policy_number": "POL-API-3",
            "policy_start_date": "2025-01-01",
            "raw_text": "Third test narrative.",
        },
    )
    claim_id = submit_resp.json()["claim_id"]

    decision_resp = client.patch(
        f"/claims/{claim_id}/decision",
        json={"action": "approve", "reason": "Manually reviewed, evidence checks out."},
    )
    assert decision_resp.status_code == 200
    body = decision_resp.json()
    assert body["adjuster_decision"]["action"] == "approve"
    assert body["adjuster_decision"]["reason"] == "Manually reviewed, evidence checks out."


def test_decision_on_nonexistent_claim_returns_404():
    resp = client.patch(
        "/claims/CG-DOES-NOT-EXIST/decision",
        json={"action": "approve", "reason": "test"},
    )
    assert resp.status_code == 404


def test_decision_with_invalid_action_returns_422():
    submit_resp = client.post(
        "/claims",
        data={
            "claim_type": "home",
            "claimant_id": "CL-API-4",
            "claimant_name": "Fourth Claimant",
            "address": "4 API Test Street",
            "policy_number": "POL-API-4",
            "policy_start_date": "2025-01-01",
            "raw_text": "Fourth test narrative.",
        },
    )
    claim_id = submit_resp.json()["claim_id"]

    # "maybe" is not a valid action per the DecisionRequest Literal type
    resp = client.patch(
        f"/claims/{claim_id}/decision",
        json={"action": "maybe", "reason": "test"},
    )
    assert resp.status_code == 422


def test_submit_claim_missing_required_field_returns_422():
    resp = client.post(
        "/claims",
        data={
            "claim_type": "home",
            "claimant_id": "CL-API-5",
            # claimant_name deliberately omitted
            "address": "5 API Test Street",
            "policy_number": "POL-API-5",
            "policy_start_date": "2025-01-01",
            "raw_text": "Missing field test.",
        },
    )
    assert resp.status_code == 422


def test_submit_claim_with_idempotency_key_returns_same_claim():
    idem_key = "test-idem-key-001"
    data = {
        "claim_type": "home", "claimant_id": "CL-IDEM-1", "claimant_name": "Idempotency Test",
        "address": "1 Idem St", "policy_number": "POL-IDEM-1",
        "policy_start_date": "2025-01-01", "raw_text": "First submission.",
    }
    resp1 = client.post("/claims", data=data, headers={"Idempotency-Key": idem_key})
    claim_id_1 = resp1.json()["claim_id"]

    # Second submission with the SAME idempotency key, even with different
    # claimant details — should return the ORIGINAL claim, not reprocess.
    resp2 = client.post("/claims", data={**data, "claimant_name": "Changed Name"},
                         headers={"Idempotency-Key": idem_key})
    claim_id_2 = resp2.json()["claim_id"]

    assert claim_id_1 == claim_id_2
    assert resp2.json()["claimant_name"] == "Idempotency Test"  # original data, not the "changed" resubmission


def test_submit_claim_without_idempotency_key_creates_separate_claims():
    data = {
        "claim_type": "home", "claimant_id": "CL-NOIDEM-1", "claimant_name": "No Idem Test",
        "address": "2 NoIdem St", "policy_number": "POL-NOIDEM-1",
        "policy_start_date": "2025-01-01", "raw_text": "Identical narrative text.",
    }
    resp1 = client.post("/claims", data=data)
    resp2 = client.post("/claims", data=data)
    # No idempotency key means these ARE treated as separate submissions —
    # duplicate_submission fraud detection (not idempotency) is what should
    # catch this, not silent deduplication.
    assert resp1.json()["claim_id"] != resp2.json()["claim_id"]
    types_2 = [f["type"] for f in resp2.json()["pattern_flags"]]
    assert "duplicate_submission" in types_2


def test_claims_list_respects_limit_parameter():
    for i in range(5):
        client.post("/claims", data={
            "claim_type": "home", "claimant_id": f"CL-PAGE-{i}", "claimant_name": f"Page Test {i}",
            "address": f"{i} Page St", "policy_number": f"POL-PAGE-{i}",
            "policy_start_date": "2025-01-01", "raw_text": f"Narrative {i}.",
        })
    resp = client.get("/claims", params={"limit": 2})
    assert len(resp.json()) == 2


def test_raw_text_exceeding_max_length_returns_422():
    resp = client.post("/claims", data={
        "claim_type": "home", "claimant_id": "CL-LONG-1", "claimant_name": "Long Text Test",
        "address": "1 Long St", "policy_number": "POL-LONG-1",
        "policy_start_date": "2025-01-01", "raw_text": "x" * 20001,  # 1 over the limit
    })
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Mandatory vehicle photo + declared number — auto claims only. Enforced at
# the API boundary (see app/main.py), which is why these are API-level
# tests rather than pattern_agent-level ones.
# ---------------------------------------------------------------------------

_VALID_PNG_BYTES = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452"
    "0000000100000001080600000037" "6ef9240000000019"
)


def test_auto_claim_without_vehicle_number_returns_422():
    resp = client.post("/claims", data={
        "claim_type": "auto", "claimant_id": "CL-VEH-1", "claimant_name": "Vehicle Test",
        "address": "1 Vehicle St", "policy_number": "POL-VEH-1",
        "policy_start_date": "2025-01-01", "raw_text": "Auto claim, no vehicle number given.",
    }, files={"files": ("evidence.png", _VALID_PNG_BYTES, "image/png")})
    assert resp.status_code == 422
    assert "declared_vehicle_number" in resp.json()["detail"]


def test_auto_claim_without_photo_returns_422():
    resp = client.post("/claims", data={
        "claim_type": "auto", "claimant_id": "CL-VEH-2", "claimant_name": "Vehicle Test",
        "address": "1 Vehicle St", "policy_number": "POL-VEH-2",
        "policy_start_date": "2025-01-01", "raw_text": "Auto claim, no photo attached.",
        "declared_vehicle_number": "DL3CAB1234",
    })  # deliberately no files
    assert resp.status_code == 422
    assert "evidence photo" in resp.json()["detail"]


def test_auto_claim_with_number_and_photo_succeeds():
    resp = client.post("/claims", data={
        "claim_type": "auto", "claimant_id": "CL-VEH-3", "claimant_name": "Vehicle Test",
        "address": "1 Vehicle St", "policy_number": "POL-VEH-3",
        "policy_start_date": "2025-01-01", "raw_text": "Auto claim with both required fields.",
        "declared_vehicle_number": "DL3CAB1234",
    }, files={"files": ("evidence.png", _VALID_PNG_BYTES, "image/png")})
    assert resp.status_code == 200
    assert resp.json()["declared_vehicle_number"] == "DL3CAB1234"


def test_home_claim_does_not_require_vehicle_number_or_photo():
    resp = client.post("/claims", data={
        "claim_type": "home", "claimant_id": "CL-HOME-1", "claimant_name": "Home Test",
        "address": "1 Home St", "policy_number": "POL-HOME-1",
        "policy_start_date": "2025-01-01", "raw_text": "Home water damage claim, no vehicle involved.",
    })  # no declared_vehicle_number, no files — correctly not required
    assert resp.status_code == 200


def test_invalid_claim_type_returns_422():
    resp = client.post("/claims", data={
        "claim_type": "spaceship", "claimant_id": "CL-BAD-1", "claimant_name": "Bad Type Test",
        "address": "1 Bad St", "policy_number": "POL-BAD-1",
        "policy_start_date": "2025-01-01", "raw_text": "Testing an invalid claim_type value.",
    })
    assert resp.status_code == 422


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-v"]))
