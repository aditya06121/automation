"""Command-line entrypoint and run orchestration."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, TypeVar

import requests
from dotenv import load_dotenv

from brief import config
from brief.config import IST, MAX_NEW_KEV, MAX_TECH_NEWS, NEWS_MAX_AGE, Settings
from brief.fulltext import add_fulltext
from brief.gemini import GeminiClient, GeminiError, parse_brief
from brief.http import make_session
from brief.kev import build_kev_index, compact_entry, diff_new_kev, enrich_items
from brief.sources import (
    SecurityItem,
    TechItem,
    fetch_bleepingcomputer,
    fetch_kev,
    fetch_techmeme,
)
from brief.state import GistStore, LocalStore, State, Store
from brief.summary import QUIET_LOCKSCREEN, build_summary
from brief.telegram import TelegramClient

log = logging.getLogger("brief")

T = TypeVar("T")


class FatalError(RuntimeError):
    """An error that aborts the run (alert + error summary + non-zero exit)."""


@dataclass
class Collected:
    """Everything fetched for one run."""

    security: list[SecurityItem] = field(default_factory=list)
    tech: list[TechItem] = field(default_factory=list)
    kev_entries: list[dict[str, str]] | None = None
    failed: list[str] = field(default_factory=list)


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Daily tech & security news brief")
    parser.add_argument("--dry-run", action="store_true", help="don't send Telegram or write state; print output")
    parser.add_argument("--no-fulltext", action="store_true", help="skip fetching full article text")
    parser.add_argument("--local-state", type=Path, help="use a local state file instead of the gist")
    return parser.parse_args(argv)


def _try_fetch(name: str, fetch: Callable[[], T], collected: Collected) -> T | None:
    """Run one source fetch, recording failure instead of raising."""
    try:
        result = fetch()
    except Exception as exc:
        log.error("Source %s failed: %s", name, exc)
        collected.failed.append(name)
        return None
    log.info("Source %s: %d items", name, len(result))  # type: ignore[arg-type]
    return result


def is_fresh(published: datetime | None, now: datetime) -> bool:
    """True if the item is inside the news time window (undated items are kept)."""
    return published is None or published >= now - NEWS_MAX_AGE


def filter_new(items: list[Any], seen: set[str], now: datetime) -> list[Any]:
    """Keep items not seen before and published within the time window."""
    return [i for i in items if i.link not in seen and is_fresh(i.published, now)]


def build_payload(
    security: list[SecurityItem], new_kev: list[dict[str, str]], tech: list[TechItem]
) -> dict[str, Any]:
    """Compact JSON input for Gemini."""
    return {
        "security_news": [
            {
                "title": i.title,
                "link": i.link,
                "published": i.published.isoformat() if i.published else None,
                "categories": i.categories,
                "text": i.text or i.summary,
                "cves": i.cves,
                "kev_exploited": i.kev_exploited,
                "ransomware": i.ransomware,
                "kev": i.kev,
            }
            for i in security
        ],
        "new_kev": [compact_entry(e) for e in new_kev],
        "tech_news": [{"title": t.title, "source_url": t.source_url, "snippet": t.snippet} for t in tech],
    }


def build_prompt(payload: dict[str, Any], now: datetime) -> str:
    template = config.PROMPT_PATH.read_text(encoding="utf-8")
    template = template.replace("{{DATE_IST}}", now.astimezone(IST).strftime("%A %d %B %Y"))
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return f"{template.rstrip()}\n\nINPUT DATA (JSON):\n{data}\n"


def header(now: datetime) -> str:
    d = now.astimezone(IST)
    return f"<b>📰 Tech &amp; Security Brief — {d:%a} {d.day} {d:%b %Y}</b>"


def failed_note(failed: list[str]) -> str:
    if not failed:
        return ""
    return f"\n\n<i>Note: could not fetch {', '.join(failed)} this run.</i>"


class Runner:
    """Executes one brief run."""

    def __init__(
        self,
        settings: Settings,
        session: requests.Session,
        store: Store,
        telegram: TelegramClient | None,
        now: datetime,
    ) -> None:
        self.settings = settings
        self.session = session
        self.store = store
        self.telegram = telegram
        self.now = now

    def collect(self) -> Collected:
        log.info("Step 2/6: fetching sources")
        c = Collected()
        c.security = _try_fetch("BleepingComputer", lambda: fetch_bleepingcomputer(self.session), c) or []
        c.tech = _try_fetch("Techmeme", lambda: fetch_techmeme(self.session), c) or []
        c.kev_entries = _try_fetch("CISA KEV", lambda: fetch_kev(self.session), c)
        if len(c.failed) == 3:
            raise FatalError("All sources failed: " + ", ".join(c.failed))
        return c

    def run(self) -> int:
        log.info("Step 1/6: loading state from %s", "local file" if self.settings.local_state else "gist")
        try:
            state = self.store.load()
        except Exception as exc:
            raise FatalError(f"Could not load state: {exc}") from exc
        log.info(
            "State: %d seen links, %d KEV IDs, last run %s",
            len(state.seen_links), len(state.kev_ids), state.last_run or "never",
        )

        c = self.collect()

        log.info("Step 3/6: filtering new items")
        seen = set(state.seen_links)
        security = filter_new(c.security, seen, self.now)
        tech = sorted(
            filter_new(c.tech, seen, self.now),
            key=lambda t: t.published or self.now,
            reverse=True,
        )[:MAX_TECH_NEWS]
        new_kev: list[dict[str, str]] = []
        kev_ids: list[str] | None = None
        if c.kev_entries is not None:
            kev_ids = [e["cveID"].strip().upper() for e in c.kev_entries]
            new_kev = diff_new_kev(c.kev_entries, set(state.kev_ids) or None, self.now)
            if state.is_first_run:
                log.info("First run: treating KEV entries from the last 3 days as new")
        log.info(
            "New: %d security, %d tech, %d KEV (sending %d)",
            len(security), len(tech), len(new_kev), min(len(new_kev), MAX_NEW_KEV),
        )
        new_kev = new_kev[:MAX_NEW_KEV]

        log.info("Step 4/6: enriching security stories")
        if security and not self.settings.no_fulltext:
            add_fulltext(self.session, security)
        else:
            for item in security:
                item.text = item.summary
        enrich_items(security, build_kev_index(c.kev_entries or []))
        exploited = sum(1 for i in security if i.kev_exploited)
        log.info("%d stories reference actively exploited (KEV) CVEs", exploited)

        processed_links = [i.link for i in security] + [t.link for t in tech]

        if not (security or tech or new_kev):
            log.info("Step 5/6: nothing new; sending quiet-night message")
            message = f"{header(self.now)}\n\n🌙 Quiet night, nothing new since the last brief.{failed_note(c.failed)}"
            summary = build_summary(self.now, QUIET_LOCKSCREEN)
        else:
            log.info("Step 5/6: generating brief with Gemini (%s)", self.settings.gemini_model)
            prompt = build_prompt(build_payload(security, new_kev, tech), self.now)
            log.info("Prompt size: %d chars", len(prompt))
            gemini = GeminiClient(self.session, self.settings.gemini_api_key, self.settings.gemini_model)
            try:
                output = parse_brief(gemini.generate_json(prompt))
            except (GeminiError, requests.RequestException) as exc:
                raise FatalError(f"Gemini failed: {exc}") from exc
            log.info("Gemini model %s produced %d chars (parsed=%s)", gemini.model, len(output.telegram), output.parsed)
            message = f"{header(self.now)}\n\n{output.telegram}{failed_note(c.failed)}"
            summary = build_summary(
                self.now,
                output.lockscreen,
                new_kev_count=len(new_kev),
                exploited_in_news_count=exploited,
            )

        state.remember(processed_links, kev_ids, self.now.isoformat(timespec="seconds"))
        return self.deliver(message, summary, state)

    def deliver(self, message: str, summary: dict[str, Any], state: State) -> int:
        if self.settings.dry_run:
            log.info("Step 6/6: dry run, printing output (nothing sent or saved)")
            print("\n========== TELEGRAM ==========\n" + message)
            print("\n========== summary.json ==========\n" + json.dumps(summary, indent=2, ensure_ascii=False))
            return 0
        assert self.telegram is not None
        log.info("Step 6/6: sending Telegram message and saving state")
        self.telegram.send_html(message)
        self.store.save(state, summary)
        log.info("Done: state and summary saved")
        return 0

    def fail(self, error: str) -> None:
        """Best-effort alert and error summary; never raises."""
        log.error("Run failed: %s", error)
        summary = build_summary(self.now, f"⚠️ Brief failed: {error[:150]}", error=error)
        if self.settings.dry_run:
            print("\n========== summary.json (error) ==========\n" + json.dumps(summary, indent=2, ensure_ascii=False))
            return
        if self.telegram is not None:
            try:
                self.telegram.send_plain(f"⚠️ Tech & Security Brief failed\n\n{error[:3500]}")
            except Exception as exc:
                log.error("Could not send Telegram alert: %s", exc)
        try:
            self.store.save(None, summary)
        except Exception as exc:
            log.error("Could not write error summary: %s", exc)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    load_dotenv()
    logging.basicConfig(
        stream=sys.stdout,
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
    )
    for noisy in ("urllib3", "trafilatura", "htmldate", "charset_normalizer"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    settings = Settings.from_env(args.dry_run, args.no_fulltext, args.local_state)
    if missing := settings.missing():
        log.error("Missing required environment variables: %s", ", ".join(missing))
        return 2

    session = make_session()
    store: Store = (
        LocalStore(settings.local_state)
        if settings.local_state
        else GistStore(session, settings.gist_id, settings.gist_token)
    )
    telegram = (
        None
        if settings.dry_run
        else TelegramClient(session, settings.telegram_token, settings.telegram_chat_id)
    )
    runner = Runner(settings, session, store, telegram, datetime.now(timezone.utc))
    log.info("Tech & Security Brief starting (dry_run=%s, fulltext=%s)", settings.dry_run, not settings.no_fulltext)
    try:
        return runner.run()
    except FatalError as exc:
        runner.fail(str(exc))
    except Exception as exc:
        log.exception("Unexpected error")
        runner.fail(f"{exc.__class__.__name__}: {exc}")
    return 1
