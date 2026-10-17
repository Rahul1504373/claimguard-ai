"""
Thin wrapper around the Gemini API. Centralizing this makes it trivial to:
  - swap models per agent (see config.py)
  - force structured JSON output
  - fall back to MOCK_MODE when no API key is set, so `pytest` and local
    pipeline testing work with zero cost and zero network calls.
  - retry transient failures and enforce a request timeout (both free —
    tenacity is a lightweight, open-source library, and the timeout uses
    only Python's standard library, not an unverified SDK-internal API)
    rather than letting one flaky or hung call fail the whole claim with
    no second attempt, or block a worker thread indefinitely.
"""
import json
import logging
import concurrent.futures
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from app.config import settings

logger = logging.getLogger("claimguard.gemini_client")

MOCK_MODE = not bool(settings.GEMINI_API_KEY)
GEMINI_REQUEST_TIMEOUT_SECONDS = 30

if MOCK_MODE:
    logger.warning(
        "GEMINI_API_KEY is not set — running in MOCK_MODE. All Gemini-backed "
        "agents will return fixed canned responses regardless of input. "
        "This is expected for local dev/testing and costs $0, but every "
        "claim will look identical until a real key is configured."
    )
else:
    from google import genai
    _client = genai.Client(api_key=settings.GEMINI_API_KEY)
    logger.info("GEMINI_API_KEY is set — making real Gemini API calls.")

# One shared worker thread is enough here: this is only used to enforce a
# timeout on an otherwise-blocking SDK call, not for real parallelism.
_timeout_executor = concurrent.futures.ThreadPoolExecutor(max_workers=4)


class TransientGeminiError(Exception):
    """Raised for failures worth retrying (network hiccup, rate limit, a
    timeout, or malformed JSON on a single attempt) — as opposed to a
    genuine bug in our own prompt construction, which retrying won't fix."""


def _generate_content_with_timeout(model: str, system_prompt: str, user_content: list):
    """Runs the blocking SDK call in a worker thread and enforces a wall-clock
    timeout via concurrent.futures — deliberately not relying on any
    SDK-internal timeout parameter, since that couldn't be verified against
    the installed SDK version without risking a silently wrong setting."""
    future = _timeout_executor.submit(
        _client.models.generate_content,
        model=model,
        contents=[system_prompt, *user_content],
        config={"response_mime_type": "application/json"},
    )
    return future.result(timeout=GEMINI_REQUEST_TIMEOUT_SECONDS)


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=8),
    retry=retry_if_exception_type(TransientGeminiError),
    reraise=True,
)
def _call_with_retry(model: str, system_prompt: str, user_content: list) -> dict:
    try:
        response = _generate_content_with_timeout(model, system_prompt, user_content)
    except concurrent.futures.TimeoutError as e:
        logger.warning(f"Gemini call exceeded {GEMINI_REQUEST_TIMEOUT_SECONDS}s timeout (will retry if attempts remain)")
        raise TransientGeminiError(f"Timed out after {GEMINI_REQUEST_TIMEOUT_SECONDS}s") from e
    except Exception as e:
        # Network errors, rate limits (429), and transient server errors from
        # the SDK all surface as generic exceptions here — treated as
        # transient and worth retrying, per tenacity's config above.
        logger.warning(f"Gemini call failed (will retry if attempts remain): {e}")
        raise TransientGeminiError(str(e)) from e

    try:
        return json.loads(response.text)
    except (json.JSONDecodeError, AttributeError) as e:
        logger.warning(f"Gemini returned non-JSON output (will retry if attempts remain): {e}")
        raise TransientGeminiError(f"Non-JSON output: {e}") from e


def call_gemini_json(model: str, system_prompt: str, user_content: list, mock_response: dict) -> dict:
    """
    user_content: list of parts — strings and/or genai.types.Part (for images/PDFs).
    mock_response: what to return when MOCK_MODE is on (no API key configured) —
        callers pass a realistic canned response so pipeline logic can be
        exercised end-to-end without burning API quota during development.
    """
    if MOCK_MODE:
        return mock_response

    try:
        return _call_with_retry(model, system_prompt, user_content)
    except TransientGeminiError as e:
        # All 3 attempts exhausted — surface as a real failure so the
        # pipeline's own error handling (status="error", logged to
        # agent_trace) takes over, rather than silently returning garbage.
        raise RuntimeError(f"Gemini call failed after 3 attempts: {e}") from e


def load_image_part(file_path: str):
    """Helper to build an image/PDF Part for a Gemini multimodal call."""
    if MOCK_MODE:
        return None
    from google.genai import types
    with open(file_path, "rb") as f:
        data = f.read()
    mime = "application/pdf" if file_path.lower().endswith(".pdf") else "image/jpeg"
    return types.Part.from_bytes(data=data, mime_type=mime)
