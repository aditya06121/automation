"""Fetch and parse BleepingComputer, Techmeme and CISA KEV."""

from __future__ import annotations

import calendar
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

import feedparser
import requests
from bs4 import BeautifulSoup

from brief.config import (
    BLEEPINGCOMPUTER_RSS,
    HTTP_TIMEOUT,
    KEV_JSON,
    TECHMEME_RSS,
    TECHMEME_SNIPPET_CHARS,
)

log = logging.getLogger(__name__)


@dataclass
class SecurityItem:
    """A BleepingComputer story, later enriched with full text and KEV data."""

    title: str
    link: str
    published: datetime | None
    summary: str
    categories: list[str]
    text: str = ""
    cves: list[str] = field(default_factory=list)
    kev_exploited: bool = False
    ransomware: bool = False
    kev: list[dict[str, str]] = field(default_factory=list)


@dataclass
class TechItem:
    """A Techmeme headline with the original publisher link."""

    title: str
    link: str
    source_url: str
    snippet: str
    published: datetime | None


def _published(entry: Any) -> datetime | None:
    """Return the entry's publish time as an aware UTC datetime, if present."""
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    if not parsed:
        return None
    return datetime.fromtimestamp(calendar.timegm(parsed), tz=timezone.utc)


def _html_to_text(html: str) -> str:
    """Strip HTML and collapse whitespace."""
    return " ".join(BeautifulSoup(html or "", "html.parser").get_text(" ").split())


def _truncate(text: str, limit: int) -> str:
    """Truncate text to limit characters, adding an ellipsis if cut."""
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _parse_feed(content: bytes, name: str) -> Any:
    """Parse RSS bytes, raising if the feed is unusable."""
    feed = feedparser.parse(content)
    if not feed.entries:
        raise ValueError(f"{name} feed has no entries (bozo={feed.get('bozo_exception')!r})")
    return feed


def parse_bleepingcomputer(content: bytes) -> list[SecurityItem]:
    """Parse the BleepingComputer RSS feed."""
    items = []
    for entry in _parse_feed(content, "BleepingComputer").entries:
        link = entry.get("link", "").strip()
        if not link:
            continue
        items.append(
            SecurityItem(
                title=entry.get("title", "").strip(),
                link=link,
                published=_published(entry),
                summary=_html_to_text(entry.get("summary", "")),
                categories=[t.get("term", "") for t in entry.get("tags", []) if t.get("term")],
            )
        )
    return items


def techmeme_source(description_html: str) -> tuple[str, str]:
    """Return (original publisher URL, snippet) from a Techmeme item description."""
    soup = BeautifulSoup(description_html or "", "html.parser")
    source_url = ""
    for a in soup.find_all("a", href=True):
        host = (urlparse(a["href"]).hostname or "").lower()
        if host and host != "techmeme.com" and not host.endswith(".techmeme.com"):
            source_url = a["href"]
            break
    snippet = _truncate(" ".join(soup.get_text(" ").split()), TECHMEME_SNIPPET_CHARS)
    return source_url, snippet


def parse_techmeme(content: bytes) -> list[TechItem]:
    """Parse the Techmeme RSS feed."""
    items = []
    for entry in _parse_feed(content, "Techmeme").entries:
        link = entry.get("link", "").strip()
        if not link:
            continue
        source_url, snippet = techmeme_source(entry.get("summary", ""))
        items.append(
            TechItem(
                title=entry.get("title", "").strip(),
                link=link,
                source_url=source_url or link,
                snippet=snippet,
                published=_published(entry),
            )
        )
    return items


def parse_kev(data: dict[str, Any]) -> list[dict[str, str]]:
    """Return the KEV `vulnerabilities` array, validating its shape."""
    vulns = data.get("vulnerabilities")
    if not isinstance(vulns, list) or not vulns:
        raise ValueError("KEV JSON has no vulnerabilities array")
    return [v for v in vulns if isinstance(v, dict) and v.get("cveID")]


def _get(session: requests.Session, url: str) -> requests.Response:
    resp = session.get(url, timeout=HTTP_TIMEOUT)
    resp.raise_for_status()
    return resp


def fetch_bleepingcomputer(session: requests.Session) -> list[SecurityItem]:
    """Fetch and parse BleepingComputer RSS."""
    return parse_bleepingcomputer(_get(session, BLEEPINGCOMPUTER_RSS).content)


def fetch_techmeme(session: requests.Session) -> list[TechItem]:
    """Fetch and parse Techmeme RSS."""
    return parse_techmeme(_get(session, TECHMEME_RSS).content)


def fetch_kev(session: requests.Session) -> list[dict[str, str]]:
    """Fetch and parse the CISA KEV catalog."""
    return parse_kev(_get(session, KEV_JSON).json())
