from typing import Any

import pytest

from brief.chat import ChatClient, ChatError, extract_content


class FakeResp:
    def __init__(self, status: int, body: dict[str, Any]) -> None:
        self.status_code = status
        self.ok = status < 400
        self._body = body
        self.text = str(body)

    def json(self) -> dict[str, Any]:
        return self._body


class FakeSession:
    def __init__(self, responses: list[FakeResp]) -> None:
        self.responses = responses
        self.bodies: list[dict[str, Any]] = []

    def post(self, url: str, **kwargs: Any) -> FakeResp:
        self.bodies.append(kwargs["json"])
        return self.responses.pop(0)


def ok(content: str) -> FakeResp:
    return FakeResp(200, {"choices": [{"message": {"content": content}, "finish_reason": "stop"}]})


def client(session: FakeSession, model: str = "openai/gpt-4.1") -> ChatClient:
    return ChatClient("Test", session, "https://x/chat/completions", "KEY", model, sleep=lambda s: None)  # type: ignore[arg-type]


def test_extract_content() -> None:
    assert extract_content({"choices": [{"message": {"content": "hi"}}]}) == "hi"
    with pytest.raises(ChatError):
        extract_content({"choices": []})
    with pytest.raises(ChatError):
        extract_content({"choices": [{"message": {"content": ""}, "finish_reason": "length"}]})


def test_json_mode_and_reasoning_effort() -> None:
    session = FakeSession([ok("{}"), ok("{}")])
    client(session).generate_json("p")
    client(session, "openai/gpt-oss-120b").generate_json("p")
    assert session.bodies[0]["response_format"] == {"type": "json_object"}
    assert "reasoning_effort" not in session.bodies[0]
    assert session.bodies[1]["reasoning_effort"] == "low"


def test_retries_without_json_mode_when_unsupported() -> None:
    session = FakeSession([FakeResp(400, {"error": {"message": "response_format not supported"}}), ok("{}")])
    assert client(session).generate_json("p") == "{}"
    assert "response_format" not in session.bodies[1]


def test_retries_transient_then_gives_up() -> None:
    session = FakeSession([FakeResp(429, {}), ok("{}")])
    assert client(session).generate_json("p") == "{}"
    session = FakeSession([FakeResp(503, {})] * 3)
    with pytest.raises(ChatError, match="503"):
        client(session).generate_json("p")


def test_client_error_is_not_retried() -> None:
    session = FakeSession([FakeResp(401, {"error": {"message": "bad token"}})])
    with pytest.raises(ChatError, match="401"):
        client(session).generate_json("p")
    assert len(session.bodies) == 1
