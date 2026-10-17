from __future__ import annotations
from typing import Optional, Literal
from pydantic import BaseModel, Field
import uuid
import datetime


def new_id() -> str:
    return f"CG-{uuid.uuid4().hex[:8].upper()}"


def now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


class ClaimSubmission(BaseModel):
    claimant_id: str
    claimant_name: str
    address: str
    policy_number: str
    policy_start_date: str
    raw_text: str  # the claimant's free-text narrative


class ExtractedFields(BaseModel):
    incident_type: Optional[str] = None
    damage_description: Optional[str] = None
    claimed_amount: Optional[float] = None
    incident_date: Optional[str] = None
    policy_number: Optional[str] = None
    visible_evidence_summary: Optional[str] = None
    detected_vehicle_number: Optional[str] = None  # read from evidence photo by Extraction Agent, auto claims only


class ConsistencyFlag(BaseModel):
    issue: str
    confidence: float
    severity: Literal["low", "medium", "high"]


class ConsistencyResult(BaseModel):
    consistency_flags: list[ConsistencyFlag] = Field(default_factory=list)
    overall_match_assessment: str = ""


class PatternFlag(BaseModel):
    type: str
    detail: str
    related_claim_ids: list[str] = Field(default_factory=list)


class ExplainabilityResult(BaseModel):
    risk_score: int
    risk_tier: Literal["low", "moderate", "high"]
    rationale: str
    recommended_action: str


class AdjusterDecision(BaseModel):
    action: str  # "approve" | "override" | "escalate"
    reason: str
    timestamp: str = Field(default_factory=now_iso)


class Claim(BaseModel):
    claim_id: str = Field(default_factory=new_id)
    status: Literal["submitted", "processing", "reviewed", "flagged", "cleared", "error"] = "submitted"
    claim_type: Literal["auto", "home", "health"] = "auto"
    claimant_id: str
    claimant_name: str
    address: str
    policy_number: str
    policy_start_date: str
    raw_text: str
    file_urls: list[str] = Field(default_factory=list)
    declared_vehicle_number: Optional[str] = None  # required for claim_type="auto" — enforced in app/main.py, not here, since Pydantic Form fields don't support conditional requiredness declaratively

    extracted: Optional[ExtractedFields] = None
    consistency: Optional[ConsistencyResult] = None
    pattern_flags: list[PatternFlag] = Field(default_factory=list)
    statistical_flags: list[PatternFlag] = Field(default_factory=list)  # Benford's Law / Isolation Forest — same shape as pattern_flags, kept separate to distinguish deterministic rules from statistical methods in the audit trail
    similar_claims: list[dict] = Field(default_factory=list)  # RAG retrieval output — top-K most textually similar past claims (see app/agents/retrieval_agent.py), for audit/display, not fraud flags themselves
    retrieval_flags: list[PatternFlag] = Field(default_factory=list)  # new deterministic signal: narrative similarity to a PAST FLAGGED claim — separate from pattern_flags/statistical_flags in the audit trail, same shape
    explainability: Optional[ExplainabilityResult] = None

    adjuster_decision: Optional[AdjusterDecision] = None
    idempotency_key: Optional[str] = None  # client-supplied, for retry-safety — see app/main.py
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)
    agent_trace: list[dict] = Field(default_factory=list)  # audit log of each agent step


class DecisionRequest(BaseModel):
    action: Literal["approve", "override", "escalate"]
    reason: str


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str
    display_name: str
    claimant_id: Optional[str] = None


class CurrentUser(BaseModel):
    username: str
    role: str
    display_name: str
    claimant_id: Optional[str] = None
