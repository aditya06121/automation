"""Run state persisted in a secret gist (or a local file for development)."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

import requests

from brief.config import HTTP_TIMEOUT, MAX_SEEN_LINKS

log = logging.getLogger(__name__)

GIST_API = "https://api.github.com/gists/{gist_id}"
STATE_FILE = "state.json"
SUMMARY_FILE = "summary.json"


@dataclass
class State:
    """Links already processed and KEV IDs already known."""

    seen_links: list[str] = field(default_factory=list)
    kev_ids: list[str] = field(default_factory=list)
    last_run: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> State:
        """Build state from parsed JSON, tolerating missing or bad fields."""
        seen = data.get("seen_links")
        kev = data.get("kev_ids")
        seen = seen if isinstance(seen, list) else []
        kev = kev if isinstance(kev, list) else []
        return cls(
            seen_links=[s for s in seen if isinstance(s, str)],
            kev_ids=[k for k in kev if isinstance(k, str)],
            last_run=data.get("last_run") if isinstance(data.get("last_run"), str) else None,
        )

    def to_dict(self) -> dict[str, Any]:
        return {"seen_links": self.seen_links, "kev_ids": self.kev_ids, "last_run": self.last_run}

    @property
    def is_first_run(self) -> bool:
        return not self.kev_ids

    def remember(self, links: list[str], kev_ids: list[str] | None, last_run: str) -> None:
        """Add newly processed links (keeping the most recent N) and update KEV IDs."""
        new = [link for link in dict.fromkeys(links) if link not in set(self.seen_links)]
        self.seen_links = (self.seen_links + new)[-MAX_SEEN_LINKS:]
        if kev_ids is not None:
            self.kev_ids = sorted(set(kev_ids))
        self.last_run = last_run


def _loads(text: str | None) -> dict[str, Any]:
    if not text or not text.strip():
        return {}
    data = json.loads(text)
    return data if isinstance(data, dict) else {}


class Store(Protocol):
    def load(self) -> State: ...

    def save(self, state: State | None, summary: dict[str, Any]) -> None: ...


class GistStore:
    """Reads/writes state.json and summary.json in a GitHub gist."""

    def __init__(self, session: requests.Session, gist_id: str, token: str) -> None:
        self.session = session
        self.url = GIST_API.format(gist_id=gist_id)
        self.headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if token:
            self.headers["Authorization"] = f"Bearer {token}"

    def load(self) -> State:
        resp = self.session.get(self.url, headers=self.headers, timeout=HTTP_TIMEOUT)
        resp.raise_for_status()
        file = resp.json().get("files", {}).get(STATE_FILE) or {}
        content = file.get("content")
        if file.get("truncated") and file.get("raw_url"):
            raw = self.session.get(file["raw_url"], headers=self.headers, timeout=HTTP_TIMEOUT)
            raw.raise_for_status()
            content = raw.text
        return State.from_dict(_loads(content))

    def save(self, state: State | None, summary: dict[str, Any]) -> None:
        files: dict[str, Any] = {SUMMARY_FILE: {"content": json.dumps(summary, indent=2, ensure_ascii=False)}}
        if state is not None:
            files[STATE_FILE] = {"content": json.dumps(state.to_dict(), indent=1)}
        resp = self.session.patch(
            self.url, headers=self.headers, json={"files": files}, timeout=HTTP_TIMEOUT
        )
        resp.raise_for_status()


class LocalStore:
    """Reads/writes state in a local JSON file; summary goes next to it."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.summary_path = path.with_name(path.stem + ".summary.json")

    def load(self) -> State:
        if not self.path.exists():
            return State()
        return State.from_dict(_loads(self.path.read_text(encoding="utf-8")))

    def save(self, state: State | None, summary: dict[str, Any]) -> None:
        self.summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
        if state is not None:
            self.path.write_text(json.dumps(state.to_dict(), indent=1), encoding="utf-8")
