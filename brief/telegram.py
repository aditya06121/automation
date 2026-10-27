"""Telegram delivery: HTML-safe message splitting and plain-text fallback."""

from __future__ import annotations

import html
import logging
import re
import time
from typing import Any, Callable

import requests

from brief.config import HTTP_TIMEOUT

log = logging.getLogger(__name__)

API_URL = "https://api.telegram.org/bot{token}/sendMessage"
CHUNK_LIMIT = 3900

_TAG_RE = re.compile(r"<(/?)([a-zA-Z][a-zA-Z0-9-]*)[^>]*>")
_TOKEN_RE = re.compile(r"(<[^>]*>)")
_WORD_RE = re.compile(r"\S+\s*|\s+")
_LINK_RE = re.compile(r"""<a\s[^>]*?href\s*=\s*["']([^"']*)["'][^>]*>(.*?)</a\s*>""", re.I | re.S)


class TelegramError(RuntimeError):
    """Telegram rejected or failed to deliver a message."""


# ---------- splitting ----------


def _apply_tags(stack: list[tuple[str, str]], fragment: str) -> list[tuple[str, str]]:
    """Return the open-tag stack after the tags in fragment."""
    stack = list(stack)
    for match in _TAG_RE.finditer(fragment):
        closing, name = match.group(1), match.group(2).lower()
        if not closing:
            stack.append((name, match.group(0)))
            continue
        for i in range(len(stack) - 1, -1, -1):
            if stack[i][0] == name:
                del stack[i]
                break
    return stack


def _closers(stack: list[tuple[str, str]]) -> str:
    return "".join(f"</{name}>" for name, _ in reversed(stack))


def _openers(stack: list[tuple[str, str]]) -> str:
    return "".join(tag for _, tag in stack)


def _hard_cut(word: str, room: int) -> int:
    """Return a cut position <= room that does not split an HTML entity."""
    cut = max(room, 1)
    amp = word.rfind("&", 0, cut)
    if amp != -1 and ";" not in word[amp:cut] and 0 < amp:
        cut = amp
    return cut


def split_message(text: str, limit: int = CHUNK_LIMIT) -> list[str]:
    """Split Telegram HTML into chunks of at most `limit` chars.

    Prefers line boundaries, never cuts inside a tag or entity, and closes/reopens
    tags that are still open at a chunk boundary so every chunk is valid HTML.
    """
    chunks: list[str] = []
    stack: list[tuple[str, str]] = []
    cur = ""

    def has_content() -> bool:
        return bool(cur.strip()) and cur != _openers(stack)

    def fits(piece: str) -> bool:
        return len(cur) + len(piece) + len(_closers(_apply_tags(stack, piece))) <= limit

    def flush() -> None:
        nonlocal cur
        if has_content():
            chunks.append(cur.rstrip("\n") + _closers(stack))
        cur = _openers(stack)

    def add(piece: str) -> None:
        nonlocal cur, stack
        cur += piece
        stack = _apply_tags(stack, piece)

    lines = text.split("\n")
    for i, line in enumerate(lines):
        piece = line + ("\n" if i < len(lines) - 1 else "")
        if fits(piece):
            add(piece)
            continue
        flush()
        if fits(piece):
            add(piece)
            continue
        # A single line is too long: split it token by token.
        for token in _TOKEN_RE.split(piece):
            if not token:
                continue
            if token.startswith("<"):
                if not fits(token):
                    flush()
                add(token)
                continue
            for word in _WORD_RE.findall(token):
                if not fits(word):
                    flush()
                while not fits(word):
                    room = limit - len(cur) - len(_closers(stack))
                    cut = _hard_cut(word, room)
                    add(word[:cut])
                    flush()
                    word = word[cut:]
                add(word)
    if has_content():
        chunks.append(cur.rstrip("\n") + _closers(stack))
    return chunks


# ---------- plain-text fallback ----------


def html_to_plain(text: str) -> str:
    """Convert Telegram HTML to plain text: links become 'text (url)', tags are dropped."""

    def link(match: re.Match[str]) -> str:
        url, label = match.group(1), re.sub(r"<[^>]+>", "", match.group(2)).strip()
        if not label or html.unescape(label) == html.unescape(url):
            return url
        return f"{label} ({url})"

    text = _LINK_RE.sub(link, text)
    text = re.sub(r"<[^>]+>", "", text)
    return html.unescape(text)


# ---------- sending ----------


class TelegramClient:
    """Sends messages to one chat."""

    def __init__(
        self,
        session: requests.Session,
        token: str,
        chat_id: str,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.session = session
        self.token = token
        self.chat_id = chat_id
        self.sleep = sleep

    def _redact(self, message: str) -> str:
        return message.replace(self.token, "***") if self.token else message

    def _send(self, text: str, html_mode: bool) -> requests.Response:
        payload: dict[str, Any] = {
            "chat_id": self.chat_id,
            "text": text,
            "disable_web_page_preview": True,
        }
        if html_mode:
            payload["parse_mode"] = "HTML"
        for attempt in range(3):
            try:
                resp = self.session.post(
                    API_URL.format(token=self.token), json=payload, timeout=HTTP_TIMEOUT
                )
            except requests.RequestException as exc:
                # exception text can contain the URL, which contains the bot token
                err = self._redact(str(exc))
                if attempt == 2:
                    raise TelegramError(f"network error: {err}") from None
                log.warning("Telegram network error (%s); retrying", err)
                self.sleep(3 * (attempt + 1))
                continue
            if resp.status_code == 429 or resp.status_code >= 500:
                retry_after = _retry_after(resp)
                if attempt == 2:
                    break
                log.warning("Telegram HTTP %s; retrying in %ss", resp.status_code, retry_after)
                self.sleep(retry_after)
                continue
            return resp
        raise TelegramError(f"Telegram HTTP {resp.status_code}: {self._redact(resp.text[:200])}")

    def send_html(self, text: str) -> None:
        """Send long HTML text in chunks; a chunk rejected as bad HTML is resent as plain text."""
        chunks = split_message(text)
        for i, chunk in enumerate(chunks, 1):
            resp = self._send(chunk, html_mode=True)
            if resp.status_code == 400:
                log.warning(
                    "Telegram rejected chunk %d/%d as HTML (%s); resending as plain text",
                    i, len(chunks), self._redact(resp.text[:200]),
                )
                resp = self._send(html_to_plain(chunk), html_mode=False)
            if not resp.ok:
                raise TelegramError(
                    f"chunk {i}/{len(chunks)} failed: HTTP {resp.status_code} {self._redact(resp.text[:200])}"
                )
            log.info("Telegram chunk %d/%d sent (%d chars)", i, len(chunks), len(chunk))

    def send_plain(self, text: str) -> None:
        """Send a short plain-text message (alerts)."""
        resp = self._send(text[:4000], html_mode=False)
        if not resp.ok:
            raise TelegramError(f"HTTP {resp.status_code} {self._redact(resp.text[:200])}")


def _retry_after(resp: requests.Response) -> int:
    try:
        return int(resp.json().get("parameters", {}).get("retry_after", 5))
    except (ValueError, AttributeError):
        return 5
