import os
from dotenv import load_dotenv

load_dotenv()


class Settings:
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    # Model names as of the current Gemini generation available to this
    # project's API key. The 2.5 generation (flash-lite/flash/pro) was
    # retired for keys without prior usage history sometime around mid-2026
    # — confirmed via a live 404 from Google's own API, corroborated by
    # widely-reported issues on Google's developer forum for gemini-2.5-flash
    # and gemini-2.5-pro specifically, not just flash-lite. If these ever
    # 404 again, check https://ai.google.dev/gemini-api/docs/models for the
    # current generation and update here — this is a fast-moving API surface.
    EXTRACTION_MODEL: str = os.getenv("EXTRACTION_MODEL", "gemini-3.5-flash-lite")
    CONSISTENCY_MODEL: str = os.getenv("CONSISTENCY_MODEL", "gemini-3.5-flash")
    EXPLAINABILITY_MODEL: str = os.getenv("EXPLAINABILITY_MODEL", "gemini-3.5-flash")
    CLAIMS_STORE_PATH: str = os.getenv("CLAIMS_STORE_PATH", "data/claims_store.json")
    # False (default) = JSON-file backend, used by pytest — zero setup.
    # True = Firestore backend — point FIRESTORE_EMULATOR_HOST at the local
    # emulator for $0 production-resembling testing, or leave unset when
    # deployed to Cloud Run to use real Firestore's free tier.
    USE_FIRESTORE: bool = os.getenv("USE_FIRESTORE", "false").lower() == "true"

    # --- Security settings, all free at prototype scale ---
    # API key for authenticating requests. Empty string = auth DISABLED
    # (the default, so local dev/testing/pytest keep working without setup).
    # Set a real value via env var before any deployment beyond your own
    # machine — see .env.example for how this is generated and used.
    API_KEY: str = os.getenv("CLAIMGUARD_API_KEY", "")

    # Comma-separated list of allowed CORS origins. Defaults to localhost
    # dev ports only — never "*" — set explicitly via env var for your
    # actual deployed dashboard URL.
    ALLOWED_ORIGINS: list[str] = [
        o.strip() for o in os.getenv(
            "ALLOWED_ORIGINS", "http://localhost:8501,http://localhost:3000"
        ).split(",") if o.strip()
    ]

    # Max upload size in bytes (default 10 MB) — rejects oversized files
    # before they're even fully read, as a basic DoS/abuse guard.
    MAX_UPLOAD_SIZE_BYTES: int = int(os.getenv("MAX_UPLOAD_SIZE_BYTES", str(10 * 1024 * 1024)))

    # Rate limit for claim submission, per client IP. Free via slowapi
    # (in-memory, no Redis needed at this scale).
    RATE_LIMIT_SUBMIT: str = os.getenv("RATE_LIMIT_SUBMIT", "10/minute")
    # Rate limit for login attempts, per client IP — a basic brute-force guard.
    RATE_LIMIT_LOGIN: str = os.getenv("RATE_LIMIT_LOGIN", "10/minute")

    # --- RBAC settings, all free (see app/auth.py for the full scope note) ---
    # Signing secret for JWTs. The fallback below is for local dev/pytest
    # ONLY — it is publicly visible in this source file, so anything beyond
    # your own machine MUST set a real random value via env var (e.g.
    # `python -c "import secrets; print(secrets.token_hex(32))"`, free).
    JWT_SECRET: str = os.getenv("JWT_SECRET", "dev-only-insecure-secret-change-me")
    JWT_EXPIRE_MINUTES: int = int(os.getenv("JWT_EXPIRE_MINUTES", "120"))
    # Demo user store — five fixed accounts, one per role, auto-seeded on
    # first run if this file doesn't exist yet. NOT a real user-registration
    # system — see app/auth.py's module docstring for the honest scope.
    USERS_STORE_PATH: str = os.getenv("USERS_STORE_PATH", "data/users.json")


settings = Settings()
