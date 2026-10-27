"""Shared HTTP session with a browser User-Agent."""

from __future__ import annotations

import threading
from typing import Any

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


def post_with_deadline(
    session: requests.Session, url: str, timeout: float, **kwargs: Any
) -> requests.Response:
    """POST with a hard wall-clock limit.

    requests' timeout only bounds each socket read, so a server that trickles
    bytes or stalls mid-response can hold a call open far longer. The request
    runs in a daemon thread that we stop waiting for after `timeout` seconds.
    """
    result: dict[str, Any] = {}

    def target() -> None:
        try:
            result["resp"] = session.post(url, timeout=(10, timeout), **kwargs)
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
