"""Shared HTTP session with a browser User-Agent."""

from __future__ import annotations

import requests

from brief.config import USER_AGENT


def make_session() -> requests.Session:
    """Return a requests session that sends a normal browser User-Agent."""
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }
    )
    return session
