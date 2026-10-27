"""Gemini REST client with retry, model fallback and tolerant response parsing."""

from __future__ import annotations

import json
import logging
import re
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable

import requests

from brief.config import LOCKSCREEN_MAX_CHARS

log = logging.getLogger(__name__)

API_BASE = "https://generativelanguage.googleapis.com/v1beta"
REQUEST_TIMEOUT = 90  # hard wall-clock limit per attempt
TOTAL_BUDGET = 300  # all attempts (incl. model fallback) must finish inside the 10-minute job
MIN_ATTEMPT_SECONDS = 20  # don't start an attempt with less time than this left
MAX_RETRIES = 3
EXCLUDED_VARIANTS = ("image", "tts", "live", "embedding", "audio")
UNSTABLE_MARKERS = ("preview", "exp")
GENERIC_LOCKSCREEN = (
    "Today's tech and security brief is in Telegram. "
    "The lockscreen summary could not be generated this time."
)

_FENCE_RE = re.compile(r"^\s*```[a-zA-Z]*\s*\n?(.*?)\n?\s*```\s*$", re.DOTALL)
_VERSION_RE = re.compile(r"gemini-(\d+(?:\.\d+)?)")


class GeminiError(RuntimeError):
    """Gemini could not produce a response."""


class ModelNotFound(GeminiError):
    """The requested model does not exist or does not support generateContent."""


@dataclass
class BriefOutput:
    """Parsed Gemini output."""

    telegram: str
    lockscreen: str
    parsed: bool


# ---------- response parsing ----------


def extract_text(response: dict[str, Any]) -> str:
    """Join the text parts of the first candidate, skipping thought parts."""
    candidates = response.get("candidates") or []
    if not candidates:
        feedback = response.get("promptFeedback", {})
        raise GeminiError(f"Gemini returned no candidates: {feedback}")
    parts = (candidates[0].get("content") or {}).get("parts") or []
    text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
    if not text.strip():
        reason = candidates[0].get("finishReason", "unknown")
        raise GeminiError(f"Gemini returned empty text (finishReason={reason})")
    return text


def strip_fences(text: str) -> str:
    """Remove a surrounding markdown code fence, if any."""
    match = _FENCE_RE.match(text)
    return match.group(1) if match else text.strip()


def normalize_lockscreen(value: Any) -> str:
    """Collapse the lockscreen value into one paragraph, soft-capped at a sentence boundary."""
    if isinstance(value, list):
        value = " ".join(str(v) for v in value)
    text = " ".join(str(value or "").split())
    if not text:
        return GENERIC_LOCKSCREEN
    if len(text) <= LOCKSCREEN_MAX_CHARS:
        return text
    cut = text[:LOCKSCREEN_MAX_CHARS]
    end = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "))
    if end >= LOCKSCREEN_MAX_CHARS // 2:
        return cut[: end + 1]
    return cut[: cut.rfind(" ")].rstrip(",;:") + "…"


def parse_brief(text: str) -> BriefOutput:
    """Parse Gemini's JSON output; fall back to raw text if it is not valid JSON."""
    try:
        data = json.loads(strip_fences(text))
        telegram = data["telegram"]
        if not isinstance(telegram, str) or not telegram.strip():
            raise ValueError("empty telegram field")
    except (ValueError, KeyError, TypeError) as exc:
        log.warning("Could not parse Gemini JSON (%s); using raw text", exc)
        return BriefOutput(telegram=text.strip(), lockscreen=GENERIC_LOCKSCREEN, parsed=False)
    return BriefOutput(
        telegram=telegram.strip(), lockscreen=normalize_lockscreen(data.get("lockscreen")), parsed=True
    )


# ---------- model fallback ----------


def _version(name: str) -> float:
    match = _VERSION_RE.search(name)
    return float(match.group(1)) if match else 0.0


def pick_fallback_model(models: list[dict[str, Any]], exclude: str = "") -> str | None:
    """Pick the newest flash model that supports generateContent, preferring stable releases."""
    exclude = exclude.removeprefix("models/")
    candidates = []
    for model in models:
        name = str(model.get("name", "")).removeprefix("models/")
        lower = name.lower()
        if "flash" not in lower or name == exclude:
            continue
        if "generateContent" not in (model.get("supportedGenerationMethods") or []):
            continue
        if any(v in lower for v in EXCLUDED_VARIANTS):
            continue
        stable = not any(m in lower for m in UNSTABLE_MARKERS)
        # stable first, then newest version, then full flash over flash-lite, then shorter name
        candidates.append(((stable, _version(lower), "lite" not in lower, -len(name)), name))
    if not candidates:
        return None
    return max(candidates)[1]


# ---------- client ----------


class GeminiClient:
    """Minimal Gemini REST client."""

    def __init__(
        self,
        session: requests.Session,
        api_key: str,
        model: str,
        sleep: Callable[[float], None] = time.sleep,
        request_timeout: float = REQUEST_TIMEOUT,
        total_budget: float = TOTAL_BUDGET,
    ) -> None:
        self.session = session
        self.api_key = api_key
        self.model = model.removeprefix("models/")
        self.sleep = sleep
        self.request_timeout = request_timeout
        self.total_budget = total_budget
        self._deadline = time.monotonic() + total_budget

    @property
    def _headers(self) -> dict[str, str]:
        return {"x-goog-api-key": self.api_key, "Content-Type": "application/json"}

    def _remaining(self) -> float:
        return self._deadline - time.monotonic()

    def _post_once(self, url: str, body: dict[str, Any], timeout: float) -> requests.Response:
        """POST with a hard wall-clock limit.

        requests' timeout only bounds each socket read, so a server that trickles
        bytes or stalls mid-response can hold a call open far longer. The request
        runs in a daemon thread that we stop waiting for after `timeout` seconds.
        """
        result: dict[str, Any] = {}

        def target() -> None:
            try:
                result["resp"] = self.session.post(
                    url, headers=self._headers, json=body, timeout=(10, timeout)
                )
            except BaseException as exc:
                result["exc"] = exc

        thread = threading.Thread(target=target, daemon=True)
        thread.start()
        thread.join(timeout)
        if thread.is_alive():
            raise requests.Timeout(f"no response within {timeout:.0f}s")
        if "exc" in result:
            raise result["exc"]
        return result["resp"]

    def _post(self, model: str, body: dict[str, Any]) -> dict[str, Any]:
        """POST generateContent with retries on transient errors, within the total budget."""
        url = f"{API_BASE}/models/{model}:generateContent"
        error = "no attempt made"
        for attempt in range(MAX_RETRIES + 1):
            remaining = self._remaining()
            if remaining < MIN_ATTEMPT_SECONDS:
                raise GeminiError(
                    f"time budget of {self.total_budget:.0f}s used up after {attempt} attempt(s): {error}"
                )
            try:
                resp = self._post_once(url, body, min(self.request_timeout, remaining))
            except requests.RequestException as exc:
                error = f"network error: {exc.__class__.__name__}"
            else:
                if resp.ok:
                    return resp.json()
                message = _error_message(resp)
                if _is_model_not_found(resp.status_code, message):
                    raise ModelNotFound(f"{model}: HTTP {resp.status_code} {message}")
                if resp.status_code != 429 and resp.status_code < 500:
                    raise GeminiError(f"HTTP {resp.status_code}: {message}")
                error = f"HTTP {resp.status_code}: {message}"
            if attempt == MAX_RETRIES:
                raise GeminiError(f"gave up after {MAX_RETRIES} retries: {error}")
            delay = min(5 * 2**attempt, max(self._remaining() - MIN_ATTEMPT_SECONDS, 0))
            log.warning("Gemini transient error (%s); retrying in %.0fs", error, delay)
            self.sleep(delay)
        raise AssertionError("unreachable")

    def list_models(self) -> list[dict[str, Any]]:
        """Return all models visible to this API key."""
        models: list[dict[str, Any]] = []
        params: dict[str, Any] = {"pageSize": 1000}
        while True:
            resp = self.session.get(f"{API_BASE}/models", headers=self._headers, params=params, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            models.extend(data.get("models", []))
            token = data.get("nextPageToken")
            if not token:
                return models
            params["pageToken"] = token

    def generate_json(self, prompt: str) -> str:
        """Generate JSON text for the prompt, falling back to another flash model once."""
        body = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"responseMimeType": "application/json", "temperature": 0.3},
        }
        self._deadline = time.monotonic() + self.total_budget
        try:
            return extract_text(self._post(self.model, body))
        except ModelNotFound as exc:
            log.warning("Model unavailable (%s); looking for a fallback flash model", exc)
            fallback = pick_fallback_model(self.list_models(), exclude=self.model)
            if not fallback:
                raise GeminiError("No fallback flash model available") from exc
            log.info("Falling back to Gemini model %s", fallback)
            self.model = fallback
            return extract_text(self._post(fallback, body))


def _error_message(resp: requests.Response) -> str:
    try:
        return str(resp.json().get("error", {}).get("message", ""))[:300]
    except ValueError:
        return resp.text[:300]


def _is_model_not_found(status: int, message: str) -> bool:
    lower = message.lower()
    return status == 404 or (
        status == 400 and "model" in lower and ("not found" in lower or "not supported" in lower)
    )
