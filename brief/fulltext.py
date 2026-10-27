"""Full-text article extraction for BleepingComputer stories."""

from __future__ import annotations

import logging
import time

import requests
import trafilatura

from brief.config import FULLTEXT_BUDGET, FULLTEXT_MAX_CHARS, HTTP_TIMEOUT
from brief.sources import SecurityItem

log = logging.getLogger(__name__)


def fetch_article_text(session: requests.Session, url: str) -> str | None:
    """Download an article and return its main text (capped), or None on failure."""
    try:
        resp = session.get(url, timeout=HTTP_TIMEOUT)
        resp.raise_for_status()
        text = trafilatura.extract(resp.text, url=url, include_comments=False, include_tables=False)
    except Exception as exc:  # one bad article must never stop the run
        log.warning("Full-text fetch failed for %s: %s", url, exc)
        return None
    if not text or not text.strip():
        log.warning("No text extracted from %s", url)
        return None
    return text.strip()[:FULLTEXT_MAX_CHARS]


def add_fulltext(
    session: requests.Session, items: list[SecurityItem], budget: float = FULLTEXT_BUDGET
) -> None:
    """Fill item.text for each item, falling back to the RSS teaser (also once the time budget is spent)."""
    deadline = time.monotonic() + budget
    for i, item in enumerate(items, 1):
        if time.monotonic() > deadline:
            log.warning("Full-text budget of %ss used up; using RSS teasers for the remaining %d items",
                        budget, len(items) - i + 1)
            for rest in items[i - 1:]:
                rest.text = rest.summary
            return
        text = fetch_article_text(session, item.link)
        log.info("  [%d/%d] %s: %s", i, len(items), "ok" if text else "teaser", item.title[:70])
        item.text = text or item.summary
