import re
from typing import Any

import pytest

from brief.telegram import TelegramClient, html_to_plain, split_message

TAG_RE = re.compile(r"<(/?)([a-z]+)[^>]*>")


def assert_valid_html(chunk: str) -> None:
    """No partial tags and every opened tag is closed in the same chunk."""
    assert chunk.count("<") == chunk.count(">")
    assert re.search(r"<[^>]*$", chunk) is None
    assert re.search(r"&[a-z#0-9]*$", chunk) is None
    stack: list[str] = []
    for closing, name in TAG_RE.findall(chunk):
        if closing:
            assert stack and stack[-1] == name, chunk
            stack.pop()
        else:
            stack.append(name)
    assert stack == [], chunk


def sample_brief(n: int) -> str:
    lines = []
    for i in range(n):
        lines.append(f"<b>Story {i}: something &amp; more</b>")
        lines.append(
            f"Details about story {i} with <code>CVE-2026-{1000 + i}</code> and "
            f'<a href="https://example.com/{i}?a=1&amp;b=2">Read more</a>'
        )
        lines.append("")
    return "\n".join(lines)


def test_short_message_single_chunk() -> None:
    assert split_message("<b>hi</b>\nthere") == ["<b>hi</b>\nthere"]


def test_split_on_line_boundaries_reassembles() -> None:
    text = sample_brief(200)
    chunks = split_message(text)
    assert len(chunks) > 1
    for chunk in chunks:
        assert len(chunk) <= 3900
        assert_valid_html(chunk)
    # every non-empty line survives intact and in order (only blank lines at cuts are dropped)
    rejoined = [line for line in "\n".join(chunks).split("\n") if line]
    assert rejoined == [line for line in text.split("\n") if line]


def test_tag_spanning_lines_is_closed_and_reopened() -> None:
    text = "<i>" + "\n".join(f"line {i} " + "x" * 50 for i in range(200)) + "</i>"
    chunks = split_message(text, limit=1000)
    assert len(chunks) > 1
    for chunk in chunks:
        assert len(chunk) <= 1000
        assert_valid_html(chunk)
        assert chunk.startswith("<i>") and chunk.endswith("</i>")


def test_very_long_single_line_splits_outside_tags() -> None:
    line = " ".join(f'<a href="https://e.com/{i}">link {i}</a> &amp; text' for i in range(400))
    chunks = split_message(line, limit=500)
    assert len(chunks) > 1
    for chunk in chunks:
        assert len(chunk) <= 500
        assert_valid_html(chunk)
    plain = "".join(html_to_plain(c) for c in chunks)
    for i in (0, 199, 399):
        assert f"link {i}" in plain


def test_giant_word_is_hard_split_without_breaking_entities() -> None:
    chunks = split_message("&amp;" * 300, limit=100)
    for chunk in chunks:
        assert len(chunk) <= 100
        assert_valid_html(chunk)
    assert "".join(chunks) == "&amp;" * 300


def test_html_to_plain() -> None:
    html = (
        '<b>Bold</b> &amp; <i>it</i> <code>CVE-1</code> '
        '<a href="https://x.com/a?b=1&amp;c=2">Read more</a> '
        "<a href='https://y.com'>https://y.com</a> 1 &lt; 2"
    )
    assert html_to_plain(html) == (
        "Bold & it CVE-1 Read more (https://x.com/a?b=1&c=2) https://y.com 1 < 2"
    )


class FakeResponse:
    def __init__(self, status: int, body: dict[str, Any] | None = None) -> None:
        self.status_code = status
        self.ok = status < 400
        self._body = body or {}
        self.text = str(self._body)

    def json(self) -> dict[str, Any]:
        return self._body


class FakeSession:
    def __init__(self, statuses: list[int]) -> None:
        self.statuses = statuses
        self.calls: list[dict[str, Any]] = []

    def post(self, url: str, json: dict[str, Any], timeout: int) -> FakeResponse:
        self.calls.append(json)
        return FakeResponse(self.statuses.pop(0), {"description": "Bad Request: can't parse entities"})


def test_bad_html_chunk_resent_as_plain_text() -> None:
    session = FakeSession([400, 200])
    client = TelegramClient(session, "TOKEN", "123", sleep=lambda s: None)  # type: ignore[arg-type]
    client.send_html('<b>Hi</b> <a href="https://x.com">x</a> &amp;')
    first, second = session.calls
    assert first["parse_mode"] == "HTML"
    assert "parse_mode" not in second
    assert second["text"] == "Hi x (https://x.com) &"


def test_send_failure_redacts_token() -> None:
    session = FakeSession([403])
    client = TelegramClient(session, "SECRETTOKEN", "123", sleep=lambda s: None)  # type: ignore[arg-type]
    with pytest.raises(Exception) as exc:
        client.send_plain("hi")
    assert "SECRETTOKEN" not in str(exc.value)
