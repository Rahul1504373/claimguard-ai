# Rules — ClaimGuard AI

These are the non-negotiable constraints for this project. Any contributor — human or AI coding agent — should treat these as fixed unless a decision explicitly changes them here first.

## Hackathon Compliance (fixed)

1. Must use Gemini models (`google-genai` SDK) for the Extraction, Consistency, and Explainability agents — this is the "meaningful use of Gen AI" the judging rubric scores at 40% weight.
2. Pattern Agent and Statistical Agent are **deliberately** non-Gemini, deterministic/classical-ML — this is a documented architecture decision (see `techspec.md`), never "fixed" by routing them through Gemini too.
3. Must be deployable on Google Cloud Run via the project's Dockerfile.
4. Must operate at **$0 cost** for the prototype phase (see Free-Tier Constraints below).
5. All code, documentation, and UI text in English.
6. Theme identification (BFSI: Intelligent Risk, Fraud & Financial Experiences) must remain clearly stated in the README.

## Free-Tier Constraints (fixed, until an explicit investment decision is made)

- Gemini API: use AI Studio keys with **billing disabled** — exceeding free quota returns 429 errors, never a charge.
- Firestore: default to the JSON-file backend for all local dev/testing (zero setup); Firestore itself stays within the free Spark tier (1 GiB storage, 50K reads/day, 20K writes/day) when deployed.
- Cloud Run: `--min-instances 0` (scale-to-zero) always, to avoid idle cost.
- Any new dependency must be free/open-source. No paid SaaS tool, API, or infrastructure without an explicit decision to move past the free-prototype phase.
- Set a Cloud Billing budget alert ($1-2) the moment Blaze billing is enabled for Cloud Run — this is required even for free-tier Cloud Run usage.

## Naming Conventions

- Use the exact field/function names already established in the test suite (`risk_score`, `consistency_flags`, `pattern_flags`, `statistical_flags`, `claim_id`, etc.) — these are load-bearing, referenced across models, agents, and tests.
- Beyond what's fixed by tests: full, clear, domain-meaningful names. No abbreviations (`claimed_amount`, not `amt`; `policy_start_date`, not `psd`). This is a judged submission — unclear naming reads as lower technical merit.
- Python: `snake_case` for functions/variables, `PascalCase` for Pydantic models, `UPPER_SNAKE_CASE` for module-level constants (e.g., `BENFORD_MIN_SAMPLES`).

## Testing Discipline

- The test suite is the correctness contract. If implementation and a test disagree, fix the implementation — never edit a test to force a pass.
- Every new agent, endpoint, or security control ships with dedicated tests, including both the positive (it fires when it should) and negative (it doesn't fire when it shouldn't, or a guard correctly blocks below-threshold input) cases.
- Prefer live end-to-end verification through the actual running server over trusting unit tests alone, for anything security- or integration-related — several real bugs in this project were only caught this way (see `tracker.md`).

## Data Honesty

- All demo/test data is synthetic and must be clearly labeled as such (see `schema.md`'s Data Honesty Conventions).
- Never present an illustrative assumption (a cost figure, a time estimate, a projected savings number) as a validated fact — see the dataset methodology notes for the explicit list of placeholder assumptions that must be replaced with real figures before any real business use.
- Never let a synthetic dataset's sample-size or composition imply a real-world fraud rate or prevalence — call out explicitly when a demonstration is a "mechanism proof," not a projection.

## Scope Discipline

- No feature is added without being tied back to either the hackathon rubric (`prd.md`) or an explicitly identified, currently-open gap (`tracker.md`). "Would be nice" is not sufficient justification at prototype stage.
- When extending an agentic coding tool (e.g., Antigravity) to build this project, favor giving it a precise specification plus the actual test files over pasting every implementation file verbatim — token-efficient and the test suite is the real correctness anchor, not a manual diff.

## Security Non-Negotiables Once Any Real Data Is Involved

- No real customer PII/PHI may pass through the free AI Studio Gemini tier under any circumstances (see `prd.md` Out of Scope, `tracker.md`'s deferred-gaps section).
- Auth (`CLAIMGUARD_API_KEY`) must be set (non-empty) before any deployment reachable outside a controlled demo/judge-testing context.
