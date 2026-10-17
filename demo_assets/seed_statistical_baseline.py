"""
Pre-seeds 32 baseline claims directly into storage, bypassing Gemini
entirely (no API key, no cost, instant). Purpose: the Statistical Agent
requires >=30 claims for Benford's Law and >=10 for Isolation Forest to be
statistically meaningful. Without pre-seeding this history, a live demo
would need 30 real claim submissions on camera before either check could
ever fire — impractical for a 3-minute video.

The 32 amounts below are deliberately varied across leading digits in a
way that broadly follows Benford's Law's natural distribution (more
values starting with 1-3 than with 7-9), so this baseline reads as
"normal" — it's the LIVE scenario claims (see live_demo_scenarios.json)
that are designed to stand out against it.

Run: python3 demo_assets/seed_statistical_baseline.py
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app import storage
from app.models import Claim, now_iso

# Amounts chosen to broadly follow Benford's natural leading-digit
# distribution (roughly: digit 1 ~30%, digit 2 ~18%, tapering to digit 9 ~5%)
BASELINE_AMOUNTS = [
    1200, 1450, 1800, 1150, 1920, 1300, 1670,       # leading digit 1 (7)
    2100, 2450, 2800, 2200,                          # leading digit 2 (4)
    3300, 3900, 3150,                                # leading digit 3 (3)
    4200, 4800,                                      # leading digit 4 (2)
    5100, 5600, 5900,                                # leading digit 5 (3)
    6200, 6700,                                      # leading digit 6 (2)
    7400, 7100,                                      # leading digit 7 (2)
    8300, 8900,                                      # leading digit 8 (2)
    9200,                                            # leading digit 9 (1)
    1050, 1580, 1290, 2650, 3700, 5300,              # padding to reach 32
]

BASELINE_INCIDENT_TYPES = [
    "Auto collision", "Home water damage", "Home fire damage",
    "Health outpatient procedure", "Auto theft", "Home storm damage",
]


def seed():
    for i, amount in enumerate(BASELINE_AMOUNTS):
        claim_id = f"BASELINE-{i+1:03d}"
        claim = Claim(
            claim_id=claim_id,
            claimant_id=f"CL-BASELINE-{i+1}",
            claimant_name=f"Baseline Claimant {i+1}",
            address=f"{i+1} Baseline Avenue, Demo City",
            policy_number=f"POL-BASE-{1000+i}",
            policy_start_date="2024-01-01",
            raw_text=f"Routine {BASELINE_INCIDENT_TYPES[i % len(BASELINE_INCIDENT_TYPES)].lower()} claim.",
            file_urls=[],
        ).model_dump()

        claim["extracted"] = {
            "incident_type": BASELINE_INCIDENT_TYPES[i % len(BASELINE_INCIDENT_TYPES)],
            "damage_description": "Routine claim, evidence consistent with narrative.",
            "claimed_amount": amount,
            "incident_date": "2026-06-01",
            "policy_number": claim["policy_number"],
            "visible_evidence_summary": "Consistent with narrative.",
        }
        claim["consistency"] = {"consistency_flags": [], "overall_match_assessment": "Consistent."}
        claim["pattern_flags"] = []
        claim["statistical_flags"] = []
        claim["explainability"] = {
            "risk_score": 0, "risk_tier": "low",
            "rationale": "Baseline history claim — processed and cleared prior to this demo session.",
            "recommended_action": "Approve",
        }
        claim["status"] = "cleared"
        claim["updated_at"] = now_iso()

        storage.save_claim(claim)

    print(f"Seeded {len(BASELINE_AMOUNTS)} baseline claims.")
    print("Statistical Agent thresholds now met: Benford's Law (>=30) and Isolation Forest (>=10).")
    print("Live-submitted scenario claims will now be checked against this history immediately.")


if __name__ == "__main__":
    seed()
