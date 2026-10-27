import time
from typing import Any

import pytest

from brief import gemini
from brief.gemini import (
    GENERIC_LOCKSCREEN,
    GeminiClient,
    GeminiError,
    extract_text,
    normalize_lockscreen,
    parse_brief,
    pick_fallback_model,
    strip_fences,
)


def response(*parts: dict[str, Any]) -> dict[str, Any]:
    return {"candidates": [{"content": {"parts": list(parts)}, "finishReason": "STOP"}]}


def test_extract_text_skips_thoughts() -> None:
    resp = response(
        {"text": "thinking about it...", "thought": True},
        {"text": '{"telegram": "a",'},
        {"text": ' "lockscreen": "b"}'},
    )
    assert extract_text(resp) == '{"telegram": "a", "lockscreen": "b"}'


def test_extract_text_errors() -> None:
    with pytest.raises(GeminiError):
        extract_text({"promptFeedback": {"blockReason": "SAFETY"}})
    with pytest.raises(GeminiError):
        extract_text(response({"text": "x", "thought": True}))


@pytest.mark.parametrize(
    "text",
    [
        '```json\n{"telegram": "<b>Hi</b>", "lockscreen": "Para."}\n```',
        '```\n{"telegram": "<b>Hi</b>", "lockscreen": "Para."}\n```',
        '  {"telegram": "<b>Hi</b>", "lockscreen": "Para."}  ',
    ],
)
def test_parse_brief_fenced_and_plain(text: str) -> None:
    out = parse_brief(text)
    assert out.parsed
    assert out.telegram == "<b>Hi</b>"
    assert out.lockscreen == ["Para."]


def test_parse_brief_invalid_json_falls_back_to_raw() -> None:
    out = parse_brief("<b>Not JSON</b> brief text")
    assert not out.parsed
    assert out.telegram == "<b>Not JSON</b> brief text"
    assert out.lockscreen == list(GENERIC_LOCKSCREEN)


def test_parse_brief_missing_key_falls_back() -> None:
    assert not parse_brief('{"lockscreen": "x"}').parsed


def test_strip_fences_noop() -> None:
    assert strip_fences('{"a": 1}') == '{"a": 1}'


def test_normalize_lockscreen_list() -> None:
    raw = ["⚠️ Acme VPN exploited", "  - Big Co earnings ", "", "2. Third point"] + [f"p{i}" for i in range(10)]
    out = normalize_lockscreen(raw)
    assert out[:3] == ["⚠️ Acme VPN exploited", "Big Co earnings", "Third point"]
    assert len(out) == 8


def test_normalize_lockscreen_from_strings() -> None:
    assert normalize_lockscreen("• one\n• two") == ["one", "two"]
    assert normalize_lockscreen("First thing happened. Second thing too. ⚠️ Third.") == [
        "First thing happened.", "Second thing too.", "⚠️ Third."
    ]
    assert normalize_lockscreen("") == list(GENERIC_LOCKSCREEN)
    assert normalize_lockscreen(None) == list(GENERIC_LOCKSCREEN)


def test_normalize_lockscreen_clips_long_points() -> None:
    (point,) = normalize_lockscreen(["word " * 40])
    assert len(point) <= 90 and point.endswith("…")


def test_pick_fallback_model_prefers_stable_newest_full_flash(models_data: dict) -> None:
    assert pick_fallback_model(models_data["models"]) == "gemini-2.5-flash"


def test_pick_fallback_model_excludes_failed_model(models_data: dict) -> None:
    assert pick_fallback_model(models_data["models"], exclude="models/gemini-2.5-flash") == "gemini-2.5-flash-lite"


def test_pick_fallback_model_uses_preview_when_no_stable() -> None:
    models = [
        {"name": "models/gemini-3-flash-preview", "supportedGenerationMethods": ["generateContent"]},
        {"name": "models/gemini-2.5-flash-preview-05-20", "supportedGenerationMethods": ["generateContent"]},
        {"name": "models/gemini-2.5-flash-image", "supportedGenerationMethods": ["generateContent"]},
    ]
    assert pick_fallback_model(models) == "gemini-3-flash-preview"
    assert pick_fallback_model([]) is None


class FakeResp:
    def __init__(self, status: int, body: dict[str, Any]) -> None:
        self.status_code = status
        self.ok = status < 400
        self._body = body
        self.text = str(body)

    def json(self) -> dict[str, Any]:
        return self._body

    def raise_for_status(self) -> None:
        assert self.ok


class FakeGeminiSession:
    def __init__(self, posts: list[FakeResp], models: dict[str, Any]) -> None:
        self.posts = posts
        self.models = models
        self.urls: list[str] = []

    def post(self, url: str, **kwargs: Any) -> FakeResp:
        self.urls.append(url)
        return self.posts.pop(0)

    def get(self, url: str, **kwargs: Any) -> FakeResp:
        return FakeResp(200, self.models)


def test_client_falls_back_on_404(models_data: dict) -> None:
    ok = response({"text": '{"telegram": "t", "lockscreen": "l"}'})
    session = FakeGeminiSession(
        [FakeResp(404, {"error": {"message": "models/gemini-flash-latest is not found"}}), FakeResp(200, ok)],
        models_data,
    )
    client = GeminiClient(session, "KEY", "gemini-flash-latest", sleep=lambda s: None)  # type: ignore[arg-type]
    assert parse_brief(client.generate_json("prompt")).telegram == "t"
    assert client.model == "gemini-2.5-flash"
    assert session.urls[1].endswith("/models/gemini-2.5-flash:generateContent")


def test_client_retries_transient_errors(models_data: dict) -> None:
    ok = response({"text": '{"telegram": "t", "lockscreen": "l"}'})
    session = FakeGeminiSession(
        [FakeResp(429, {}), FakeResp(503, {}), FakeResp(200, ok)], models_data
    )
    sleeps: list[float] = []
    client = GeminiClient(session, "KEY", "m", sleep=sleeps.append)  # type: ignore[arg-type]
    client.generate_json("prompt")
    assert len(sleeps) == 2


def test_client_gives_up_after_retries(models_data: dict) -> None:
    session = FakeGeminiSession([FakeResp(500, {})] * 4, models_data)
    client = GeminiClient(session, "KEY", "m", sleep=lambda s: None)  # type: ignore[arg-type]
    with pytest.raises(GeminiError):
        client.generate_json("prompt")


class HangingSession:
    """A server that accepts the request and never answers in time."""

    def __init__(self) -> None:
        self.calls = 0

    def post(self, url: str, **kwargs: Any) -> FakeResp:
        self.calls += 1
        time.sleep(2)
        return FakeResp(200, response({"text": "{}"}))


def test_hanging_request_hits_hard_timeout() -> None:
    session = HangingSession()
    client = GeminiClient(session, "KEY", "m", sleep=lambda s: None, request_timeout=0.2, total_budget=100)  # type: ignore[arg-type]
    start = time.monotonic()
    with pytest.raises(GeminiError, match="Timeout"):
        client.generate_json("prompt")
    assert session.calls == 4  # first try + 3 retries
    assert time.monotonic() - start < 1.5  # each attempt cut off at ~0.2s, not 2s


def test_total_budget_stops_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gemini, "MIN_ATTEMPT_SECONDS", 0.3)
    session = HangingSession()
    client = GeminiClient(session, "KEY", "m", sleep=lambda s: None, request_timeout=0.2, total_budget=0.45)  # type: ignore[arg-type]
    with pytest.raises(GeminiError, match="time budget"):
        client.generate_json("prompt")
    assert session.calls == 1
