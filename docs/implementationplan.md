# Implementation Plan — ClaimGuard AI

## Build Phases (as actually executed)

**Phase 1 — Core pipeline skeleton:** `config.py`, `models.py`, `storage.py` (JSON-file backend), `gemini_client.py` with MOCK_MODE, the three Gemini agents (Extraction, Consistency, Explainability) with mock responses, `pipeline.py`, `main.py`, basic pytest coverage.

**Phase 2 — Pattern detection:** `pattern_agent.py` (deterministic — repeat claimant, shared address, duplicate, policy-date anomaly, frequency spike), wired into the pipeline between Consistency and Explainability, with dedicated tests for each flag type (positive and negative cases).

**Phase 3 — Firestore production-path:** extended `storage.py` with a real Firestore backend behind the same interface, gated by `USE_FIRESTORE`, verified via mocked-client tests (a real module-caching bug was found and fixed during this phase — see `tracker.md`).

**Phase 4 — Statistical Agent:** added Benford's Law and Isolation Forest as a fifth pipeline stage, deliberately kept non-Gemini (see `techspec.md` for the rationale), with explicit minimum-sample-size guards and dedicated tests proving the guards work at both sides of the threshold.

**Phase 5 — Security hardening:** API key auth, restricted CORS, rate limiting (slowapi), real file-content validation (python-magic) — each verified both by unit test and by a live end-to-end run against the actual running server (not just test-suite passing).

**Phase 6 — Demo assets:** placeholder evidence images, baseline-seeding script, ordered demo scenario file with documented expected outcomes, and a rehearsal script — the rehearsal run itself caught a real limitation (mock mode can't validate Gemini-dependent scenarios) before it could surface during actual recording.

## Current Test Coverage

96 tests across 8 files, all passing in MOCK_MODE (no cost, no external dependency):
- `test_pipeline.py` — pipeline orchestration, all 5 pattern-flag types + vehicle-number checks, scoring tier boundaries, error handling, and server-side verification that a Gemini-reported risk score is never trusted without recomputation
- `test_api.py` — FastAPI endpoint layer, routing, 404/422 handling, mandatory vehicle-photo enforcement for auto claims
- `test_statistical_agent.py` — Benford's Law and Isolation Forest, both guard behavior and detection behavior
- `test_storage_firestore.py` — Firestore backend logic via mocked client
- `test_security.py` — API key auth, file validation, live integration test

**Not yet verified** (documented honestly, not silently skipped): real Firestore Emulator I/O (blocked by sandbox network restrictions during development — see `tracker.md` for the exact verification steps to run before deployment).

## Deployment Procedure

```bash
# 1. Local verification first
pip install -r requirements.txt --break-system-packages
pytest tests/ -v   # expect 96 passed, 1 skipped (test_mcp_server.py needs the separate venv-mcp — see README's MCP section)

# 2. Firestore emulator verification (once, before first real deployment)
npm install -g firebase-tools
firebase emulators:start --only firestore
# separate terminal:
export FIRESTORE_EMULATOR_HOST=localhost:8080
export USE_FIRESTORE=true
pytest tests/test_pipeline.py -v

# 3. Deploy
gcloud run deploy claimguard-api \
  --source . \
  --region asia-south1 \
  --allow-unauthenticated \
  --min-instances 0 \
  --set-env-vars GEMINI_API_KEY=<key>,USE_FIRESTORE=true,CLAIMGUARD_API_KEY=<key>

# 4. Set a Cloud Billing budget alert at $1-2 immediately after enabling
#    Blaze billing (required for Cloud Run even within free-tier usage)
```

## Rollback / Recovery Notes

Since storage is either a local JSON file or Firestore, there is no complex migration state to roll back — redeploying an earlier container image is sufficient. Firestore data itself is not versioned or backed up in the prototype (documented gap — see `tracker.md`).
