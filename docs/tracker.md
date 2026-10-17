# Tracker — ClaimGuard AI

Status as of the most recent test run: **96/96 tests passing.** This file consolidates findings from the full architecture review (see the separately delivered 73-row tech-stack comparison spreadsheet for complete detail) into a single at-a-glance status.

## ✅ Built, Tested, and Verified

| Item | Verification |
|---|---|
| 6-agent pipeline (Extraction → Consistency → Pattern → Statistical → Retrieval → Explainability) | Live end-to-end run + unit tests |
| All 5 Pattern Agent flag types | Positive + negative test cases each |
| Benford's Law + Isolation Forest, including sample-size guards | Both sides of each threshold tested |
| Firestore backend logic | Mocked-client tests (real module-caching bug found and fixed) |
| API key auth | Live-tested: 401 without key, 200 with correct key |
| Rate limiting | Live-tested: 4th request in a 3/minute window returned 429 |
| File upload validation | Live-tested: a bash script renamed to `.jpg` correctly rejected (415) |
| Health check endpoint | Present, functioning — a genuine self-healing/liveness building block |
| Input validation (Pydantic) | Confirmed via 422-response tests |
| No XSS vector in dashboard | Confirmed by code inspection — no `unsafe_allow_html=True` anywhere |
| No SQL injection surface | Structural — Firestore is NoSQL, no query string construction |

## ✅ Fixed This Round — Trust & Deployability Gaps

| Item | What changed | Verification |
|---|---|---|
| **Risk score trusted from Gemini without verification** | Previously, real Gemini calls were instructed to self-report `risk_score`/`risk_tier` via the fixed formula, but nothing checked that it actually did. Since `risk_tier` directly sets `claim["status"]` to flagged/cleared (not just displayed text), an ungrounded score would silently misclassify a claim. Fixed: `compute_deterministic_score()` is now the single source of truth for score/tier/recommended_action in BOTH mock and real paths — Gemini's self-reported score is logged as a warning if it disagrees, but never used. Only the rationale narrative is taken from Gemini's actual output. | New test (`test_gemini_self_reported_score_is_overridden_by_deterministic_computation`) simulates a real Gemini response with a deliberately wrong score (12/low) and confirms the agent correctly overrides it to the verified computation (60/moderate) — this is the exact scenario MOCK_MODE alone could never catch, since the mock always agreed with itself by construction |
| **Packaged default model drift** | `app/config.py` and `.env.example` still defaulted `EXPLAINABILITY_MODEL` to `gemini-3.5-pro`, which returns a 404 for this project's actual API key (see the live debugging session that found this). A fresh clone or Antigravity rebuild would have hit the identical wall. Fixed: default changed to `gemini-3.5-flash`, matching what's actually confirmed working. | Verified by grep across the whole project for any remaining `gemini-3.5-pro`/`gemini-2.5-*` reference outside historical comments; full test suite re-run clean |

## ✅ Added This Round — Agent Evaluation Harness

| Item | What it covers | Result |
|---|---|---|
| `scripts/run_eval.py` + `docs/eval_results.md` | Runs the real Pattern Agent + Statistical Agent + deterministic scoring formula against all 42 labeled claims in `claimguard_synthetic_claims.json`, comparing predicted flagged/cleared against the dataset's `intended_flag` ground truth | **89.2% accuracy, 100% precision, 69.2% recall** on the 37 in-scope claims (5 pure consistency-mismatch claims reported separately as out of scope — see below). Zero false positives across all 24 clean claims. The 4 false negatives are explained, not hidden: they're the 1st/2nd claim of a 3-claim pattern sequence, which by definition can't be detected until the pattern completes. |
| **Known, stated limitation** | The Extraction Agent and Consistency Agent (the Gemini-backed stages) are **not** covered by this eval. MOCK_MODE returns one fixed canned response regardless of input, and the dataset has no real image files — only placeholder filenames — so there is nothing to genuinely evaluate without a real API key and real photos. This is documented explicitly in `docs/eval_results.md`, not glossed over. | Open item — would need a real `GEMINI_API_KEY` + real/matching photos per claim to close |

## ✅ Added This Round — RBAC (Role-Based Access Control)

Per explicit user sign-off: churn prediction dropped entirely (no genuine data to back it), 8 proposed roles consolidated to 5, and this iteration scoped to RBAC only (RAG/MCP deferred to a future iteration).

| Item | What it covers | Verification |
|---|---|---|
| `app/auth.py` — JWT (PyJWT, HS256) + bcrypt password hashing | 5 fixed, seeded demo accounts, one per role (end_user, adjuster, investigator, analyst, admin). `POST /auth/login` issues a token; `GET /auth/me` confirms identity. Honest, stated scope: no signup flow, no key rotation, no revocation list — see the module's own docstring. | 3 new login tests (success per role, wrong password, unknown username) |
| Server-side role enforcement on every existing endpoint | Submit: only end_user (own `claimant_id` only)/adjuster/admin. List/get: end_user sees only their own claims (others get 403). Decision: only adjuster/investigator/admin. New `GET /analytics/summary`: adjuster/investigator/analyst/admin, not end_user. | 16 new tests in `tests/test_rbac.py`, all passing — including a live curl check confirming an end_user gets a genuine 403 both for submitting under someone else's `claimant_id` and for hitting `/analytics/summary` |
| Streamlit role-conditional dashboard | Each role sees only its own tab set (My Claim/My Claims for end_user; New Submission/Case Files for adjuster; Case Files with a flagged-only default filter for investigator; Analytics for analyst; everything + a System/eval-status tab for admin). This is a UX convenience layered on top of the real server-side enforcement above, not the security boundary itself — stated explicitly in the code's own comments. | Playwright screenshots confirm: admin sees all 4 tabs + working Analytics (live `/analytics/summary` data) + System tab (renders `docs/eval_results.md`); end_user sees only 2 restricted tabs with claimant_id locked to their own account |
| Test suite growth | 66 → **87 tests**, all passing | Full `pytest tests/ -v` re-run from a clean venv |

## ✅ Added This Round — RAG (Retrieval Agent)

Per explicit user sign-off to proceed with the previously-deferred RAG and MCP work.

| Item | What it covers | Verification |
|---|---|---|
| `app/agents/retrieval_agent.py` — new 6th pipeline stage | Free, local TF-IDF + cosine similarity (scikit-learn, zero additional cost/network calls) finds the top-3 most textually-similar past claims to the one being processed. Deliberately NOT a Gemini embedding API call — stated honestly in the module docstring, to avoid another rate-limited dependency and because TF-IDF is a legitimate retrieval technique at this scale. | 7 new tests in `tests/test_retrieval_agent.py`: genuine similarity ranking (not mocked math), correct exclusion of the claim from its own history, and — critically — that the new flag does NOT fire for a similar claim that was never flagged (would otherwise be a noisy, untrustworthy signal) |
| New `similar_to_flagged_claim` deterministic fraud signal | Fires when similarity ≥ 55% to a PAST claim with `status == "flagged"`. Weighted +20 in `compute_deterministic_score()` (between pattern's +25 exact-match and statistical's +15 anomaly weight) — genuinely catches a reworded resubmission that the exact-text `duplicate_submission` check would miss, a different detection mechanism, not a duplicate of an existing one. | Live end-to-end curl test: two claims submitted with paraphrased-but-matching narratives — real 73% similarity computed, flag correctly raised, score correctly included the new +20 weight (35+20=55, moderate) |
| **Real RAG usage for generation, not just decoration** | The Explainability Agent's prompt now receives the retrieved `similar_claims` list and is instructed to cite a specific claim_id in its rationale only if genuinely relevant, and never to invent similarities beyond what's retrieved | Covered by the live end-to-end test above; prompt instruction reviewed for the "don't invent" constraint |
| **Bug found and fixed during live testing** | Initial `MIN_HISTORY_FOR_RETRIEVAL = 2` was wrong — modeled incorrectly on Statistical Agent's sample-size pattern, which doesn't apply to pairwise similarity. A live test with exactly 1 prior claim returned empty results silently. Fixed to `= 1` (the real minimum: need at least one other claim to compare against), with the corrected reasoning documented in the code, not just patched silently. | Re-ran the same live test after the fix — genuinely detected the match |
| Eval harness re-run with Retrieval Agent included | `scripts/run_eval.py` now also runs the Retrieval Agent sequentially, with status saved before each next claim (same ordering as production) so the "was it flagged?" check reflects computed history, not ground truth | Re-run: headline accuracy/precision/recall **unchanged** (89.2%/100%/69.2%) — honestly reported in `docs/eval_results.md` that this specific 42-claim dataset has no case isolating retrieval's unique value (no "reworded resubmission" scenario exists in it), even though the live test proves the mechanism works |
| Test suite growth | 87 → **96 tests**, all passing | Full `pytest tests/ -v` re-run from a clean venv |

## ✅ Added This Round — MCP Server (optional integration)

| Item | What it covers | Verification |
|---|---|---|
| `mcp_server.py` — 4 read-only MCP tools | `get_claim`, `list_flagged_claims`, `get_portfolio_analytics`, `search_similar_claims`. Shares `app/storage.py` and `app/agents/retrieval_agent.py` directly with the FastAPI app — no duplicated logic. Stated honestly as read-only this iteration (no submit/decide tools) and as Anthropic's protocol, not a Google technology — an integration choice on top of the hackathon's Gen AI work, not a Gemini feature. | `tests/test_mcp_server.py`: spawns the server as a **real subprocess over the actual stdio transport** (the same mechanism Claude Desktop uses, not an in-process shortcut), seeds it via the genuine pipeline with 2 real claims (one a reworded near-duplicate), and confirms all 4 tools return correct live data — including the Retrieval Agent catching the near-duplicate across the MCP boundary |
| **Real dependency conflict found and fixed, not papered over** | Installing the official `mcp` SDK (v2.3.0) into the main venv upgraded `starlette` to a version incompatible with `fastapi==0.115.0`, and broke the FastAPI app outright (`TypeError: Router.__init__() got an unexpected keyword argument`) — confirmed directly, not assumed. Fixed by isolating `mcp_server.py` into its own venv (`venv-mcp`, `requirements-mcp.txt`), documented with the exact error in the code's own comments. | Re-ran the full 96-test main suite after reverting the main venv to `requirements.txt` — confirmed clean, no regression |
| Dependency note, stated honestly | `mcp-types` 2.3.0 wants `pydantic>=2.12`, newer than this project's pinned `2.9.2`. Not a problem in practice because `mcp_server.py` only imports `app/storage.py` and `app/agents/retrieval_agent.py`, neither of which uses Pydantic — but called out explicitly rather than silently assumed safe. | — |
| Claude Desktop connection documented | Exact `claude_desktop_config.json` snippet in `README.md` | Not independently verified against a real Claude Desktop install in this environment (no desktop app available here) — stated as a documented config, not a claimed live demo |

## ✅ Fixed This Round — User-Reported Bugs & New Feature

| Item | What changed | Verification |
|---|---|---|
| **Currency display bug (user-reported)** | Real Gemini output was defaulting to `$` for amounts despite all input data being INR-denominated — root cause was the Consistency/Explainability system prompts never specifying a currency. Both now explicitly instruct ₹/"rupees", never $. | Live-tested via real dashboard submission — rationale text confirmed currency-clean |
| **Mandatory vehicle photo + plate cross-check (user-requested)** | New `claim_type` selector (auto/home/health); auto claims now require a `declared_vehicle_number` and at least one evidence photo, enforced at the API boundary (422 if missing). Extraction Agent reads the plate from the photo (genuine multimodal task); Pattern Agent does a deterministic string comparison (declared vs. detected) — same "Gemini for evidence reasoning, deterministic logic for exact comparison" split as the rest of the architecture. | 10 new tests (5 pattern-level, 5 API-level) + live-verified through the real dashboard: both a matching case (no flag) and a deliberately mismatched case (flag fired with correct detail text, contributing to risk score) |
| **Frontend redesign — live stats + example cases** | Landing section now shows real, live-computed stats (claims processed, flag rate, avg. pipeline time) from actual storage — zero fabricated numbers, honest "—" placeholders when data doesn't exist yet. "Example Case Studies" pulled directly from the project's own synthetic dataset, clearly labeled as illustrative, not customer testimonials. | Live-verified via Playwright screenshots at both empty-storage and populated states |
| **Pipeline trace replay** | Submission result now shows an animated step-by-step reveal of the 6-agent sequence. Honestly scoped: this replays the REAL `agent_trace` data returned in the one consolidated API response (backend is unchanged, still not streaming) — not a fake simulated progress bar. | Live-verified rendering correctly after a real submission |
| **Client-side validation** | Required fields and the auto-claim vehicle/photo requirement are now checked in the browser before hitting the API, with clear inline messages — mirrors the backend's real enforcement rather than replacing it. | Live-verified: submitting an incomplete auto claim shows both specific error messages with no wasted API call |

## ✅ Fixed This Round — Backend Reliability & Observability

| Fix | Verification |
|---|---|
| **Critical: async event-loop blocking bug** | `submit_claim` called the synchronous, Gemini-calling pipeline directly inside an `async def` endpoint with no `run_in_threadpool` — meaning a single slow claim would freeze the entire server, including `/health`, for every concurrent request. Live-proven fixed: a 4-second simulated claim ran concurrently with a `/health` check that returned in 0.00s. |
| Retry + backoff on Gemini calls | `tenacity`, 3 attempts, exponential backoff. Verified with simulated flaky/slow calls (can't test via MOCK_MODE, which bypasses this code path entirely) |
| Request timeout on Gemini calls | 30s wall-clock timeout via `concurrent.futures`, deliberately not an unverified SDK-internal parameter. Verified with a simulated slow call |
| Idempotency (client-supplied `Idempotency-Key` header) | Live-verified: retry with the same key returns the identical `claim_id` without reprocessing. Deliberately kept separate from the content-based `duplicate_submission` fraud check — a naive content-matching idempotency approach would have silently hidden a genuine fraud signal (a deliberate resubmission), which is now confirmed to still fire correctly when no idempotency key is used |
| Structured logging + explicit MOCK_MODE startup banner | Every claim's receipt, pipeline completion, and adjuster decision now logged. The MOCK_MODE banner directly addresses a real confusion that occurred earlier in this project's own development |
| GZip compression | Free bandwidth reduction on larger JSON responses |
| Pagination on `GET /claims` | `limit`/`offset` query params, tested |
| Narrative length limit (20,000 chars) | Cheap protective bound against oversized payloads, tested |
| OpenAPI documentation | Endpoint summaries/descriptions added — visible at `/docs` |

## ⚠️ Known Gaps — Genuinely Free to Fix (not yet done)

**Operational note:** Google retired the entire Gemini 2.5 generation (flash-lite, flash, and pro) for API keys without prior usage history sometime around mid-2026 — confirmed via a live 404 during local testing, corroborated by widely-reported issues on Google's own developer forum. `app/config.py`'s defaults were updated to the 3.5 generation as a result. If a fresh API key ever hits a 404 with "no longer available to new users" again, check https://ai.google.dev/gemini-api/docs/models for the current generation — this is a fast-moving part of the stack and worth expecting to need occasional updates.



| Gap | Why it matters |
|---|---|
| Secrets in plain env vars | No rotation, no access audit trail (Google Secret Manager's free tier would close this) |
| No dependency/vulnerability scanning | GitHub Dependabot is free and not yet enabled |

## ⚠️ Known Gaps — Require Paid Infrastructure or Real Scope (correctly deferred)

| Gap | Why it's deferred, not just missed |
|---|---|
| PII/PHI redaction before Gemini calls | The actual reason real health/financial data should never flow through the free AI Studio tier |
| Prompt injection defense (only partial) | System-prompt separation exists; a dedicated filter does not |
| Multi-region / high availability | Genuinely costs money even on "free tier" services (duplicate infra, cross-region transfer) |
| Firestore security rules (currently open/default) | Needs a real auth/user model to key rules off of, which doesn't exist yet |
| Ephemeral file storage on Cloud Run | Needs Cloud Storage (GCS) — a real but small architecture change, not done yet |
| Real Firestore Emulator I/O verification | Blocked by sandbox network restrictions during development — verification steps documented in `implementationplan.md`, not yet executed against a live emulator |

## 🔵 Deliberately Out of Scope (not gaps — architecture decisions)

- Multi-tenant SaaS architecture (single-tenant prototype; see `prd.md`)
- Caching layer, message queuing, CDN, container orchestration beyond Cloud Run's own model
- Real customer data of any kind
- Any feature not tied to the BFSI fraud-detection theme (see `prd.md` Out of Scope section)

## Open Questions Not Yet Answered (carried from earlier project discovery)

A separate, larger set of ~70 business/architecture discovery questions (target market, business model, real design-partner validation, regulatory scope) remain genuinely unanswered and are **not** hackathon-blocking — they matter only if this moves toward a real production commitment. Not repeated here in full; see project chat history for the two full discovery-question rounds if that phase becomes relevant.

## Next Recommended Actions (prioritized)

1. Run the real-Gemini rehearsal (`demo_assets/submit_demo_scenarios.py` with a real `GEMINI_API_KEY`) before recording the demo video — several scenarios cannot be validated in MOCK_MODE.
2. Close the two free, code-level gaps (retry logic, idempotency) if time permits before submission — both are cheap and directly demonstrate engineering maturity to judges.
3. Verify the real Firestore Emulator path once, before any actual Cloud Run deployment.
