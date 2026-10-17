"""
Statistical Agent — deliberately NOT a Gemini call, same design philosophy
as pattern_agent.py: classical statistical/ML methods where they genuinely
outperform LLM reasoning (detecting digit-distribution anomalies, or
multivariate outliers, is exactly what these methods are built for), kept
separate and deterministic so results are reproducible and auditable.

This module implements two real, industry-standard fraud-detection
techniques, each with an honest minimum-sample-size guard:

1. Benford's Law digit analysis — fabricated numbers (invented by a human)
   tend not to follow the natural logarithmic distribution of leading
   digits that real, organically-generated financial amounts follow.
   Requires a reasonable sample size to be statistically meaningful; below
   that threshold this returns "insufficient_data" rather than a
   misleadingly confident result on noise.

2. Isolation Forest — an unsupervised anomaly-detection model (scikit-learn,
   free) that isolates outliers in multivariate space faster than normal
   points. Also requires a minimum sample size to produce a meaningful
   anomaly score rather than an artifact of a tiny, unrepresentative batch.

Both feed into pattern_flags-shaped output so they integrate with the
existing Explainability Agent's scoring formula without changing its shape.
"""
import math
from collections import Counter

BENFORD_MIN_SAMPLES = 30   # commonly cited minimum for Benford's Law to be meaningful; ideally 100+
ISOLATION_FOREST_MIN_SAMPLES = 10  # sklearn will run below this, but results are not statistically reliable

# Benford's Law expected frequency for each leading digit 1-9
BENFORD_EXPECTED = {d: math.log10(1 + 1 / d) for d in range(1, 10)}


def _leading_digit(n: float) -> int | None:
    n = abs(n)
    if n == 0:
        return None
    while n < 1:
        n *= 10
    while n >= 10:
        n /= 10
    return int(n)


def check_benfords_law(amounts: list[float]) -> dict:
    """
    Compares the leading-digit distribution of `amounts` against Benford's
    Law's expected distribution using Mean Absolute Deviation (MAD) — a
    standard, simple metric for this (Nigrini's MAD conformity thresholds
    are the common reference points in forensic accounting literature).

    Returns {"applicable": False, "reason": ...} below the minimum sample
    size, rather than computing a deviation score on too little data.
    """
    valid_amounts = [a for a in amounts if a and a > 0]
    if len(valid_amounts) < BENFORD_MIN_SAMPLES:
        return {
            "applicable": False,
            "reason": f"insufficient sample size for Benford's Law (need >= {BENFORD_MIN_SAMPLES}, got {len(valid_amounts)})",
            "sample_size": len(valid_amounts),
        }

    digit_counts = Counter(_leading_digit(a) for a in valid_amounts)
    total = len(valid_amounts)
    observed = {d: digit_counts.get(d, 0) / total for d in range(1, 10)}

    mad = sum(abs(observed[d] - BENFORD_EXPECTED[d]) for d in range(1, 10)) / 9

    # Nigrini's commonly-cited MAD conformity bands for first-digit analysis:
    # <0.006 close conformity, 0.006-0.012 acceptable, 0.012-0.015 marginal, >0.015 nonconformity
    if mad > 0.015:
        conformity = "nonconformity"
    elif mad > 0.012:
        conformity = "marginal"
    elif mad > 0.006:
        conformity = "acceptable"
    else:
        conformity = "close_conformity"

    return {
        "applicable": True,
        "sample_size": total,
        "mean_absolute_deviation": round(mad, 5),
        "conformity": conformity,
        "flagged": conformity == "nonconformity",
        "observed_distribution": {str(d): round(v, 4) for d, v in observed.items()},
        "expected_distribution": {str(d): round(v, 4) for d, v in BENFORD_EXPECTED.items()},
    }


def compute_isolation_forest_scores(claims_with_amounts: list[dict]) -> dict:
    """
    claims_with_amounts: list of {"claim_id": str, "claimed_amount": float}
    Returns {claim_id: {"anomaly_score": float, "is_outlier": bool}} for
    every claim, or {"applicable": False, "reason": ...} below the minimum
    sample size.

    Only claimed_amount is used as a feature — this is intentionally minimal
    given the current schema's single reliably-numeric field. It's a real,
    legitimate use of Isolation Forest (univariate isolation is valid), but
    its power increases once more structured numeric fields exist (e.g.
    length_of_stay, prior_claims_count) — noted honestly rather than
    overselling this as a rich multivariate model today.
    """
    valid = [c for c in claims_with_amounts if c.get("claimed_amount")]
    if len(valid) < ISOLATION_FOREST_MIN_SAMPLES:
        return {
            "applicable": False,
            "reason": f"insufficient sample size for Isolation Forest (need >= {ISOLATION_FOREST_MIN_SAMPLES}, got {len(valid)})",
            "sample_size": len(valid),
        }

    from sklearn.ensemble import IsolationForest
    import numpy as np

    X = np.array([[c["claimed_amount"]] for c in valid])
    model = IsolationForest(contamination="auto", random_state=42)
    model.fit(X)
    raw_scores = model.decision_function(X)  # higher = more normal, lower/negative = more anomalous
    predictions = model.predict(X)  # -1 = outlier, 1 = normal

    results = {"applicable": True, "sample_size": len(valid), "scores": {}}
    for c, score, pred in zip(valid, raw_scores, predictions):
        results["scores"][c["claim_id"]] = {
            "anomaly_score": round(float(score), 4),
            "is_outlier": bool(pred == -1),
        }
    return results


def run(claim: dict, claim_history: list[dict]) -> list[dict]:
    """
    Orchestrates both checks for a single claim against its available
    history, returning pattern_flags-shaped output. `claim_history` should
    be the pool of claims to compare against (e.g., all claims for the same
    provider/hospital, or the full portfolio — caller's choice based on
    what grouping is meaningful for their data).
    """
    flags = []
    claim_id = claim["claim_id"]
    extracted = claim.get("extracted") or {}
    this_amount = extracted.get("claimed_amount")

    all_claims = claim_history + [claim]
    amounts = [
        (c.get("extracted") or {}).get("claimed_amount")
        for c in all_claims
    ]
    amounts = [a for a in amounts if a]

    benford_result = check_benfords_law(amounts)
    if benford_result.get("applicable") and benford_result.get("flagged"):
        flags.append({
            "type": "benfords_law_nonconformity",
            "detail": (
                f"Leading-digit distribution across {benford_result['sample_size']} claims deviates "
                f"significantly from Benford's Law (MAD={benford_result['mean_absolute_deviation']}), "
                "suggestive of fabricated rather than organically-generated amounts."
            ),
            "related_claim_ids": [],
        })

    claims_with_amounts = [
        {"claim_id": c["claim_id"], "claimed_amount": (c.get("extracted") or {}).get("claimed_amount")}
        for c in all_claims
    ]
    iso_result = compute_isolation_forest_scores(claims_with_amounts)
    if iso_result.get("applicable"):
        this_score = iso_result["scores"].get(claim_id)
        if this_score and this_score["is_outlier"]:
            flags.append({
                "type": "isolation_forest_outlier",
                "detail": (
                    f"Claimed amount ({this_amount}) flagged as a multivariate outlier "
                    f"(anomaly_score={this_score['anomaly_score']}) relative to {iso_result['sample_size']} "
                    "claims in the comparison pool."
                ),
                "related_claim_ids": [],
            })

    return flags
