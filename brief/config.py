"""Configuration: constants, environment variables and CLI options."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import timedelta, timezone
from pathlib import Path

BLEEPINGCOMPUTER_RSS = "https://www.bleepingcomputer.com/feed/"
TECHMEME_RSS = "https://www.techmeme.com/feed.xml"
KEV_JSON = "https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json"

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
)
HTTP_TIMEOUT = 15
FULLTEXT_BUDGET = 90  # seconds for all article downloads; the rest fall back to RSS teasers

# Newer flash models (3.7/3.8, flash-latest) were overloaded or hanging in testing (Oct 2026)
DEFAULT_GEMINI_MODEL = "gemini-2.5-flash"
DEFAULT_GITHUB_MODELS_MODEL = "openai/gpt-4.1"
DEFAULT_GROQ_MODEL = "openai/gpt-oss-120b"  # Groq retired llama-3.3-70b-versatile in Aug 2026

# Fallback providers have small free-tier request limits (GitHub Models: 8k input tokens),
# so they get a compact payload: shorter article text, fewer fields.
COMPACT_PAYLOAD_CHARS = 12000

IST = timezone(timedelta(hours=5, minutes=30), "IST")

NEWS_MAX_AGE = timedelta(hours=36)
KEV_FIRST_RUN_WINDOW = timedelta(days=3)
FULLTEXT_MAX_CHARS = 4000
TECHMEME_SNIPPET_CHARS = 400
MAX_NEW_KEV = 15
MAX_TECH_NEWS = 30
MAX_SEEN_LINKS = 1000

LOCKSCREEN_MAX_POINTS = 8
LOCKSCREEN_POINT_MAX_CHARS = 90

ROOT = Path(__file__).resolve().parent.parent
PROMPT_PATH = ROOT / "prompts" / "brief.txt"


@dataclass(frozen=True)
class Settings:
    """Runtime settings read from the environment and CLI flags."""

    gemini_api_key: str
    gemini_model: str
    telegram_token: str
    telegram_chat_id: str
    gist_token: str
    gist_id: str
    dry_run: bool = False
    no_fulltext: bool = False
    local_state: Path | None = None
    github_models_token: str = ""
    github_models_model: str = DEFAULT_GITHUB_MODELS_MODEL
    groq_api_key: str = ""
    groq_model: str = DEFAULT_GROQ_MODEL

    @classmethod
    def from_env(
        cls, dry_run: bool = False, no_fulltext: bool = False, local_state: Path | None = None
    ) -> Settings:
        """Build settings from environment variables (after optional .env loading)."""
        env = os.environ.get
        return cls(
            gemini_api_key=env("GEMINI_API_KEY", "").strip(),
            gemini_model=env("GEMINI_MODEL", "").strip() or DEFAULT_GEMINI_MODEL,
            telegram_token=env("TELEGRAM_TOKEN", "").strip(),
            telegram_chat_id=env("TELEGRAM_CHAT_ID", "").strip(),
            gist_token=env("GIST_TOKEN", "").strip(),
            gist_id=env("GIST_ID", "").strip(),
            dry_run=dry_run,
            no_fulltext=no_fulltext,
            local_state=local_state,
            github_models_token=env("GITHUB_MODELS_TOKEN", "").strip(),
            github_models_model=env("GITHUB_MODELS_MODEL", "").strip() or DEFAULT_GITHUB_MODELS_MODEL,
            groq_api_key=env("GROQ_API_KEY", "").strip(),
            groq_model=env("GROQ_MODEL", "").strip() or DEFAULT_GROQ_MODEL,
        )

    def missing(self) -> list[str]:
        """Return names of required env vars that are unset for this run mode."""
        required = {
            "GEMINI_API_KEY or GITHUB_MODELS_TOKEN or GROQ_API_KEY": (
                self.gemini_api_key or self.github_models_token or self.groq_api_key
            )
        }
        if not self.dry_run:
            required["TELEGRAM_TOKEN"] = self.telegram_token
            required["TELEGRAM_CHAT_ID"] = self.telegram_chat_id
        if self.local_state is None:
            required["GIST_ID"] = self.gist_id
            if not self.dry_run:
                required["GIST_TOKEN"] = self.gist_token
        return [name for name, value in required.items() if not value]
