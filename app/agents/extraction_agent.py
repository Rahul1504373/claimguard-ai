from app.config import settings
from app.gemini_client import call_gemini_json, load_image_part

SYSTEM_PROMPT = """You are a claims data extraction assistant for an insurance company.
Extract ONLY the following structured fields from the claim text and any
attached images/documents. Do not infer beyond what is stated or visible.
If a field cannot be determined, return null for it.

For detected_vehicle_number: if any attached image shows a vehicle number
plate / registration plate, read and return the exact plate text as shown
(preserve the original formatting/spacing as best you can). If no plate is
visible in any image, or this claim has no vehicle involved, return null —
do not guess or infer a plate number from context.

Return valid JSON matching this schema exactly:
{
  "incident_type": string,
  "damage_description": string,
  "claimed_amount": number | null,
  "incident_date": string | null,
  "policy_number": string | null,
  "visible_evidence_summary": string,
  "detected_vehicle_number": string | null
}
"""

# Used when GEMINI_API_KEY isn't set, so the pipeline is testable for free.
MOCK_RESPONSE = {
    "incident_type": "Auto collision",
    "damage_description": "Major front-end collision damage, vehicle undrivable, extensive structural damage.",
    "claimed_amount": 185000,
    "incident_date": "2026-07-20",
    "policy_number": "POL-70035",
    "visible_evidence_summary": "Photo shows a minor cosmetic scuff on the front bumper only; no structural deformation visible.",
    "detected_vehicle_number": "DL 3C AB 1234",
}


def run(raw_text: str, file_paths: list[str]) -> dict:
    parts = [f"Claim text: {raw_text}"]
    for path in file_paths:
        img = load_image_part(path)
        if img is not None:
            parts.append(img)

    return call_gemini_json(
        model=settings.EXTRACTION_MODEL,
        system_prompt=SYSTEM_PROMPT,
        user_content=parts,
        mock_response=MOCK_RESPONSE,
    )
