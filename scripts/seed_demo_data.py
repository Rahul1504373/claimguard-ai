"""
Pre-loads a curated set of claims from claimguard_synthetic_claims.json so
the Pattern Agent's relationships (repeat claimant, shared address ring,
frequency spike) are already visible when you open the dashboard — instead
of needing to submit 3+ claims live on camera to build up the pattern.

Run: python3 scripts/seed_demo_data.py
"""
import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app import storage
from app.models import Claim, now_iso

DATASET_PATH = os.path.join(os.path.dirname(__file__), "..", "claimguard_synthetic_claims.json")

# Claim IDs to pre-seed as "background" claims — these establish the pattern
# relationships (repeat claimant, address ring, frequency spike) so that when
# you submit CG-025 / CG-030 / etc. live during the demo, the Pattern Agent
# immediately finds a match. We seed them as already "cleared" so they read
# as legitimate history, not part of the live demo.
SEED_CLAIM_IDS = [
    "CG-016",  # Vikram Singh — sets up prior history before CG-034 (different Vikram Singh at ring address, deliberately same name different claimant to test the system doesn't just match on name)
    "CG-031", "CG-032",  # Ramesh Chandra — repeat claimant pattern (2 of the 3, so live submission of a 3rd would trigger it)
    "CG-034", "CG-035",  # shared address ring — 2 of 3 at Sunrise Colony, Faridabad
    "CG-037", "CG-038",  # Anjali Bose — frequency spike, 2 of 3
]


def seed():
    with open(DATASET_PATH) as f:
        dataset = json.load(f)["claims"]

    by_id = {c["claim_id"]: c for c in dataset}
    seeded = 0

    for cid in SEED_CLAIM_IDS:
        src = by_id.get(cid)
        if not src:
            print(f"  skip {cid}: not found in dataset")
            continue

        claim = Claim(
            claim_id=src["claim_id"],
            claimant_id=src["claimant_id"],
            claimant_name=src["claimant_name"],
            address=src["address"],
            policy_number=src["policy_number"],
            policy_start_date=src["policy_start_date"],
            raw_text=src["damage_description"],
            file_urls=[],
        ).model_dump()

        # Pre-fill extracted data (skips needing a live Gemini call for seed data)
        claim["extracted"] = {
            "incident_type": src["incident_type"],
            "damage_description": src["damage_description"],
            "claimed_amount": src["claimed_amount"],
            "incident_date": src["incident_date"],
            "policy_number": src["policy_number"],
            "visible_evidence_summary": src["damage_description"],
        }
        claim["consistency"] = {"consistency_flags": [], "overall_match_assessment": "Consistent."}
        claim["pattern_flags"] = []
        claim["explainability"] = {
            "risk_score": 0, "risk_tier": "low",
            "rationale": "Seed history claim — processed and cleared prior to this demo session.",
            "recommended_action": "Approve",
        }
        claim["status"] = "cleared"
        claim["updated_at"] = now_iso()

        storage.save_claim(claim)
        seeded += 1
        print(f"  seeded {cid} — {src['claimant_name']} @ {src['address']}")

    print(f"\nDone. {seeded} background claims seeded.")
    print("Now submit CG-025, CG-030, CG-033, or CG-036's details live through the")
    print("dashboard (or /claims API) to see the Consistency and Pattern agents fire")
    print("against this pre-loaded history in real time.")


if __name__ == "__main__":
    seed()
