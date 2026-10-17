"""
Security helpers, all free at prototype scale:

1. verify_api_key — a FastAPI dependency checking a shared-secret API key.
   Disabled (no-op) when settings.API_KEY is empty, so local dev/pytest
   never need to set one up. This is intentionally simple (a single shared
   key, not per-user OAuth/JWT) — appropriate for a prototype with no user
   accounts yet, and a large step up from zero authentication.

2. validate_upload — checks file size against a limit AND sniffs the
   actual file content (via python-magic) rather than trusting the
   filename extension, so a malicious executable renamed to .jpg is
   rejected rather than silently accepted.
"""
import magic
from fastapi import Header, HTTPException, UploadFile
from app.config import settings

ALLOWED_MIME_TYPES = {
    "image/jpeg", "image/png", "image/webp",
    "application/pdf",
}


def verify_api_key(x_api_key: str = Header(default="")):
    """FastAPI dependency. No-op if settings.API_KEY is unset (local dev).
    Once set, every protected request must include a matching
    X-API-Key header, or it's rejected with 401."""
    if not settings.API_KEY:
        return  # auth disabled — local/dev/test mode
    if x_api_key != settings.API_KEY:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")


def validate_upload(file: UploadFile, content: bytes) -> None:
    """Raises HTTPException if the upload fails size or content-type checks.
    Call this AFTER reading the file's bytes (content), before saving to disk."""
    if len(content) > settings.MAX_UPLOAD_SIZE_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"File '{file.filename}' exceeds the {settings.MAX_UPLOAD_SIZE_BYTES} byte limit",
        )

    detected_type = magic.from_buffer(content, mime=True)
    if detected_type not in ALLOWED_MIME_TYPES:
        raise HTTPException(
            status_code=415,
            detail=(
                f"File '{file.filename}' has content-type '{detected_type}', "
                f"which is not one of the allowed evidence types: {sorted(ALLOWED_MIME_TYPES)}"
            ),
        )
