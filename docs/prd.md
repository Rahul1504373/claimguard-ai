# PRD — ClaimGuard AI

## Problem Statement

Insurance claims adjusters manually cross-check claim narratives, submitted photos/documents, and policy history to detect fraud — a process that is slow, inconsistent across adjusters, and difficult to audit. Existing AI fraud-detection tools typically output a black-box risk score with no supporting rationale, which adjusters and compliance reviewers cannot act on or defend to a regulator.

## Hackathon Context

- **Event:** H2S x Google Cloud Gen AI Hackathon
- **Theme:** BFSI — Intelligent Risk, Fraud & Financial Experiences
- **Mandatory technical requirements:** must leverage Google AI models (Gemini/Gemma family) or agentic platforms (Agent Platform, Antigravity, AI Studio); must deploy on Google Cloud via Cloud Run or Firebase
- **Judging rubric:** Technical Merit & Gen AI Implementation (40%), Problem Alignment & Impact (25%), Innovation & Creativity (25%), User Experience & Solution Design (10%)

## Goals

1. Produce a claim risk score that comes with a **defensible, evidence-cited rationale**, not a black-box number.
2. Demonstrate a genuinely hybrid architecture: Gemini for reasoning over unstructured evidence (photos, narratives), classical statistical/ML methods for what they do better (digit-distribution analysis, multivariate outlier detection) — directly addressing the 40%-weighted "meaningful use of Gen AI" criterion without over-relying on it for tasks it's not suited to.
3. Build a working prototype, not a mockup or slide deck — functional end-to-end, tested.
4. Operate at **$0 cost** throughout the prototype phase (see `rules.md` for the specific free-tier constraints this places on every technical decision).

## Target Users (prototype scope)

- **Primary:** Insurance claims adjusters reviewing flagged claims
- **Secondary (not yet built, noted for future scope):** SIU (Special Investigation Unit) investigators, compliance reviewers auditing AI-assisted decisions

## In Scope (prototype)

- Claim submission (text narrative + photo/PDF evidence)
- Four-stage automated risk assessment: Extraction → Consistency → Pattern → Statistical → Explainability (five agents; naming kept as "four-agent pipeline" in early docs before the Statistical Agent was added — see `tracker.md`)
- Adjuster review dashboard: view flags, rationale, accept/override/escalate with a logged reason
- Basic security: API key auth, rate limiting, restricted CORS, real file-content validation

## Explicitly Out of Scope (prototype)

- Real customer data of any kind (synthetic/demo data only — see `schema.md` and the dataset methodology notes)
- Multi-tenant SaaS architecture (single-tenant only; see `techspec.md` for the migration path if this becomes a real product)
- PII/PHI redaction pipeline, dedicated AI Gateway, prompt-injection defense beyond basic system-prompt separation (all identified as real gaps in the security review — see `tracker.md`)
- Multi-region deployment, load balancing beyond Cloud Run's built-in behavior, CDN, caching, message queuing

## Success Criteria

**For the hackathon submission specifically:** score well against the four rubric criteria above, with a working, demoable prototype and an honest, well-documented submission package (deck, video, this documentation set).

**For "does this become a real product" (a separate, later-stage question — see the discovery-question rounds earlier in project history, not repeated here):** not yet defined, deliberately — see `prd.md`'s companion discussion in project chat history regarding the ~70 unanswered discovery questions before any real production commitment should be made. This PRD covers the hackathon prototype only.

## Non-Goals

This system does not (and is not claimed to) replace human adjuster judgment — every flag is advisory, logged, and requires human decision (approve/override/escalate). It does not process real financial transactions or make binding claim decisions.
