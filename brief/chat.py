"""OpenAI-compatible chat-completions client, used for the GitHub Models and Groq fallbacks."""

from __future__ import annotations

import logging
import time
from typing import Any, Callable

import requests

from brief.http import post_with_deadline

log = logging.getLogger(__name__)

GITHUB_MODELS_URL = "https://models.github.ai/inference/chat/completions"
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

REQUEST_TIMEOUT = 75
TOTAL_BUDGET = 90
MIN_ATTEMPT_SECONDS = 15
MAX_RETRIES = 2
MAX_OUTPUT_TOKENS = 4000  # GitHub Models' free tier caps output at 4k tokens


class ChatError(RuntimeError):
    """The provider could not produce a response."""


def extract_content(response: dict[str, Any]) -> str:
    """Return the assistant message text from a chat-completions response."""
    choices = response.get("choices") or []
    if not choices:
        raise ChatError(f"no choices in response: {str(response)[:200]}")
    content = (choices[0].get("message") or {}).get("content") or ""
    if not content.strip():
        raise ChatError(f"empty content (finish_reason={choices[0].get('finish_reason')})")
    return content


class ChatClient:
    """Minimal OpenAI-compatible client with retries, JSON mode and a hard time budget."""

    def __init__(
        self,
        name: str,
        session: requests.Session,
        url: str,
        api_key: str,
        model: str,
        extra_headers: dict[str, str] | None = None,
        sleep: Callable[[float], None] = time.sleep,
        request_timeout: float = REQUEST_TIMEOUT,
        total_budget: float = TOTAL_BUDGET,
    ) -> None:
        self.name = name
        self.session = session
        self.url = url
        self.model = model
        self.headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        self.headers.update(extra_headers or {})
        self.sleep = sleep
        self.request_timeout = request_timeout
        self.total_budget = total_budget

    def _body(self, prompt: str, json_mode: bool) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.3,
            "max_tokens": MAX_OUTPUT_TOKENS,
        }
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        if "gpt-oss" in self.model:
            # reasoning tokens count against output and free-tier token limits
            body["reasoning_effort"] = "low"
        return body

    def generate_json(self, prompt: str) -> str:
        """Generate JSON text for the prompt, retrying transient errors within the time budget."""
        deadline = time.monotonic() + self.total_budget
        json_mode = True
        error = "no attempt made"
        for attempt in range(MAX_RETRIES + 1):
            remaining = deadline - time.monotonic()
            if remaining < MIN_ATTEMPT_SECONDS:
                raise ChatError(f"time budget of {self.total_budget:.0f}s used up: {error}")
            try:
                resp = post_with_deadline(
                    self.session,
                    self.url,
                    min(self.request_timeout, remaining),
                    headers=self.headers,
                    json=self._body(prompt, json_mode),
                )
            except requests.RequestException as exc:
                error = f"network error: {exc.__class__.__name__}"
            else:
                if resp.ok:
                    return extract_content(resp.json())
                message = _error_message(resp)
                error = f"HTTP {resp.status_code}: {message}"
                if resp.status_code == 400 and json_mode and "response_format" in message.lower():
                    log.warning("%s: model rejected JSON mode; retrying without it", self.name)
                    json_mode = False
                    continue
                if resp.status_code != 429 and resp.status_code < 500:
                    raise ChatError(error)
            if attempt == MAX_RETRIES:
                break
            delay = min(5 * 2**attempt, max(deadline - time.monotonic() - MIN_ATTEMPT_SECONDS, 0))
            log.warning("%s transient error (%s); retrying in %.0fs", self.name, error, delay)
            self.sleep(delay)
        raise ChatError(f"gave up after {MAX_RETRIES} retries: {error}")


def _error_message(resp: requests.Response) -> str:
    try:
        err = resp.json().get("error", {})
        return str(err.get("message", err) if isinstance(err, dict) else err)[:300]
    except (ValueError, AttributeError):
        return resp.text[:300]
