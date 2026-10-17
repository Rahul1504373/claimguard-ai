"""
Deterministic, not Gemini-based — by design. Fraud-ring and frequency
signals need to be reliable and explainable, not subject to LLM variance.
This is a design choice worth stating explicitly in the pitch deck: Gen AI
where reasoning over unstructured evidence adds value, plain logic where
explainability and reliability matter more.
"""
import datetime
from app import storage

REPEAT_CLAIMANT_THRESHOLD = 2       # >= this many other claims from same claimant
FREQUENCY_WINDOW_DAYS = 45          # claims within this window count as a "spike"
FREQUENCY_THRESHOLD = 2             # >= this many other claims in the window


def _parse_date(d: str) -> datetime.date | None:
    try:
        return datetime.date.fromisoformat(d)
    except (ValueError, TypeError):
        return None


def run(claim: dict) -> list[dict]:
    flags = []
    claim_id = claim["claim_id"]
    claimant_id = claim["claimant_id"]
    address = claim["address"]
    incident_date = _parse_date(claim.get("incident_date") or claim.get("raw_text", "")[:0])

    same_claimant = storage.find_by_claimant(claimant_id, exclude_claim_id=claim_id)
    if len(same_claimant) >= REPEAT_CLAIMANT_THRESHOLD:
        flags.append({
            "type": "repeat_claimant",
            "detail": f"{len(same_claimant)} other claim(s) on file for this claimant.",
            "related_claim_ids": [c["claim_id"] for c in same_claimant],
        })

    same_address = storage.find_by_address(address, exclude_claim_id=claim_id)
    distinct_other_claimants = {c["claimant_id"] for c in same_address if c["claimant_id"] != claimant_id}
    if len(distinct_other_claimants) >= 1 and len(same_address) >= 1:
        flags.append({
            "type": "shared_address_ring",
            "detail": f"{len(distinct_other_claimants)} other claimant(s) share this address across {len(same_address)} claim(s).",
            "related_claim_ids": [c["claim_id"] for c in same_address],
        })

    # Duplicate submission: same policy_number + same incident description text
    duplicates = [
        c for c in storage.list_claims()
        if c["claim_id"] != claim_id
        and c.get("policy_number") == claim.get("policy_number")
        and c.get("raw_text") == claim.get("raw_text")
    ]
    if duplicates:
        flags.append({
            "type": "duplicate_submission",
            "detail": "Identical policy_number and claim narrative found in an existing claim.",
            "related_claim_ids": [c["claim_id"] for c in duplicates],
        })

    # Policy-date anomaly: incident predates policy start (needs extracted incident_date)
    extracted_incident_date = _parse_date((claim.get("extracted") or {}).get("incident_date", ""))
    policy_start = _parse_date(claim.get("policy_start_date", ""))
    if extracted_incident_date and policy_start and extracted_incident_date < policy_start:
        gap = (policy_start - extracted_incident_date).days
        flags.append({
            "type": "policy_date_anomaly",
            "detail": f"Incident date precedes policy start date by {gap} day(s).",
            "related_claim_ids": [],
        })

    # Claim frequency spike within a rolling window
    if extracted_incident_date:
        recent = []
        for c in same_claimant:
            c_date = _parse_date((c.get("extracted") or {}).get("incident_date", ""))
            if c_date and abs((extracted_incident_date - c_date).days) <= FREQUENCY_WINDOW_DAYS:
                recent.append(c["claim_id"])
        if len(recent) >= FREQUENCY_THRESHOLD:
            flags.append({
                "type": "claim_frequency_spike",
                "detail": f"{len(recent)} claim(s) from this claimant within a {FREQUENCY_WINDOW_DAYS}-day window.",
                "related_claim_ids": recent,
            })

    # Vehicle number mismatch: declared registration number vs. what was
    # actually read off the number plate in the evidence photo. Only
    # evaluated when a declared_vehicle_number was actually provided —
    # WHETHER one is required at all (mandatory for auto claims) is an
    # API-boundary concern enforced in app/main.py, not this agent's job.
    # This keeps the check backward-compatible with any claim that never
    # touches this feature, and keeps the separation of concerns clean:
    # "is the data present" vs. "does the data make sense" are different
    # questions, answered in different layers.
    if claim.get("claim_type") == "auto" and claim.get("declared_vehicle_number"):
        declared = claim["declared_vehicle_number"].strip().upper().replace(" ", "").replace("-", "")
        detected_raw = (claim.get("extracted") or {}).get("detected_vehicle_number")
        detected = (detected_raw or "").strip().upper().replace(" ", "").replace("-", "")

        if not detected_raw:
            flags.append({
                "type": "vehicle_number_undetected",
                "detail": "No vehicle number plate could be read from the submitted evidence photo(s).",
                "related_claim_ids": [],
            })
        elif declared != detected:
            flags.append({
                "type": "vehicle_number_mismatch",
                "detail": (
                    f"Declared vehicle number ({claim['declared_vehicle_number']}) does not match "
                    f"the number plate detected in the evidence photo ({detected_raw})."
                ),
                "related_claim_ids": [],
            })

    return flags
