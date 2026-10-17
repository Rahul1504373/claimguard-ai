from app.config import settings
from app.gemini_client import call_gemini_json, load_image_part

SYSTEM_PROMPT = """You are a claims consistency reviewer. Compare the claimant's narrative and
claimed amount against the visual evidence provided. Identify specific
mismatches — do not speculate about fraud intent, only report factual
inconsistencies between what was claimed and what is visible/stated.

CURRENCY: All monetary amounts in this system are in Indian Rupees (INR).
When referencing an amount in the "issue" text, always use the ₹ symbol or
the word "rupees" — never $ or any other currency symbol.

For each inconsistency found, output an object with:
  "issue": string,          // specific, e.g. "Claimed damage described as severe collision impact; image shows minor surface scratch only"
  "confidence": number,     // 0-1, how confident you are this is a genuine mismatch
  "severity": "low" | "medium" | "high"

Return JSON: { "consistency_flags": [ ... ], "overall_match_assessment": string }

If no inconsistencies are found, return an empty array and state that
evidence is consistent with the narrative in overall_match_assessment.
"""

# Mirrors the CG-025 style mismatch from the synthetic dataset for mock testing.
MOCK_RESPONSE = {
    "consistency_flags": [
        {
            "issue": "Claimed damage described as major structural collision damage; photo shows only a minor cosmetic scuff with no structural deformation.",
            "confidence": 0.86,
            "severity": "high",
        }
    ],
    "overall_match_assessment": "Significant mismatch between narrative severity and visible evidence.",
}


def run(extracted: dict, file_paths: list[str]) -> dict:
    parts = [f"Extracted claim data: {extracted}"]
    for path in file_paths:
        img = load_image_part(path)
        if img is not None:
            parts.append(img)

    return call_gemini_json(
        model=settings.CONSISTENCY_MODEL,
        system_prompt=SYSTEM_PROMPT,
        user_content=parts,
        mock_response=MOCK_RESPONSE,
    )
