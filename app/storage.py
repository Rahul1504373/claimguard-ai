"""
Storage abstraction with two backends, selected by settings.USE_FIRESTORE:

1. JSON-file backend (USE_FIRESTORE=false, the default) — zero setup, used
   by pytest so the test suite never needs any external service running.
   This is what the earlier prototype used exclusively.

2. Firestore backend (USE_FIRESTORE=true) — the production-resembling path.
   This talks to real Firestore via the google-cloud-firestore SDK. It costs
   $0 in two distinct ways depending on where you point it:
     - Locally: run the Firestore Emulator (part of the free Firebase CLI —
       `firebase emulators:start --only firestore`) and set
       FIRESTORE_EMULATOR_HOST=localhost:8080. The SDK below automatically
       talks to the emulator instead of real GCP the moment that env var is
       set — no code change needed, no GCP billing touched at all.
     - Deployed (Cloud Run): talks to real Firestore, staying within the
       free Spark-tier quota (1 GiB storage, 50K reads/day, 20K writes/day)
       for a hackathon judge's testing volume.

Either way, main.py and pipeline.py never change — they only call
save_claim / get_claim / list_claims / find_by_claimant / find_by_address.
"""
import json
import os
import threading
from app.config import settings

_lock = threading.Lock()

if settings.USE_FIRESTORE:
    from google.cloud import firestore
    _db = firestore.Client()
    _collection = _db.collection("claims")


def _ensure_store():
    os.makedirs(os.path.dirname(settings.CLAIMS_STORE_PATH) or ".", exist_ok=True)
    if not os.path.exists(settings.CLAIMS_STORE_PATH):
        with open(settings.CLAIMS_STORE_PATH, "w") as f:
            json.dump({}, f)


def _read_all() -> dict:
    _ensure_store()
    with open(settings.CLAIMS_STORE_PATH, "r") as f:
        return json.load(f)


def _write_all(data: dict):
    with open(settings.CLAIMS_STORE_PATH, "w") as f:
        json.dump(data, f, indent=2, default=str)


def save_claim(claim: dict):
    if settings.USE_FIRESTORE:
        _collection.document(claim["claim_id"]).set(claim)
        return
    with _lock:
        data = _read_all()
        data[claim["claim_id"]] = claim
        _write_all(data)


def get_claim(claim_id: str) -> dict | None:
    if settings.USE_FIRESTORE:
        doc = _collection.document(claim_id).get()
        return doc.to_dict() if doc.exists else None
    data = _read_all()
    return data.get(claim_id)


def list_claims() -> list[dict]:
    if settings.USE_FIRESTORE:
        return [doc.to_dict() for doc in _collection.stream()]
    data = _read_all()
    return list(data.values())


def find_by_claimant(claimant_id: str, exclude_claim_id: str | None = None) -> list[dict]:
    if settings.USE_FIRESTORE:
        docs = _collection.where("claimant_id", "==", claimant_id).stream()
        return [d.to_dict() for d in docs if d.id != exclude_claim_id]
    return [
        c for c in list_claims()
        if c.get("claimant_id") == claimant_id and c.get("claim_id") != exclude_claim_id
    ]


def find_by_address(address: str, exclude_claim_id: str | None = None) -> list[dict]:
    if settings.USE_FIRESTORE:
        docs = _collection.where("address", "==", address).stream()
        return [d.to_dict() for d in docs if d.id != exclude_claim_id]
    return [
        c for c in list_claims()
        if c.get("address") == address and c.get("claim_id") != exclude_claim_id
    ]


def find_by_idempotency_key(idempotency_key: str) -> dict | None:
    """Returns the existing claim with this client-supplied idempotency key,
    if any — used for retry-safety (see app/main.py), NOT for fraud-pattern
    duplicate detection, which is a deliberately separate, content-based
    check in pattern_agent.py."""
    if settings.USE_FIRESTORE:
        docs = list(_collection.where("idempotency_key", "==", idempotency_key).limit(1).stream())
        return docs[0].to_dict() if docs else None
    matches = [c for c in list_claims() if c.get("idempotency_key") == idempotency_key]
    return matches[0] if matches else None
