"""
Tests the security additions directly. The existing test_api.py suite
passing does NOT prove these work — auth is disabled by default (no
CLAIMGUARD_API_KEY set) and no existing test uploads a file, so none of
this code was previously exercised at all.
"""
import os
import sys
import io

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from fastapi import HTTPException, UploadFile
import pytest


# ---------------------------------------------------------------------------
# API key auth (unit-level, no app re-import needed for the disabled case)
# ---------------------------------------------------------------------------

def test_verify_api_key_is_noop_when_unset():
    os.environ["CLAIMGUARD_API_KEY"] = ""
    for name in ["app.security", "app.config"]:
        sys.modules.pop(name, None)
    app_pkg = sys.modules.get("app")
    if app_pkg:
        for attr in ["security", "config"]:
            if hasattr(app_pkg, attr):
                delattr(app_pkg, attr)

    from app.security import verify_api_key
    verify_api_key(x_api_key="")  # should not raise — auth disabled


def test_verify_api_key_rejects_missing_key_when_configured():
    os.environ["CLAIMGUARD_API_KEY"] = "secret-test-key-123"
    for name in ["app.security", "app.config"]:
        sys.modules.pop(name, None)
    app_pkg = sys.modules.get("app")
    if app_pkg:
        for attr in ["security", "config"]:
            if hasattr(app_pkg, attr):
                delattr(app_pkg, attr)

    from app.security import verify_api_key
    with pytest.raises(HTTPException) as exc_info:
        verify_api_key(x_api_key="")
    assert exc_info.value.status_code == 401

    os.environ["CLAIMGUARD_API_KEY"] = ""  # reset for other tests


def test_verify_api_key_accepts_correct_key():
    os.environ["CLAIMGUARD_API_KEY"] = "secret-test-key-123"
    for name in ["app.security", "app.config"]:
        sys.modules.pop(name, None)
    app_pkg = sys.modules.get("app")
    if app_pkg:
        for attr in ["security", "config"]:
            if hasattr(app_pkg, attr):
                delattr(app_pkg, attr)

    from app.security import verify_api_key
    verify_api_key(x_api_key="secret-test-key-123")  # should not raise

    os.environ["CLAIMGUARD_API_KEY"] = ""  # reset for other tests


# ---------------------------------------------------------------------------
# File upload validation
# ---------------------------------------------------------------------------

def _make_upload_file(filename: str) -> UploadFile:
    return UploadFile(filename=filename, file=io.BytesIO(b""))


def test_validate_upload_rejects_oversized_file():
    os.environ["MAX_UPLOAD_SIZE_BYTES"] = "100"
    for name in ["app.security", "app.config"]:
        sys.modules.pop(name, None)
    app_pkg = sys.modules.get("app")
    if app_pkg:
        for attr in ["security", "config"]:
            if hasattr(app_pkg, attr):
                delattr(app_pkg, attr)

    from app.security import validate_upload
    big_content = b"\x00" * 200  # exceeds the 100-byte limit just set
    f = _make_upload_file("test.jpg")
    with pytest.raises(HTTPException) as exc_info:
        validate_upload(f, big_content)
    assert exc_info.value.status_code == 413

    os.environ.pop("MAX_UPLOAD_SIZE_BYTES", None)


def test_validate_upload_rejects_disallowed_content_type():
    for name in ["app.security", "app.config"]:
        sys.modules.pop(name, None)
    app_pkg = sys.modules.get("app")
    if app_pkg:
        for attr in ["security", "config"]:
            if hasattr(app_pkg, attr):
                delattr(app_pkg, attr)

    from app.security import validate_upload
    # A file renamed to .jpg but whose actual bytes are a script, not an
    # image — this is exactly the "malicious file renamed to .jpg" attack
    # flagged as a real gap in the tech-stack review.
    fake_script_content = b"#!/bin/bash\nrm -rf /\n"
    f = _make_upload_file("evidence.jpg")  # filename LIES about content
    with pytest.raises(HTTPException) as exc_info:
        validate_upload(f, fake_script_content)
    assert exc_info.value.status_code == 415


def test_validate_upload_accepts_real_png():
    for name in ["app.security", "app.config"]:
        sys.modules.pop(name, None)
    app_pkg = sys.modules.get("app")
    if app_pkg:
        for attr in ["security", "config"]:
            if hasattr(app_pkg, attr):
                delattr(app_pkg, attr)

    from app.security import validate_upload
    # Minimal valid PNG file signature (8-byte magic number + minimal IHDR)
    png_header = bytes.fromhex(
        "89504e470d0a1a0a0000000d49484452"
        "0000000100000001080600000037" "6ef9240000000019"
    )
    f = _make_upload_file("evidence.png")
    validate_upload(f, png_header)  # should not raise


# ---------------------------------------------------------------------------
# API-level integration: auth actually enforced through the real endpoint
# ---------------------------------------------------------------------------

def test_api_rejects_request_without_key_when_configured():
    os.environ["CLAIMGUARD_API_KEY"] = "integration-test-key"
    os.environ["CLAIMS_STORE_PATH"] = "/tmp/test_security_claims.json"
    os.environ["USERS_STORE_PATH"] = "/tmp/test_security_users.json"
    for name in ["app.main", "app.security", "app.config", "app.storage", "app.auth"]:
        sys.modules.pop(name, None)
    app_pkg = sys.modules.get("app")
    if app_pkg:
        for attr in ["main", "security", "config", "storage", "auth"]:
            if hasattr(app_pkg, attr):
                delattr(app_pkg, attr)

    from fastapi.testclient import TestClient
    from app.main import app as fresh_app
    client = TestClient(fresh_app)

    # X-API-Key (the shared-secret layer) is missing here — this should be
    # rejected regardless of whether a valid RBAC bearer token is also sent,
    # proving the two auth layers are independent, not an either/or.
    login_resp = client.post("/auth/login", json={"username": "adjuster1", "password": "Adjuster@123"})
    assert login_resp.status_code == 200, login_resp.text
    token = login_resp.json()["access_token"]

    resp = client.post("/claims",
        headers={"Authorization": f"Bearer {token}"},
        data={
            "claim_type": "home", "claimant_id": "CL-SEC-1", "claimant_name": "Sec Test",
            "address": "1 Sec St", "policy_number": "POL-SEC-1",
            "policy_start_date": "2025-01-01", "raw_text": "test",
        })
    assert resp.status_code == 401

    resp2 = client.post("/claims",
        headers={"X-API-Key": "integration-test-key", "Authorization": f"Bearer {token}"},
        data={
            "claim_type": "home", "claimant_id": "CL-SEC-2", "claimant_name": "Sec Test",
            "address": "1 Sec St", "policy_number": "POL-SEC-2",
            "policy_start_date": "2025-01-01", "raw_text": "test",
        })
    assert resp2.status_code == 200

    os.environ["CLAIMGUARD_API_KEY"] = ""  # reset for other test files


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
