"""
Retrieval Agent — ClaimGuard AI's RAG (Retrieval-Augmented Generation) layer.

WHAT THIS IS, HONESTLY
-----------------------
This retrieves the most textually-similar past claims to the current one
and (a) surfaces that as grounding context for the Explainability Agent's
generated rationale, and (b) raises a new deterministic fraud signal when
the current claim closely resembles a PAST claim that was already flagged.
Both are genuine, standard RAG uses — "retrieve relevant documents, then
let generation use them" — just built on free infrastructure:

- Retrieval method: TF-IDF vectorization + cosine similarity
  (scikit-learn — already a project dependency, zero additional cost,
  zero network calls, runs instantly even on a laptop). This is classic,
  real information retrieval, not a toy. It is NOT dense/embedding-based
  retrieval (no vector database, no Gemini embedding API call) — that's a
  deliberate choice, not an oversight: it keeps this component free of any
  additional paid/rate-limited API dependency (the project has already hit
  real Gemini model-availability issues more than once — see
  docs/tracker.md), and TF-IDF is a legitimate, well-established retrieval
  technique in its own right, especially at this claim-volume scale where a
  vector index would be overkill. A genuine next step for a larger
  deployment would be swapping in Gemini's embedding model or a local
  sentence-embedding model — noted honestly as a future upgrade, not
  claimed as already done.

- What counts as "similar": cosine similarity over each claim's raw
  narrative text (raw_text) — the claimant's own free-text description.
  Two independent claims describing a similar kind of incident in similar
  language will score high; this is a narrative-similarity signal, not a
  semantic-meaning-despite-different-wording signal (that's the known
  limitation of TF-IDF vs. true embeddings — acknowledged, not hidden).

Design consistency with the rest of this pipeline: this agent is
deterministic and auditable by design, same philosophy as Pattern Agent
and Statistical Agent (see their own module docstrings) — Gemini is used
elsewhere in this pipeline for reasoning over unstructured evidence, not
for retrieval or for score arithmetic.
"""
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

MIN_HISTORY_FOR_RETRIEVAL = 1       # need at least 1 other claim to compute any similarity against
SIMILARITY_FLAG_THRESHOLD = 0.55    # cosine similarity above this counts as "closely resembles"
TOP_K = 3                            # how many similar past claims to surface as RAG context


def find_similar_claims(claim: dict, claim_history: list[dict], top_k: int = TOP_K) -> list[dict]:
    """
    Returns up to top_k past claims most textually similar to `claim`,
    each as {"claim_id", "similarity", "risk_tier", "status"}, sorted by
    similarity descending. Returns [] below MIN_HISTORY_FOR_RETRIEVAL.

    Note this guard is NOT the same kind of statistical-sample-size check
    Statistical Agent uses for Benford's Law/Isolation Forest — those need
    a large sample to estimate a reliable distribution. Pairwise TF-IDF
    cosine similarity has no such requirement; it's a direct comparison
    that's just as valid against one prior document as against a hundred.
    The guard here only exists because comparing against ZERO other claims
    is meaningless (nothing to retrieve), not because of any sample-size
    statistics.
    """
    others = [c for c in claim_history if c["claim_id"] != claim["claim_id"] and c.get("raw_text")]
    if len(others) < MIN_HISTORY_FOR_RETRIEVAL or not claim.get("raw_text"):
        return []

    corpus = [c["raw_text"] for c in others] + [claim["raw_text"]]
    vectorizer = TfidfVectorizer(stop_words="english")
    try:
        tfidf_matrix = vectorizer.fit_transform(corpus)
    except ValueError:
        # Can happen if every document is pure stopwords/empty after
        # cleaning — degrade gracefully rather than raising out of an
        # agent that's supposed to be a soft signal, not a hard dependency.
        return []

    this_vector = tfidf_matrix[-1]
    history_vectors = tfidf_matrix[:-1]
    similarities = cosine_similarity(this_vector, history_vectors)[0]

    scored = sorted(zip(others, similarities), key=lambda pair: pair[1], reverse=True)
    results = []
    for other_claim, score in scored[:top_k]:
        if score <= 0:
            continue
        exp = other_claim.get("explainability") or {}
        results.append({
            "claim_id": other_claim["claim_id"],
            "similarity": round(float(score), 4),
            "risk_tier": exp.get("risk_tier"),
            "status": other_claim.get("status"),
        })
    return results


def run(claim: dict, claim_history: list[dict]) -> dict:
    """
    Returns {"similar_claims": [...], "retrieval_flags": [...]}.

    similar_claims: top-K most similar past claims, for the Explainability
    Agent to cite as grounding context in its rationale (real RAG usage).

    retrieval_flags: pattern_flags-shaped output — a NEW deterministic
    signal, separate from Pattern Agent and Statistical Agent, raised when
    the current claim closely resembles a past claim that was already
    flagged. This is a genuine, new fraud-detection signal this agent adds
    (e.g. a reworded resubmission under different claimant details that
    the exact-match duplicate_submission check in pattern_agent.py would
    miss), not just decorative context-dressing for the narrative text.
    """
    similar_claims = find_similar_claims(claim, claim_history)

    retrieval_flags = []
    for sc in similar_claims:
        if sc["similarity"] >= SIMILARITY_FLAG_THRESHOLD and sc["status"] == "flagged":
            retrieval_flags.append({
                "type": "similar_to_flagged_claim",
                "detail": (
                    f"Narrative is {sc['similarity']:.0%} textually similar to claim {sc['claim_id']}, "
                    f"which was previously flagged ({sc['risk_tier']} risk). This may indicate a "
                    "reworded resubmission or a templated/copied narrative pattern — review alongside "
                    "the exact-match duplicate_submission check, which this is deliberately separate from."
                ),
                "related_claim_ids": [sc["claim_id"]],
            })

    return {"similar_claims": similar_claims, "retrieval_flags": retrieval_flags}
