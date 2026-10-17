"""
Tests the Firestore branch of storage.py using a mocked firestore.Client.
This verifies our code calls Firestore correctly (right collection, right
query filters, right self-exclusion logic) without needing a live emulator
connection — useful for CI environments with restricted network access.

This does NOT replace testing against a real Firestore Emulator before
deployment — mocking proves our code calls the SDK correctly, not that the
SDK/emulator combination behaves as we assume. Run this before deploying:
    firebase emulators:start --only firestore
    export FIRESTORE_EMULATOR_HOST=localhost:8080
    export USE_FIRESTORE=true
    pytest tests/test_pipeline.py -v   # against the live emulator
"""
import os
import sys
from unittest.mock import MagicMock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


def _fresh_storage_with_mocked_firestore():
    """Re-imports app.storage with USE_FIRESTORE=true and a mocked
    google.cloud.firestore module, isolated per-test so mock state doesn't
    leak between tests.

    Popping sys.modules alone is NOT enough to force a real re-import:
    `from app import storage` checks for a `storage` attribute already
    cached on the `app` package object first, and finds it even after
    sys.modules['app.storage'] is removed, silently returning the stale
    module. We must also delete those cached attributes on the parent
    package object itself.
    """
    os.environ["USE_FIRESTORE"] = "true"

    mock_module = MagicMock()
    mock_client = MagicMock()
    mock_collection = MagicMock()
    mock_module.Client.return_value = mock_client
    mock_client.collection.return_value = mock_collection
    sys.modules["google.cloud.firestore"] = mock_module

    for name in ["app.storage", "app.config"]:
        sys.modules.pop(name, None)
    app_pkg = sys.modules.get("app")
    if app_pkg is not None:
        for attr in ["storage", "config"]:
            if hasattr(app_pkg, attr):
                delattr(app_pkg, attr)

    from app import storage
    return storage, mock_collection


def teardown_function():
    """Reset back to JSON-backend mode so other test files aren't affected."""
    os.environ["USE_FIRESTORE"] = "false"
    for name in ["app.storage", "app.config"]:
        sys.modules.pop(name, None)
    app_pkg = sys.modules.get("app")
    if app_pkg is not None:
        for attr in ["storage", "config"]:
            if hasattr(app_pkg, attr):
                delattr(app_pkg, attr)
    sys.modules.pop("google.cloud.firestore", None)


def test_save_claim_calls_correct_firestore_methods():
    storage, mock_collection = _fresh_storage_with_mocked_firestore()
    mock_doc_ref = MagicMock()
    mock_collection.document.return_value = mock_doc_ref

    claim = {"claim_id": "CG-TEST-1", "claimant_id": "CL-1"}
    storage.save_claim(claim)

    mock_collection.document.assert_called_with("CG-TEST-1")
    mock_doc_ref.set.assert_called_with(claim)


def test_get_claim_returns_dict_when_doc_exists():
    storage, mock_collection = _fresh_storage_with_mocked_firestore()
    claim = {"claim_id": "CG-TEST-1"}
    mock_doc = MagicMock(exists=True)
    mock_doc.to_dict.return_value = claim
    mock_collection.document.return_value.get.return_value = mock_doc

    assert storage.get_claim("CG-TEST-1") == claim


def test_get_claim_returns_none_when_doc_missing():
    storage, mock_collection = _fresh_storage_with_mocked_firestore()
    mock_doc = MagicMock(exists=False)
    mock_collection.document.return_value.get.return_value = mock_doc

    assert storage.get_claim("CG-MISSING") is None


def test_find_by_claimant_filters_and_excludes_self():
    storage, mock_collection = _fresh_storage_with_mocked_firestore()
    doc_a = MagicMock(id="CG-A")
    doc_a.to_dict.return_value = {"claim_id": "CG-A", "claimant_id": "CL-9"}
    doc_b = MagicMock(id="CG-B")
    doc_b.to_dict.return_value = {"claim_id": "CG-B", "claimant_id": "CL-9"}
    mock_collection.where.return_value.stream.return_value = [doc_a, doc_b]

    results = storage.find_by_claimant("CL-9", exclude_claim_id="CG-A")

    mock_collection.where.assert_called_with("claimant_id", "==", "CL-9")
    assert [r["claim_id"] for r in results] == ["CG-B"]


def test_find_by_address_filters_and_excludes_self():
    storage, mock_collection = _fresh_storage_with_mocked_firestore()
    doc_a = MagicMock(id="CG-A")
    doc_a.to_dict.return_value = {"claim_id": "CG-A", "address": "1 Ring Rd"}
    doc_b = MagicMock(id="CG-B")
    doc_b.to_dict.return_value = {"claim_id": "CG-B", "address": "1 Ring Rd"}
    mock_collection.where.return_value.stream.return_value = [doc_a, doc_b]

    results = storage.find_by_address("1 Ring Rd", exclude_claim_id="CG-B")

    mock_collection.where.assert_called_with("address", "==", "1 Ring Rd")
    assert [r["claim_id"] for r in results] == ["CG-A"]


def test_list_claims_maps_all_documents():
    storage, mock_collection = _fresh_storage_with_mocked_firestore()
    doc_a = MagicMock()
    doc_a.to_dict.return_value = {"claim_id": "CG-A"}
    doc_b = MagicMock()
    doc_b.to_dict.return_value = {"claim_id": "CG-B"}
    mock_collection.stream.return_value = [doc_a, doc_b]

    results = storage.list_claims()
    assert {r["claim_id"] for r in results} == {"CG-A", "CG-B"}


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-v"]))
