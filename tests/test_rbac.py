"""
RBAC tests — role-based access control added as this iteration's feature.
Covers: login success/failure, per-role permission boundaries on
submit/list/get/decision/analytics, and the end_user same-claimant-only
restriction. Runs in the same $0 MOCK_MODE as the rest of the suite.
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
os.environ["CLAIMS_STORE_PATH"] = os.path.join(tempfile.mkdtemp(), "test_rbac_claims.json")
os.environ["USERS_STORE_PATH"] = os.path.join(tempfile.mkdtemp(), "test_rbac_users.json")
os.environ["RATE_LIMIT_SUBMIT"] = "1000/minute"
os.environ["RATE_LIMIT_LOGIN"] = "1000/minute"

from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

DEMO_CREDENTIALS = {
    "end_user": ("end_user1", "EndUser@123", "CL-2001"),
    "adjuster": ("adjuster1", "Adjuster@123", None),
    "investigator": ("investigator1", "Investigator@123", None),
    "analyst": ("analyst1", "Analyst@123", None),
    "admin": ("admin1", "Admin@123", None),
}


def token_for(role: str) -> str:
    username, password, _ = DEMO_CREDENTIALS[role]
    resp = client.post("/auth/login", json={"username": username, "password": password})
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def auth_headers(role: str) -> dict:
    return {"Authorization": f"Bearer {token_for(role)}"}


def submit_claim(headers, claimant_id="CL-RBAC-1", **overrides):
    data = {
        "claim_type": "home", "claimant_id": claimant_id, "claimant_name": "RBAC Test",
        "address": "1 RBAC St", "policy_number": "POL-RBAC-1",
        "policy_start_date": "2025-01-01", "raw_text": "RBAC test narrative.",
        **overrides,
    }
    return client.post("/claims", data=data, headers=headers)


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------

def test_login_succeeds_for_each_seeded_role():
    for role, (username, password, _) in DEMO_CREDENTIALS.items():
        resp = client.post("/auth/login", json={"username": username, "password": password})
        assert resp.status_code == 200, f"{role} login failed: {resp.text}"
        assert resp.json()["role"] == role


def test_login_rejects_wrong_password():
    resp = client.post("/auth/login", json={"username": "adjuster1", "password": "wrong-password"})
    assert resp.status_code == 401


def test_login_rejects_unknown_username():
    resp = client.post("/auth/login", json={"username": "no-such-user", "password": "whatever"})
    assert resp.status_code == 401


def test_whoami_reflects_the_authenticated_role():
    resp = client.get("/auth/me", headers=auth_headers("admin"))
    assert resp.status_code == 200
    assert resp.json()["role"] == "admin"


def test_protected_endpoint_without_any_token_returns_401():
    resp = client.get("/claims")
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Submission permissions
# ---------------------------------------------------------------------------

def test_end_user_can_submit_under_their_own_claimant_id():
    _, _, claimant_id = DEMO_CREDENTIALS["end_user"]
    resp = submit_claim(auth_headers("end_user"), claimant_id=claimant_id)
    assert resp.status_code == 200


def test_end_user_cannot_submit_under_a_different_claimant_id():
    resp = submit_claim(auth_headers("end_user"), claimant_id="CL-SOMEONE-ELSE")
    assert resp.status_code == 403


def test_adjuster_can_submit_on_behalf_of_any_claimant():
    resp = submit_claim(auth_headers("adjuster"), claimant_id="CL-ANY-CLAIMANT")
    assert resp.status_code == 200


def test_investigator_cannot_submit_claims():
    resp = submit_claim(auth_headers("investigator"))
    assert resp.status_code == 403


def test_analyst_cannot_submit_claims():
    resp = submit_claim(auth_headers("analyst"))
    assert resp.status_code == 403


def test_admin_can_submit_claims():
    resp = submit_claim(auth_headers("admin"), claimant_id="CL-ADMIN-SUBMIT")
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# List / get visibility
# ---------------------------------------------------------------------------

def test_end_user_only_sees_their_own_claims_in_list():
    own_claimant_id = DEMO_CREDENTIALS["end_user"][2]
    submit_claim(auth_headers("end_user"), claimant_id=own_claimant_id)
    submit_claim(auth_headers("adjuster"), claimant_id="CL-NOT-THIS-USER")

    resp = client.get("/claims", headers=auth_headers("end_user"))
    assert resp.status_code == 200
    claimant_ids_seen = {c["claimant_id"] for c in resp.json()}
    assert claimant_ids_seen == {own_claimant_id}


def test_adjuster_sees_all_claims_in_list():
    resp = client.get("/claims", headers=auth_headers("adjuster"))
    assert resp.status_code == 200
    claimant_ids_seen = {c["claimant_id"] for c in resp.json()}
    assert len(claimant_ids_seen) > 1  # sees claims across multiple claimants


def test_end_user_cannot_view_another_claimants_claim_by_id():
    other_resp = submit_claim(auth_headers("adjuster"), claimant_id="CL-PRIVATE-OTHER")
    other_claim_id = other_resp.json()["claim_id"]

    resp = client.get(f"/claims/{other_claim_id}", headers=auth_headers("end_user"))
    assert resp.status_code == 403


def test_end_user_can_view_their_own_claim_by_id():
    own_claimant_id = DEMO_CREDENTIALS["end_user"][2]
    own_resp = submit_claim(auth_headers("end_user"), claimant_id=own_claimant_id)
    own_claim_id = own_resp.json()["claim_id"]

    resp = client.get(f"/claims/{own_claim_id}", headers=auth_headers("end_user"))
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Decision permissions
# ---------------------------------------------------------------------------

def test_end_user_cannot_record_a_decision():
    own_claimant_id = DEMO_CREDENTIALS["end_user"][2]
    own_resp = submit_claim(auth_headers("end_user"), claimant_id=own_claimant_id)
    claim_id = own_resp.json()["claim_id"]

    resp = client.patch(f"/claims/{claim_id}/decision",
                         json={"action": "approve", "reason": "trying anyway"},
                         headers=auth_headers("end_user"))
    assert resp.status_code == 403


def test_analyst_cannot_record_a_decision():
    submit_resp = submit_claim(auth_headers("adjuster"), claimant_id="CL-FOR-DECISION")
    claim_id = submit_resp.json()["claim_id"]

    resp = client.patch(f"/claims/{claim_id}/decision",
                         json={"action": "approve", "reason": "trying anyway"},
                         headers=auth_headers("analyst"))
    assert resp.status_code == 403


def test_investigator_can_record_a_decision():
    submit_resp = submit_claim(auth_headers("adjuster"), claimant_id="CL-FOR-INVESTIGATOR")
    claim_id = submit_resp.json()["claim_id"]

    resp = client.patch(f"/claims/{claim_id}/decision",
                         json={"action": "escalate", "reason": "SIU review"},
                         headers=auth_headers("investigator"))
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Analytics permissions
# ---------------------------------------------------------------------------

def test_end_user_cannot_access_analytics():
    resp = client.get("/analytics/summary", headers=auth_headers("end_user"))
    assert resp.status_code == 403


def test_analyst_can_access_analytics():
    resp = client.get("/analytics/summary", headers=auth_headers("analyst"))
    assert resp.status_code == 200
    body = resp.json()
    assert "total_claims" in body and "by_risk_tier" in body


def test_admin_can_access_analytics():
    resp = client.get("/analytics/summary", headers=auth_headers("admin"))
    assert resp.status_code == 200


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-v"]))
