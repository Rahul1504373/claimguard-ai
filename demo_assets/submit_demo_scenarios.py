"""
Submits every scenario from live_demo_scenarios.json to a running
ClaimGuard API instance, in order, printing what actually came back for
each — use this to REHEARSE and verify the scenario file works as
documented before recording, not just trust the documentation.

Requires the API to already be running (uvicorn app.main:app) and,
ideally, demo_assets/seed_statistical_baseline.py already run.

Usage:
    python3 demo_assets/submit_demo_scenarios.py [--base-url http://localhost:8000] [--api-key KEY]
"""
import argparse
import json
import os
import sys

import requests

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--api-key", default=os.getenv("CLAIMGUARD_API_KEY", ""))
    parser.add_argument("--only", type=int, default=None, help="Submit only this scenario's 'order' number")
    args = parser.parse_args()

    with open(os.path.join(SCRIPT_DIR, "live_demo_scenarios.json")) as f:
        data = json.load(f)

    headers = {"X-API-Key": args.api_key} if args.api_key else {}
    scenarios = data["scenarios"]
    if args.only is not None:
        scenarios = [s for s in scenarios if s["order"] == args.only]
        if not scenarios:
            print(f"No scenario with order={args.only}")
            sys.exit(1)

    for s in scenarios:
        print(f"\n{'='*70}")
        print(f"[{s['order']}] {s['scenario_name']}")
        print(f"{'='*70}")

        image_path = os.path.join(SCRIPT_DIR, "images", s["evidence_image"])
        files = {}
        if os.path.exists(image_path):
            files["files"] = (s["evidence_image"], open(image_path, "rb"), "image/jpeg")
        else:
            print(f"  WARNING: evidence image not found at {image_path}, submitting without it")

        form_data = {
            "claimant_id": s["claimant_id"],
            "claimant_name": s["claimant_name"],
            "address": s["address"],
            "policy_number": s["policy_number"],
            "policy_start_date": s["policy_start_date"],
            "raw_text": s["raw_text"],
        }

        try:
            resp = requests.post(f"{args.base_url}/claims", data=form_data, files=files,
                                  headers=headers, timeout=120)
        finally:
            if "files" in files:
                files["files"][1].close()

        if resp.status_code != 200:
            print(f"  FAILED: HTTP {resp.status_code} — {resp.text}")
            continue

        claim = resp.json()
        print(f"  claim_id: {claim['claim_id']}")
        print(f"  status: {claim['status']}")
        print(f"  expected: {s['expected_overall']}")
        cons_flags = (claim.get("consistency") or {}).get("consistency_flags", [])
        print(f"  consistency_flags: {[f['severity'] for f in cons_flags] if cons_flags else 'none'}")
        print(f"  pattern_flags: {[f['type'] for f in claim.get('pattern_flags', [])] or 'none'}")
        print(f"  statistical_flags: {[f['type'] for f in claim.get('statistical_flags', [])] or 'none'}")
        if claim.get("explainability"):
            exp = claim["explainability"]
            print(f"  risk_score: {exp['risk_score']} ({exp['risk_tier']})")


if __name__ == "__main__":
    main()
