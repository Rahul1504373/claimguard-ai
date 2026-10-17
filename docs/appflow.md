# App Flow — ClaimGuard AI

## Primary Flow: Claim Submission → Risk Assessment → Adjuster Decision

1. **Adjuster or claim-intake system submits a claim** via the Streamlit dashboard's "Submit Claim" tab (or directly via `POST /claims` for system-to-system use): claimant details, policy details, a free-text narrative, and evidence files (photos/PDFs).

2. **Backend validates the request:**
   - API key checked (`X-API-Key` header) — rejected with 401 if missing/wrong (when auth is enabled)
   - Rate limit checked — rejected with 429 if exceeded
   - Each uploaded file's size and *actual* content-type checked (not just filename) — rejected with 413 (too large) or 415 (disallowed type) before anything is saved to disk

3. **Claim is saved** (status: `submitted`) and the 6-agent pipeline begins (status: `processing`):
   - **Extraction** reads the narrative + evidence, producing structured fields (incident type, damage description, claimed amount, incident date)
   - **Consistency** compares the narrative against the visual evidence, flagging factual mismatches (e.g., "major damage" narrative vs. a photo showing a minor scratch)
   - **Pattern** checks the claim against all prior claims in storage for repeat-claimant, shared-address, duplicate-submission, policy-date, and frequency-spike signals
   - **Statistical** checks the claim's amount against the full claim-history pool for Benford's Law digit-distribution anomalies and Isolation Forest multivariate outliers
   - **Explainability** synthesizes every prior agent's output into a single risk score (0–100), tier (low/moderate/high), plain-language rationale, and a recommended action

4. **Every step is logged** to the claim's `agent_trace` field — a full, timestamped audit trail of exactly which agent produced what, in what order. If any step fails, the claim is marked `status=error` with the failure logged, rather than silently losing data or crashing.

5. **Final status is set:** `cleared` (low risk) or `flagged` (moderate/high risk).

6. **Adjuster reviews the result** in the "Submit Claim" tab's result panel (immediately after their own submission) or the "Review Queue" tab (browsing all claims): sees the risk score/tier with color coding, the specific consistency and pattern/statistical flags with their reasoning text, and the full agent trace in an expandable section for anyone wanting to audit the reasoning chain.

7. **Adjuster records a decision:** approve, override, or escalate, with a required reason — this is saved to `adjuster_decision` and timestamped, becoming part of the permanent audit record. This is the human-in-the-loop point: the system never makes a binding decision on its own.

## Secondary Flow: Demo/Judge Walkthrough

For the hackathon demo specifically (see `demo_assets/live_demo_scenarios.json` for the exact scripted sequence):

1. Run `seed_statistical_baseline.py` before recording — pre-loads 32 historical claims (bypassing Gemini, instant, free) so the Statistical Agent's sample-size thresholds are already met.
2. Submit a clean claim live — establishes the baseline "fast, unflagged" case.
3. Submit the flagship mismatched claim live — the Consistency Agent's specific reasoning text is the key visual moment.
4. Show a pre-seeded pattern (repeat claimant or address ring) — demonstrates the system catching something no single claim reveals in isolation.
5. Submit the extreme-outlier claim (after baseline seeding) — demonstrates statistical detection working even on an otherwise well-documented, consistent claim.

## Error/Edge-Case Flows

- **Unauthenticated request** → 401, no processing attempted
- **Rate limit exceeded** → 429, no processing attempted
- **Malicious/oversized file** → 413/415, rejected before touching disk or Gemini
- **Gemini API failure mid-pipeline** → claim marked `status=error`, failure logged to `agent_trace`, exception re-raised (not silently swallowed)
- **Duplicate claim lookup on an empty history** (first-ever claim) → all pattern/statistical checks correctly return no flags (verified by `test_run_returns_no_flags_with_small_history` and the pattern-agent tests)
