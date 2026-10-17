"""
RBAC — role-based access control. Free, prototype-grade, and honest about
exactly what that means:

- Password hashing via `bcrypt` (free, industry-standard, local computation
  — no paid service).
- Tokens via `PyJWT` (free, MIT-licensed), HS256-signed with a secret from
  settings.JWT_SECRET. This is a real, working JWT implementation — not a
  placeholder — but it is a SINGLE shared signing secret with no key
  rotation, no refresh-token flow, and no revocation list. That's a
  reasonable, explicit scope for a hackathon prototype demonstrating the
  RBAC *pattern*, not a production identity system (which would use a
  managed identity provider — Firebase Auth, Auth0, etc. — all of which
  have free tiers too, but are a separate integration, not built here).
- Users are a small, fixed JSON file (data/users.json), seeded with five
  demo accounts, one per role — NOT a real user-registration system.
  There is no signup endpoint. This is explicit, not hidden: see
  docs/techspec.md and README.md for the demo credentials and this same
  caveat.

Five roles, matching the consolidated role set agreed for this iteration:
  end_user     — claimant self-service: submit/view only their OWN claims
  adjuster     — today's core workflow: submit on behalf of any claimant,
                 review all claims, record determinations
  investigator — SIU/fraud focus: review all claims (UI defaults to
                 flagged/high-risk), record determinations
  analyst      — read-only aggregate analytics, no individual case access
                 beyond what the analytics endpoint exposes
  admin        — everything, plus the system/eval status view
"""
import json
import os
import datetime
import bcrypt
import jwt
from fastapi import Header, HTTPException
from app.config import settings

ROLES = ("end_user", "adjuster", "investigator", "analyst", "admin")


def _ensure_users_store():
    if os.path.exists(settings.USERS_STORE_PATH):
        return
    os.makedirs(os.path.dirname(settings.USERS_STORE_PATH) or ".", exist_ok=True)
    demo_users = {
        "end_user1": {
            "password_hash": hash_password("EndUser@123"),
            "role": "end_user",
            "claimant_id": "CL-2001",  # ties this login to a real claimant_id from the synthetic dataset (Anita Sharma, CG-001)
            "display_name": "Anita Sharma (Demo Claimant)",
        },
        "adjuster1": {
            "password_hash": hash_password("Adjuster@123"),
            "role": "adjuster",
            "claimant_id": None,
            "display_name": "Rohan Mehta (Claims Adjuster)",
        },
        "investigator1": {
            "password_hash": hash_password("Investigator@123"),
            "role": "investigator",
            "claimant_id": None,
            "display_name": "Priya Nair (SIU Investigator)",
        },
        "analyst1": {
            "password_hash": hash_password("Analyst@123"),
            "role": "analyst",
            "claimant_id": None,
            "display_name": "Karan Verma (Business Analyst)",
        },
        "admin1": {
            "password_hash": hash_password("Admin@123"),
            "role": "admin",
            "claimant_id": None,
            "display_name": "System Admin",
        },
    }
    with open(settings.USERS_STORE_PATH, "w") as f:
        json.dump(demo_users, f, indent=2)


def _load_users() -> dict:
    _ensure_users_store()
    with open(settings.USERS_STORE_PATH, "r") as f:
        return json.load(f)


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except ValueError:
        return False


def authenticate(username: str, password: str) -> dict | None:
    """Returns the user record (with username added) if credentials are
    valid, else None. Never raises on a bad username — same code path as a
    bad password, so a 401 doesn't leak which part was wrong."""
    users = _load_users()
    user = users.get(username)
    if not user or not verify_password(password, user["password_hash"]):
        return None
    return {"username": username, "role": user["role"], "claimant_id": user.get("claimant_id"),
            "display_name": user.get("display_name", username)}


def create_access_token(user: dict) -> str:
    expire = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(minutes=settings.JWT_EXPIRE_MINUTES)
    payload = {
        "sub": user["username"],
        "role": user["role"],
        "claimant_id": user.get("claimant_id"),
        "display_name": user.get("display_name"),
        "exp": expire,
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm="HS256")


def decode_access_token(token: str) -> dict:
    try:
        return jwt.decode(token, settings.JWT_SECRET, algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Session expired — please log in again")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid authentication token")


def get_current_user(authorization: str = Header(default="")) -> dict:
    """FastAPI dependency. Expects 'Authorization: Bearer <token>'."""
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or malformed Authorization header")
    token = authorization[len("Bearer "):]
    payload = decode_access_token(token)
    return {
        "username": payload["sub"],
        "role": payload["role"],
        "claimant_id": payload.get("claimant_id"),
        "display_name": payload.get("display_name"),
    }


def require_roles(*allowed_roles: str):
    """FastAPI dependency factory: require_roles("adjuster", "admin")."""
    from fastapi import Depends

    def checker(user: dict = Depends(get_current_user)) -> dict:
        if user["role"] not in allowed_roles:
            raise HTTPException(
                status_code=403,
                detail=f"Role '{user['role']}' is not permitted to perform this action (requires: {', '.join(allowed_roles)})",
            )
        return user
    return checker
