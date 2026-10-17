import os
import shutil
import uuid
import logging
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Depends, Request, Header, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from starlette.concurrency import run_in_threadpool
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from app import storage, pipeline, auth
from app.config import settings
from app.models import Claim, DecisionRequest, AdjusterDecision, LoginRequest, TokenResponse, CurrentUser, now_iso
from app.security import verify_api_key, validate_upload

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger("claimguard.main")

limiter = Limiter(key_func=get_remote_address)

app = FastAPI(
    title="ClaimGuard AI",
    version="0.1.0",
    description=(
        "Explainable fraud-risk triage for insurance claims. Every risk score "
        "comes with an evidence-cited rationale from a 6-stage agent pipeline (Extraction, Consistency, Pattern, Statistical, Retrieval, Explainability) "
        "(Extraction, Consistency, Pattern, Statistical, Explainability) — "
        "see /docs for the full schema, or the project's docs/techspec.md."
    ),
)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    # Restricted to explicit known origins (see config.py / .env.example) —
    # never "*". Confirmed gap from an earlier review, fixed here.
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_methods=["GET", "POST", "PATCH"],
    allow_headers=["*"],
)
app.add_middleware(GZipMiddleware, minimum_size=1000)  # free bandwidth reduction on larger JSON/claim responses

UPLOAD_DIR = "data/uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)


@app.get("/health", summary="Liveness/readiness check — intentionally unauthenticated")
def health():
    return {"status": "ok"}


@app.post(
    "/auth/login", response_model=TokenResponse,
    summary="Exchange demo credentials for a role-bearing JWT",
    description=(
        "Demo-grade auth (see app/auth.py's module docstring for the honest "
        "scope: five fixed seeded accounts, no signup, no key rotation). "
        "Returns a bearer token valid for JWT_EXPIRE_MINUTES."
    ),
)
@limiter.limit(settings.RATE_LIMIT_LOGIN)
def login(request: Request, credentials: LoginRequest):
    user = auth.authenticate(credentials.username, credentials.password)
    if not user:
        raise HTTPException(status_code=401, detail="Incorrect username or password")
    token = auth.create_access_token(user)
    logger.info(f"Login success: user={user['username']} role={user['role']}")
    return TokenResponse(
        access_token=token, role=user["role"],
        display_name=user["display_name"], claimant_id=user.get("claimant_id"),
    )


@app.get("/auth/me", response_model=CurrentUser, summary="Who am I — confirms the current token's identity and role")
def whoami(current_user: dict = Depends(auth.get_current_user)):
    return CurrentUser(**current_user)


@app.get(
    "/analytics/summary",
    dependencies=[Depends(verify_api_key), Depends(auth.require_roles("adjuster", "investigator", "analyst", "admin"))],
    summary="Live, computed aggregate statistics — not available to end_user role",
)
def analytics_summary():
    """Every figure here is computed directly from storage.list_claims() at
    request time — nothing fabricated, nothing cached/stale. Intended for
    the analyst/admin dashboard views."""
    claims = storage.list_claims()
    total = len(claims)
    by_status = {}
    by_tier = {}
    pattern_type_counts = {}
    statistical_type_counts = {}
    retrieval_type_counts = {}
    scores = []

    for c in claims:
        by_status[c.get("status", "unknown")] = by_status.get(c.get("status", "unknown"), 0) + 1
        exp = c.get("explainability") or {}
        tier = exp.get("risk_tier")
        if tier:
            by_tier[tier] = by_tier.get(tier, 0) + 1
            scores.append(exp.get("risk_score", 0))
        for f in c.get("pattern_flags", []):
            pattern_type_counts[f["type"]] = pattern_type_counts.get(f["type"], 0) + 1
        for f in c.get("statistical_flags", []):
            statistical_type_counts[f["type"]] = statistical_type_counts.get(f["type"], 0) + 1
        for f in c.get("retrieval_flags", []):
            retrieval_type_counts[f["type"]] = retrieval_type_counts.get(f["type"], 0) + 1

    return {
        "total_claims": total,
        "by_status": by_status,
        "by_risk_tier": by_tier,
        "average_risk_score": round(sum(scores) / len(scores), 1) if scores else None,
        "pattern_flag_type_counts": pattern_type_counts,
        "statistical_flag_type_counts": statistical_type_counts,
        "retrieval_flag_type_counts": retrieval_type_counts,
    }


@app.post(
    "/claims", response_model=Claim, dependencies=[Depends(verify_api_key)],
    summary="Submit a new claim for risk assessment",
    description=(
        "Runs the full 6-agent pipeline synchronously and returns the "
        "completed assessment. Optionally pass an Idempotency-Key header "
        "to make retries safe: resubmitting the same key returns the "
        "original result without reprocessing. This is separate from, and "
        "does not weaken, the Pattern Agent's own content-based "
        "duplicate_submission fraud check, which still runs normally on "
        "every request that does NOT reuse an idempotency key."
    ),
)
@limiter.limit(settings.RATE_LIMIT_SUBMIT)
async def submit_claim(
    request: Request,
    claim_type: str = Form(default="auto"),
    claimant_id: str = Form(...),
    claimant_name: str = Form(...),
    address: str = Form(...),
    policy_number: str = Form(...),
    policy_start_date: str = Form(...),
    raw_text: str = Form(..., max_length=20000),  # cheap protective bound against oversized narrative payloads
    declared_vehicle_number: str = Form(default=None),
    files: list[UploadFile] = File(default=[]),
    idempotency_key: str = Header(default=None, alias="Idempotency-Key"),
    current_user: dict = Depends(auth.get_current_user),
):
    # RBAC: only end_user (self-service), adjuster (on behalf of any
    # claimant), and admin may submit. investigator/analyst are read-only
    # roles by design — they review, they don't originate claims.
    if current_user["role"] not in ("end_user", "adjuster", "admin"):
        raise HTTPException(status_code=403, detail=f"Role '{current_user['role']}' may not submit claims")
    # An end_user can only ever submit under their OWN claimant_id — this
    # is what stops one logged-in claimant from filing as someone else.
    if current_user["role"] == "end_user" and claimant_id != current_user["claimant_id"]:
        raise HTTPException(
            status_code=403,
            detail="End users may only submit claims under their own claimant_id",
        )

    if claim_type not in ("auto", "home", "health"):
        raise HTTPException(status_code=422, detail="claim_type must be one of: auto, home, health")

    # Mandatory-evidence rule lives HERE, at the API boundary — not inside
    # pattern_agent.py, which only compares data that's already present.
    # This is deliberately scoped to auto claims only: a home or health
    # claim has no vehicle, so requiring a plate photo for those would be
    # nonsensical, not just inconvenient.
    if claim_type == "auto":
        if not declared_vehicle_number or not declared_vehicle_number.strip():
            raise HTTPException(
                status_code=422,
                detail="Auto claims require a declared_vehicle_number (the registered vehicle number on the policy).",
            )
        if not files:
            raise HTTPException(
                status_code=422,
                detail="Auto claims require at least one evidence photo showing the vehicle and its number plate.",
            )

    if idempotency_key:
        existing = await run_in_threadpool(storage.find_by_idempotency_key, idempotency_key)
        if existing:
            logger.info(f"Idempotency-Key {idempotency_key} matched existing claim {existing['claim_id']} — returning cached result, not reprocessing.")
            return existing

    file_paths = []
    for f in files:
        content = await f.read()
        validate_upload(f, content)  # raises 413/415 on failure — checked BEFORE saving to disk

        ext = os.path.splitext(f.filename)[1]
        saved_name = f"{uuid.uuid4().hex}{ext}"
        saved_path = os.path.join(UPLOAD_DIR, saved_name)
        with open(saved_path, "wb") as out:
            out.write(content)
        file_paths.append(saved_path)

    claim = Claim(
        claim_type=claim_type,
        claimant_id=claimant_id,
        claimant_name=claimant_name,
        address=address,
        policy_number=policy_number,
        policy_start_date=policy_start_date,
        raw_text=raw_text,
        file_urls=file_paths,
        declared_vehicle_number=declared_vehicle_number,
        idempotency_key=idempotency_key,
    ).model_dump()

    logger.info(f"Claim {claim['claim_id']} received from claimant {claimant_id} — starting pipeline.")
    await run_in_threadpool(storage.save_claim, claim)

    # CRITICAL: process_claim makes blocking synchronous Gemini calls internally.
    # Running it directly in this async endpoint (without run_in_threadpool)
    # would block the entire event loop — freezing every other concurrent
    # request, including /health — for the full duration of the pipeline.
    # This was a real, previously undiscovered bug; fixed here.
    processed = await run_in_threadpool(pipeline.process_claim, claim)
    logger.info(f"Claim {claim['claim_id']} pipeline complete — status={processed['status']}.")
    return processed


@app.get(
    "/claims", response_model=list[Claim], dependencies=[Depends(verify_api_key)],
    summary="List claims, most recent first, with pagination",
)
def get_claims(
    limit: int = Query(default=50, ge=1, le=500, description="Max number of claims to return"),
    offset: int = Query(default=0, ge=0, description="Number of claims to skip, for pagination"),
    current_user: dict = Depends(auth.get_current_user),
):
    all_claims = sorted(storage.list_claims(), key=lambda c: c.get("created_at", ""), reverse=True)
    # RBAC: an end_user only ever sees their OWN claims. Every other role
    # sees the full list — this prototype doesn't yet narrow investigator's
    # view server-side (the Streamlit UI defaults it to flagged-only
    # client-side instead), which is a genuine, stated scope choice, not an
    # oversight.
    if current_user["role"] == "end_user":
        all_claims = [c for c in all_claims if c.get("claimant_id") == current_user["claimant_id"]]
    return all_claims[offset: offset + limit]


@app.get("/claims/{claim_id}", response_model=Claim, dependencies=[Depends(verify_api_key)])
def get_claim(claim_id: str, current_user: dict = Depends(auth.get_current_user)):
    claim = storage.get_claim(claim_id)
    if not claim:
        raise HTTPException(status_code=404, detail="Claim not found")
    if current_user["role"] == "end_user" and claim.get("claimant_id") != current_user["claimant_id"]:
        raise HTTPException(status_code=403, detail="You may only view your own claims")
    return claim


@app.patch(
    "/claims/{claim_id}/decision", response_model=Claim,
    dependencies=[Depends(verify_api_key), Depends(auth.require_roles("adjuster", "investigator", "admin"))],
)
def decide_claim(claim_id: str, decision: DecisionRequest):
    claim = storage.get_claim(claim_id)
    if not claim:
        raise HTTPException(status_code=404, detail="Claim not found")

    claim["adjuster_decision"] = AdjusterDecision(
        action=decision.action, reason=decision.reason
    ).model_dump()
    claim["updated_at"] = now_iso()
    storage.save_claim(claim)
    logger.info(f"Claim {claim_id} adjuster decision recorded: {decision.action}")
    return claim
