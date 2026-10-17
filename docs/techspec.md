# Technical Specification — ClaimGuard AI

## Architecture Overview

```
Claim submitted (text + photos/PDFs)
        │
        ▼
1. Extraction Agent (Gemini, multimodal)
        │
        ▼
2. Consistency Agent (Gemini, multimodal)
        │
        ▼
3. Pattern Agent (deterministic — NOT Gemini, by design)
        │
        ▼
4. Statistical Agent (deterministic classical ML — NOT Gemini, by design)
        │
        ▼
5. Retrieval Agent — RAG (TF-IDF cosine similarity — NOT Gemini, by design)
        │
        ▼
6. Explainability Agent (Gemini, grounded with Retrieval Agent's output)
        │
        ▼
Adjuster reviews → approve / override / escalate (audit-logged)
```

**Why two agents are deliberately not Gemini calls:** the hackathon rubric weights "meaningful use of Gen AI" — which means using Gemini where it genuinely adds value (reasoning over unstructured evidence, natural-language synthesis) and NOT using it where a classical method is more reliable, auditable, and reproducible (digit-distribution analysis, multivariate outlier detection, exact-match duplicate detection). This is a documented architecture decision, not a limitation — see `prd.md` Goal #2.

## Tech Stack

| Layer | Choice | Why |
|---|---|---|
| Backend | FastAPI (Python) | Free, async-native, matches the Python-first Gemini SDK |
| Frontend | Streamlit | Free, zero-cost Cloud Run hosting, fast to build without a JS toolchain |
| Database | Firestore (Spark free tier), with a JSON-file backend for tests | Genuine NoSQL document store at $0; JSON backend needs zero setup for pytest |
| AI models | Gemini (flash-lite / flash / pro tiers per agent) via `google-genai` | Free via AI Studio (no billing enabled = $0 even past quota, just 429s) |
| Deployment | Cloud Run (scale-to-zero) | Free tier covers prototype-scale traffic; Docker-based, matches hackathon requirement |
| Classical ML | scikit-learn (Isolation Forest), NumPy (Benford's Law) | Free, lightweight, no training infrastructure needed |
| Security | slowapi (rate limiting), python-magic (file validation) | Both free, no paid WAF/gateway needed at this scale |

Full free-vs-production tech stack comparison (73 rows, covering frontend through SIEM): see the separately delivered `claimguard_tech_stack_comparison.xlsx`.

## Agent Specifications

### Extraction Agent
Model: `gemini-3.5-flash-lite`. Input: raw claim text + evidence files. Output schema: `{incident_type, damage_description, claimed_amount, incident_date, policy_number, visible_evidence_summary}`. Instructed to return `null` for anything not stated/visible — no inference beyond given evidence.

### Consistency Agent
Model: `gemini-3.5-flash`. Compares extracted narrative against visual evidence. Output: `{consistency_flags: [{issue, confidence, severity}], overall_match_assessment}`. Instructed to report only factual mismatches, not speculate on fraud intent.

### Pattern Agent (deterministic)
Constants: `REPEAT_CLAIMANT_THRESHOLD=2`, `FREQUENCY_WINDOW_DAYS=45`, `FREQUENCY_THRESHOLD=2`.
Detects: repeat_claimant, shared_address_ring, duplicate_submission, policy_date_anomaly, claim_frequency_spike.

### Statistical Agent (deterministic classical ML)
Constants: `BENFORD_MIN_SAMPLES=30`, `ISOLATION_FOREST_MIN_SAMPLES=10`.
- **Benford's Law**: leading-digit distribution vs. expected `log10(1+1/d)`, scored via Mean Absolute Deviation, Nigrini's conformity bands (>0.015 = nonconformity/flagged).
- **Isolation Forest**: `sklearn.ensemble.IsolationForest(contamination="auto", random_state=42)` on claimed_amount.
- Both include an explicit "insufficient sample size" guard rather than a misleadingly confident result on too little data.

### Retrieval Agent (RAG — deterministic, not Gemini)
ClaimGuard AI's retrieval-augmented-generation layer: finds the top-K most
textually similar past claims via **TF-IDF vectorization + cosine
similarity** (`scikit-learn` — already a project dependency, zero
additional cost, zero network calls), comparing the current claim's
`raw_text` narrative against claim history. Deliberately NOT a dense
embedding / vector-database approach (no Gemini embedding API call, no
vector index) — see `app/agents/retrieval_agent.py`'s module docstring for
the full honest reasoning: this keeps the component free of another
rate-limited API dependency, and TF-IDF is a legitimate, standard retrieval
technique in its own right at this claim volume. A genuine future upgrade
would be swapping in dense embeddings for semantic (not just lexical)
similarity — noted as a next step, not claimed as already built.

Two outputs, both genuine RAG usage:
1. `similar_claims` — top-3 most similar past claims, passed to the
   Explainability Agent as grounding context so its generated rationale can
   cite a specific prior claim_id, instructed not to invent similarities
   beyond what's actually retrieved.
2. `retrieval_flags` — a NEW deterministic fraud signal: `similar_to_flagged_claim`,
   raised when similarity ≥ `SIMILARITY_FLAG_THRESHOLD` (0.55) AND that past
   claim's status was `"flagged"`. This catches a reworded resubmission
   (different wording, same underlying story) that the Pattern Agent's
   exact-text `duplicate_submission` check would miss — a genuinely
   different detection mechanism, not a duplicate of an existing one.
   Minimum-history guard: needs only 1 prior claim (not a statistical
   sample-size requirement like Benford's Law — pairwise similarity is
   valid even against a single comparison point).

### Explainability Agent
Model: `gemini-3.5-flash` (downgraded from `gemini-3.5-pro`, which returned a 404 for this project's API key — see `docs/tracker.md` for the exact error and reasoning). Scoring formula (fixed, given to the model explicitly — not left to free generation):
- High severity consistency flag: +35 each
- Medium severity: +15 each
- Low severity: +5 each
- Pattern flag (any type): +25 each
- Statistical flag (any type): +15 each
- Retrieval flag (similar_to_flagged_claim): +20 each — weighted between pattern's exact-match +25 and statistical's anomaly +15, since narrative similarity is a real but softer signal than an exact rule match
- Cap at 100. Tier: low (<30) / moderate (30–64) / high (≥65).

**Server-side verification, not blind trust:** Gemini is instructed to compute and self-report this score, but that self-report is never used directly — `compute_deterministic_score()` recomputes it in Python from the same formula and that value is always authoritative, in both mock and real modes. A mismatch is logged as a warning, not silently accepted. This matters because `risk_tier` directly sets `claim["status"]` to flagged/cleared in `app/pipeline.py` — not just displayed text — so an unverified self-reported score could silently misclassify a claim. Only the rationale narrative is taken from Gemini's actual output.

## API Contract

| Method | Path | Auth | Notes |
|---|---|---|---|
| GET | `/health` | None (must stay public for health checks) | |
| POST | `/claims` | API key + rate-limited | Multipart form; validates uploads (size + real content-type sniffing) before saving |
| GET | `/claims` | API key | Lists all claims |
| GET | `/claims/{id}` | API key | 404 if not found |
| PATCH | `/claims/{id}/decision` | API key | Records adjuster action + reason |

## Security Design

See `rules.md` for the full free-tier security constraint set. Summary of what's implemented vs. open: API key auth, restricted CORS, rate limiting (10/min default), and real file-content validation (via `python-magic`, not filename trust) are implemented and tested. Prompt injection defense (partial — system-prompt separation only), PII/PHI redaction, and Firestore security rules hardening remain open — documented honestly rather than silently deferred (full 73-row gap analysis in the tech-stack comparison spreadsheet).

## Deployment

Dockerfile builds a `python:3.12-slim` image with `libmagic1` installed (required by `python-magic` at runtime — the slim base image lacks it by default). Deploys via `gcloud run deploy` with `--min-instances 0` for scale-to-zero cost behavior. See `implementationplan.md` for the exact deployment command and required environment variables.
