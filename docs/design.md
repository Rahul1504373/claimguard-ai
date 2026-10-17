# Design — ClaimGuard AI

## Design Philosophy

The system's core differentiation (see `prd.md` Goal #1) is explainability — every risk score comes with a defensible, evidence-cited rationale, not a black-box number. The visual redesign leans into this directly through a **case-file / evidence-dossier** metaphor grounded in the actual domain (claims investigation), rather than a generic AI-startup dashboard look: a claim result reads as an official case file with numbered exhibits and a formal risk verdict, not a SaaS metrics panel.

## Visual Language

**Color:** Ink Navy `#142440` (headers, masthead, authority) · Paper `#EEEFEA` (background — deliberately cooler and quieter than the warm-cream tone common in AI-generated pages) · Seal Amber `#C8862B` (flagged findings — evokes an official stamp, not a bright SaaS-warning yellow) · Verified Green `#2F6D4F` and Alert Crimson `#A32330` for cleared/high-risk states (deep, institutional tones rather than neon).

**Type:** Serif (`Georgia`/`Iowan Old Style` system stack) for headings — institutional, document-like, and loads reliably with no external font dependency (a real consideration for a live demo on unknown wifi). Clean sans-serif for body text and UI chrome. Monospace reserved specifically for claim/policy identifiers — genuinely justified since these are literal codes, not a decorative choice.

**One consistent structural device:** every flag/finding carries a thick colored left border — an "evidence tab" motif — rather than Streamlit's default rounded, softly-shadowed alert boxes. This is the one bold, memorable element; everything else (spacing, typography, layout) stays quiet and disciplined around it, per the "spend your boldness in one place" design principle.

## Dashboard Layout (`streamlit_app.py`)

A navy masthead with an amber accent border, followed by a **live stats strip** and **Example Case Studies** section (new this round — see below), then two tabs restyled as folder tabs (📥 New Submission, 🗄️ Case Files):

### New Submission
- **Claim Intake** form in a bordered container, with a **Claim Type** selector (Auto/Home/Health) controlling what's required — auto claims additionally require a Registered Vehicle Number field and at least one evidence photo, both enforced client-side (clear inline errors) and server-side (the real boundary)
- **Pipeline Trace**: an animated reveal of the 5 agents completing in sequence, replaying the real `agent_trace` from the response (see the Honesty Note below — this is not literally synchronous with backend processing)
- **Case File Assessment** result panel: claim ID shown as a monospace badge, risk score as a bordered metric card (navy left border), rationale and recommended action alongside it
- **Evidence Exhibits**: two columns — "Exhibit A: Consistency Findings" and "Exhibit B: Pattern & Statistical Findings" — each flag rendered with its colored left-border tab and full reasoning text, never a bare label. For auto claims, this now includes `vehicle_number_mismatch` / `vehicle_number_undetected` findings alongside the existing fraud patterns
- Full agent trace available in a collapsed expander for anyone auditing the reasoning chain
- **Adjuster Determination** form directly below — the human-in-the-loop step as the natural next action

### Case Files (review queue)
All claims, most recent first, each an expandable row with an at-a-glance risk icon. Now also shows Claim Type and Declared Vehicle Number where applicable.

## Live Stats & Example Case Studies (new this round)

**Live stats** (claims processed, flag rate, avg. pipeline time) are computed directly from `GET /claims` at page load — every number is real, sourced from actual storage, with an honest "—" placeholder when there isn't enough data yet (e.g., zero claims processed). Nothing here is fabricated or hardcoded, per explicit direction: a hackathon submission's landing page showing invented "98% fraud catch rate" style statistics would be a credibility risk, not a feature, if a judge asked where the number came from.

**Example Case Studies** are pulled from the project's own bundled synthetic dataset (`claimguard_synthetic_claims.json`), not live customer data or testimonials — each card is explicitly labeled "EXAMPLE" and the section caption states directly that these are illustrative scenarios from the test dataset. This was a deliberate alternative to fabricated "customer success stories," chosen specifically to get visual dynamism without dishonesty.

## Honesty Note: What "Pipeline Trace" Replay Actually Is

The backend (`app/main.py`) is unchanged — it still runs the full 6-agent pipeline synchronously and returns one consolidated result, not a stream of progress events. The animated step-by-step reveal in the dashboard replays the real `agent_trace` array (real timestamps, real per-stage output) from that one response, paced with a short delay per step for visual clarity. It is not literally synchronous with backend processing, and the code comments and this document both say so explicitly — this was a deliberate choice to get a genuine "wow" moment without building fake progress on invented data, and without changing the backend's actual response contract.

## Security Property Preserved

The dashboard uses `st.markdown(..., unsafe_allow_html=True)` in four places: the static CSS block, the static masthead, the live-stats strip, and the example-case cards. The first two contain zero interpolated variables (plain triple-quoted strings, not f-strings). The latter two DO interpolate values, but only ever numbers passed through `int()`/`round()` (live stats — cannot carry arbitrary text) or content sourced from the project's own bundled dataset file, never from a submitted claim or any other user-controlled input (example cases — equivalent risk profile to static content, since that file isn't writable through the running app). All actual claim-derived and user-submitted content — narrative, rationale, flag text, claim IDs — continues to render exclusively through Streamlit's native, auto-escaping components (`st.write`, `st.warning`, `st.metric`, `st.code`, etc.), preserving the security property documented in `tracker.md`.

## Verification

Unlike the original version, this redesign was verified with actual browser automation (Playwright, headless Chromium) rather than assumed from a syntax check: the empty page, a real form submission, and the full result panel (including a case with 5 simultaneous flags) were each screenshotted and inspected, confirming no Streamlit exception occurred and the layout renders as designed.

## Why Streamlit, and its acknowledged limits

Streamlit was chosen for zero-cost prototyping speed (see `techspec.md`), not as a production UI decision. Custom CSS extends its visual range considerably, but it correctly cannot deliver what a real consumer/adjuster-facing app needs at scale (native mobile, offline support, push notifications) — documented honestly in the tech-stack comparison, not presented as a finished production interface.
