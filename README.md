# ClaimGuard AI

Explainable fraud-risk triage for insurance claims. A four-agent pipeline
(Extraction → Consistency → Pattern → Explainability) built on Gemini,
deployed on Google Cloud Run.

## Why this exists

Most claims fraud-scoring tools output a black-box number. ClaimGuard
produces a risk score **with a defensible, evidence-cited rationale** an
adjuster can act on and a compliance reviewer can trust.

## Architecture

```
Claim submitted (text + photos/PDFs)
        │
        ▼
1. Extraction Agent (Gemini, multimodal)
   → structured fields: incident_type, damage_description, claimed_amount...
        │
        ▼
2. Consistency Agent (Gemini, multimodal)
   → flags mismatches between narrative and visual evidence
        │
        ▼
3. Pattern Agent (deterministic, NOT an LLM call — by design)
   → repeat claimant / shared address / frequency spike / date anomaly / duplicate
        │
        ▼
4. Statistical Agent (deterministic classical ML, NOT an LLM call — by design)
   → Benford's Law digit analysis + Isolation Forest anomaly scoring,
     each gated by an honest minimum-sample-size guard
        │
        ▼
5. Explainability Agent (Gemini)
   → risk_score (reproducible formula, now incorporating statistical flags)
     + plain-language rationale + recommended action
        │
        ▼
Adjuster reviews in dashboard → approve / override / escalate (audit-logged)
```

**Why a Statistical Agent alongside the Pattern Agent, and why both stay non-Gemini:** the hackathon's judging rubric weights "meaningful use of Gen AI" heavily — so Gemini is deliberately kept as the system's reasoning centerpiece (multimodal evidence comparison, natural-language rationale), while classical statistical/ML methods handle what they're genuinely better at (digit-distribution analysis, multivariate outlier detection). This mirrors how real production fraud systems are built — hybrid, not single-technique — and each classical method includes an honest "insufficient data" guard rather than producing a confident-sounding result on too small a sample.

## Project layout

```
app/
  main.py              FastAPI app — /claims endpoints
  pipeline.py          orchestrates the 4 agents
  models.py            Pydantic schema
  storage.py           JSON-file store (swap for Firestore at deploy — see below)
  gemini_client.py      Gemini wrapper with MOCK_MODE for $0 local testing
  agents/
    extraction_agent.py
    consistency_agent.py
    pattern_agent.py    deterministic logic, no API calls
    explainability_agent.py
streamlit_app.py         adjuster dashboard UI
tests/test_pipeline.py   pytest suite — runs fully in MOCK_MODE, no API key needed
```

## Running locally (free, no API key required)

The pipeline runs in **MOCK_MODE** automatically whenever `GEMINI_API_KEY`
is unset — every agent returns a realistic canned response, so you can
verify the whole system before spending any real API quota.

```bash
pip install -r requirements.txt --break-system-packages   # or use a venv
pytest tests/ -v                                          # 96 tests pass, 1 skipped (test_mcp_server.py — needs venv-mcp, see MCP section)

# Terminal 1 — API
uvicorn app.main:app --reload --port 8000

# Terminal 2 — dashboard
streamlit run streamlit_app.py
```

## Running with real Gemini calls

1. Get a key from **Google AI Studio** (not Vertex AI): https://aistudio.google.com/apikey
2. `cp .env.example .env` and paste your key in
3. **Do not enable billing** on that AI Studio project if you want the
   $0 safety net — exceeding the free tier then just returns `429` errors
   instead of charging you.
4. Re-run `uvicorn app.main:app --reload` — MOCK_MODE turns off automatically
   once `GEMINI_API_KEY` is set.

## Deploying to Cloud Run

```bash
gcloud run deploy claimguard-api \
  --source . \
  --region asia-south1 \
  --allow-unauthenticated \
  --min-instances 0 \
  --set-env-vars GEMINI_API_KEY=your_key_here,USE_FIRESTORE=true
```

`--min-instances 0` (scale-to-zero) means you pay nothing when idle — see
the cost notes below. **Set a Cloud Billing budget alert at $1–2** the
moment you enable Blaze billing (required for Cloud Run's outbound calls
to the Gemini API even within the free tier) — belt-and-suspenders against
any surprise charge.

## ⚠️ Storage: two backends, and an honest note on what's actually been tested

`storage.py` supports two backends via `USE_FIRESTORE`:

- **JSON-file backend (default, `USE_FIRESTORE=false`)** — zero setup, what
  all the pipeline/API tests run against. Confirmed working end-to-end,
  live, multiple times during development.
- **Firestore backend (`USE_FIRESTORE=true`)** — the production-resembling
  path, talking to real Firestore or the free Firestore Emulator via the
  `google-cloud-firestore` SDK.

**What's been verified for the Firestore path, and what hasn't:** the
Firestore branch's logic (correct collection name, correct query filters,
correct self-exclusion, correct handling of a missing document) is covered
by `tests/test_storage_firestore.py` using a *mocked* Firestore client —
this caught a real bug during development (a stale module-caching issue in
the test harness itself) and confirms the code calls the SDK correctly.
It has **not** been run against a live Firestore Emulator or real Firestore,
because the emulator's download is blocked by network restrictions in the
environment this was built in. Before you deploy, run this once yourself:

```bash
npm install -g firebase-tools          # free, official Google CLI
firebase emulators:start --only firestore
# in another terminal:
export FIRESTORE_EMULATOR_HOST=localhost:8080
export USE_FIRESTORE=true
pytest tests/test_pipeline.py -v        # now exercises real Firestore emulator I/O
```

This costs $0 either way — the emulator never touches real GCP billing, and
deployed Firestore usage stays within the free Spark-tier quota for a
hackathon judge's testing volume (1 GiB storage, 50K reads/day, 20K writes/day).

## Security (free additions — see the tech-stack review for full context)

Four real gaps identified during architecture review are now fixed, live-tested, and covered by dedicated tests (`tests/test_security.py`):

| Fix | What it does | Free? |
|---|---|---|
| **API key auth** | `X-API-Key` header required on all `/claims` endpoints once `CLAIMGUARD_API_KEY` is set. Disabled (no-op) by default for local dev/pytest. | Yes |
| **Restricted CORS** | `allow_origins` now reads from `ALLOWED_ORIGINS` (explicit list) instead of `"*"` | Yes |
| **Rate limiting** | `slowapi`, in-memory, no Redis needed at this scale — default `10/minute` on claim submission | Yes |
| **File upload validation** | Real content-type sniffing via `python-magic` (not just trusting the filename extension) + a size limit. Live-verified: a bash script renamed to `.jpg` is correctly rejected (415) | Yes — requires `libmagic1` at the OS level, added to the Dockerfile |

**Still open, and genuinely not fixable for free** (carried forward honestly from the tech-stack review, unchanged): prompt injection defense is only partially mitigated (system-prompt separation, not a dedicated filter), PII/PHI redaction before Gemini calls isn't implemented, and Firestore's default security rules remain open. These require either paid infrastructure or a level of engineering effort beyond "free prototype" scope — flagged here rather than silently left unaddressed.

To enable auth locally: set `CLAIMGUARD_API_KEY` in `.env` for the API, and the same value in the Streamlit dashboard's environment (`export CLAIMGUARD_API_KEY=...` before running `streamlit run`) — see `.env.example` for the exact variable names.

## RBAC — role-based access control (free, demo-grade — see `app/auth.py`)

Five roles, matching the real BFSI claims workflow, enforced **server-side**
(`app/main.py`/`app/auth.py`) — the Streamlit UI's role-conditional tabs are
a presentation layer on top of that, not the actual security boundary:

| Role | Can submit claims | Can view | Can record a decision | Can see analytics |
|---|---|---|---|---|
| **End User** (claimant) | Only under their own `claimant_id` | Only their own claims | No | No |
| **Claims Adjuster** | On behalf of any claimant | All claims | Yes | Yes |
| **SIU / Fraud Investigator** | No | All claims (UI defaults to flagged-only) | Yes | Yes |
| **Business / Data Analyst** | No | — (analytics only, no case list) | No | Yes |
| **Admin** | On behalf of any claimant | All claims | Yes | Yes + System/eval status tab |

**Demo credentials** (five fixed, seeded accounts — auto-created in `data/users.json` on first run; this is a prototype login, not a real user-registration system):

| Role | Username | Password |
|---|---|---|
| End User | `end_user1` | `EndUser@123` |
| Claims Adjuster | `adjuster1` | `Adjuster@123` |
| SIU Investigator | `investigator1` | `Investigator@123` |
| Business Analyst | `analyst1` | `Analyst@123` |
| Admin | `admin1` | `Admin@123` |

Auth is a real JWT (PyJWT, HS256) + bcrypt password hashing — both free,
local, no paid identity service — layered on top of (not replacing) the
existing `X-API-Key` shared secret. See `app/auth.py`'s module docstring
for the explicit, honest scope: no signup flow, no key rotation, no
revocation list. That's a deliberate "demonstrate the RBAC pattern"
scope, not a claim of production-grade identity management.

Set a real `JWT_SECRET` via env var before any deployment beyond your own
machine — the default in `.env.example` is for local dev only.

## RAG — Retrieval Agent (free, local, no embedding API — see `app/agents/retrieval_agent.py`)

A 6th pipeline stage: finds the top-3 most textually similar past claims to
the one being processed, via **TF-IDF + cosine similarity** (`scikit-learn`
— already a dependency, zero extra cost, zero network calls). This is
genuine retrieval-augmented generation — not a dense/embedding-based
approach, deliberately: that keeps this component free of another
rate-limited Gemini API dependency, after this project already hit real
Gemini model-availability issues more than once (see the tracker).

Two real uses of what's retrieved:
1. Passed to the Explainability Agent as grounding context, so its
   generated rationale can cite a specific past claim_id — instructed not
   to invent similarities beyond what's actually retrieved.
2. A new deterministic fraud signal, `similar_to_flagged_claim`, fires when
   a claim is ≥55% similar to a PAST claim that was already flagged —
   catching a reworded resubmission that the exact-text `duplicate_submission`
   check would miss. Weighted +20 in the risk-score formula.

See `docs/eval_results.md` for an honest discussion of what this did and
didn't change in the existing 42-claim eval dataset, and what a live test
proved instead.

## MCP Server — optional integration (free, read-only — see `mcp_server.py`)

Exposes ClaimGuard AI's claim data and fraud signals as MCP (Model Context
Protocol) tools, so any MCP-compatible client — Claude Desktop, or another
MCP client — can query it in natural language: "show me flagged claims",
"what's the portfolio risk breakdown", "find claims similar to this
narrative." Shares the exact same storage backend and Retrieval Agent as
the FastAPI app — not a separate copy of the logic.

**Honestly stated:** MCP is Anthropic's open protocol, not a Google
technology — this is an architecture/integration choice on top of the
hackathon's core Gen AI work, not a Gemini feature. It's also **read-only**
for this iteration (no submit/decide tools) — a deliberate scope choice,
not an oversight.

**Runs in its own virtual environment**, separate from the main app: the
`mcp` SDK pulls a newer `starlette`/`pydantic` than this project's pinned
FastAPI versions, and installing both together genuinely breaks the FastAPI
app (confirmed directly during development — see `docs/tracker.md`). So:

```bash
python3 -m venv venv-mcp
source venv-mcp/bin/activate
pip install -r requirements-mcp.txt
python3 mcp_server.py
```

It imports `app/storage.py` and `app/agents/retrieval_agent.py` directly at
runtime — no code duplication, only environment separation.

**Four tools exposed:** `get_claim`, `list_flagged_claims`,
`get_portfolio_analytics`, `search_similar_claims` — all read-only, all
computed live from whatever claims have actually been processed.

**To connect it to Claude Desktop**, add this to `claude_desktop_config.json`
(adjust the paths to where you cloned this project):

```json
{
  "mcpServers": {
    "claimguard-ai": {
      "command": "/absolute/path/to/claimguard_ai/venv-mcp/bin/python3",
      "args": ["/absolute/path/to/claimguard_ai/mcp_server.py"],
      "cwd": "/absolute/path/to/claimguard_ai"
    }
  }
}
```

**Verified, not just written:** `tests/test_mcp_server.py` spawns the
server as a real subprocess and talks to it over the actual stdio
transport — the same mechanism Claude Desktop uses — seeds it with 2 real
claims run through the genuine pipeline (one a reworded near-duplicate of
the other), and confirms all 4 tools return correct live data, including
the Retrieval Agent catching the near-duplicate. This test requires the
`mcp` package, so it runs from `venv-mcp`, not the main venv:

```bash
source venv-mcp/bin/activate
pytest tests/test_mcp_server.py -v
```

Running the main `pytest tests/` suite from the main venv correctly
*skips* this one file (missing `mcp` module) rather than failing — that's
expected, documented behavior, not a bug.

## Seeding demo data


Load `claimguard_synthetic_claims.json` (42 claims covering clean cases,
consistency mismatches, and every pattern-flag type) via a short seed
script, or submit a few through the dashboard live for the video — seeing
the pipeline actually run beats a pre-loaded dataset for judges.
