# Schema — ClaimGuard AI

## Core Application Schema (`app/models.py`)

### Claim (top-level document / API resource)
| Field | Type | Notes |
|---|---|---|
| claim_id | str | Auto-generated `CG-{uuid hex}` |
| status | enum | submitted \| processing \| reviewed \| flagged \| cleared \| error |
| claim_type | enum | auto \| home \| health — default "auto". Determines whether the vehicle-number check applies (auto only) |
| claimant_id, claimant_name, address | str | |
| policy_number, policy_start_date | str | |
| raw_text | str | The claimant's free-text narrative |
| file_urls | list[str] | Local paths to uploaded evidence (ephemeral on Cloud Run — see `tracker.md`) |
| declared_vehicle_number | str \| null | Required for claim_type="auto" (enforced in `app/main.py`, not the model itself, since Pydantic Form fields don't support conditional requiredness declaratively) — the registration number the claimant/policy declares |
| extracted | ExtractedFields \| null | Populated by Extraction Agent |
| consistency | ConsistencyResult \| null | Populated by Consistency Agent |
| pattern_flags | list[PatternFlag] | Populated by Pattern Agent — includes `vehicle_number_mismatch` / `vehicle_number_undetected` for auto claims |
| statistical_flags | list[PatternFlag] | Same shape as pattern_flags; populated by Statistical Agent |
| explainability | ExplainabilityResult \| null | Populated by Explainability Agent |
| adjuster_decision | AdjusterDecision \| null | Set by the human reviewer |
| created_at, updated_at | ISO 8601 str | |
| agent_trace | list[dict] | `{step, output, timestamp}` per pipeline stage — the audit trail |

### ExtractedFields
`incident_type, damage_description, claimed_amount (float|null), incident_date, policy_number, visible_evidence_summary, detected_vehicle_number (str|null)` — the last field is read directly from evidence photos by the Extraction Agent's multimodal capability (no separate OCR library), null if no plate is visible or the claim has no vehicle involved.

**Currency:** all monetary amounts throughout this system are in Indian Rupees (INR). Both the Consistency and Explainability Agent system prompts explicitly instruct the model to reference amounts using ₹ or "rupees," never $ — added after real Gemini output was observed defaulting to $ despite INR-denominated input data.

### ConsistencyResult
`consistency_flags: [{issue: str, confidence: float 0-1, severity: low|medium|high}], overall_match_assessment: str`

### PatternFlag (also used for statistical_flags)
`type: str, detail: str, related_claim_ids: list[str]`

### ExplainabilityResult
`risk_score: int 0-100, risk_tier: low|moderate|high, rationale: str, recommended_action: str`

### AdjusterDecision
`action: approve|override|escalate, reason: str, timestamp: str`

## Firestore Document Structure (when `USE_FIRESTORE=true`)

Collection: `claims`. Document ID = `claim_id`. Document body = the full Claim schema above, serialized as-is (Firestore's native document model maps directly onto the nested Pydantic structure with no flattening needed).

## Synthetic Dataset Schemas (demo/test data — never real customer data)

### `claimguard_synthetic_claims.json` (42 claims)
Fields: `claim_id, claimant_id, claimant_name, address, policy_number, incident_type, damage_description, claimed_amount, incident_date, damage_photo, photo_matches_description (bool), intended_flag (str, human-readable label of what this claim is designed to test)`.

### `demo_assets/live_demo_scenarios.json` (9 ordered scenarios)
Fields: `order, scenario_name, claimant_id, claimant_name, address, policy_number, policy_start_date, raw_text, evidence_image, expected_consistency, expected_pattern_flags, expected_statistical_flags, expected_overall, presenter_note`.

### `claimguard_industry_dataset.csv` / `claimguard_health_insurance_dataset.csv`
Insurance-industry-convention field naming (e.g., `date_of_loss`, `sum_insured_inr`, `cause_of_loss` for the general dataset; IRDAI-grounded fields like `hospital_rohini_id`, `tpa_irda_license_no`, `insured_card_id_number` for the health-specific dataset) plus simulation-only ROI columns (`manual_review_time_hours`, `cost_saved_inr`, `fraud_loss_avoided_inr`) — see the dataset methodology notes for the explicit list of illustrative-assumption values that must be replaced with real figures before any real business use.

## Data Honesty Conventions (applies across all synthetic data in this project)

- All names, addresses, policy numbers are fictional
- `ground_truth_label` / `intended_flag` fields exist ONLY in synthetic/test data — a real production dataset would not have these pre-labeled; the system determines them
- Placeholder evidence images are explicitly labeled "DEMO PLACEHOLDER — not a real photograph" within the image itself, not just in accompanying documentation
