"""Provider chain: Gemini first, then GitHub Models and Groq as free fallbacks."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Protocol

import requests

from brief.chat import GITHUB_MODELS_URL, GROQ_URL, ChatClient
from brief.config import Settings
from brief.gemini import BriefOutput, GeminiClient, parse_brief

log = logging.getLogger(__name__)


class JsonGenerator(Protocol):
    model: str

    def generate_json(self, prompt: str) -> str: ...


@dataclass
class Provider:
    """One LLM provider in the chain."""

    name: str
    client: JsonGenerator
    compact: bool  # use the compact prompt (small free-tier request limits)


@dataclass
class BriefResult:
    """Parsed brief plus which provider/model wrote it."""

    output: BriefOutput
    provider: str
    model: str

    @property
    def label(self) -> str:
        return f"{self.provider} ({self.model})"


class AllProvidersFailed(RuntimeError):
    """Every configured provider failed."""


def build_providers(settings: Settings, session: requests.Session) -> list[Provider]:
    """Return configured providers in priority order; unconfigured ones are skipped."""
    providers: list[Provider] = []
    if settings.gemini_api_key:
        providers.append(
            Provider("Gemini", GeminiClient(session, settings.gemini_api_key, settings.gemini_model), compact=False)
        )
    if settings.github_models_token:
        client = ChatClient(
            "GitHub Models",
            session,
            GITHUB_MODELS_URL,
            settings.github_models_token,
            settings.github_models_model,
            extra_headers={"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"},
        )
        providers.append(Provider("GitHub Models", client, compact=True))
    if settings.groq_api_key:
        client = ChatClient("Groq", session, GROQ_URL, settings.groq_api_key, settings.groq_model)
        providers.append(Provider("Groq", client, compact=True))
    return providers


def generate_brief(providers: list[Provider], full_prompt: str, compact_prompt: str) -> BriefResult:
    """Try each provider in order until one returns a parseable brief.

    A provider that answers with invalid JSON is kept as a last resort (its raw text
    can still be sent) but the next provider is tried first.
    """
    errors: list[str] = []
    unparsed: BriefResult | None = None
    for provider in providers:
        prompt = compact_prompt if provider.compact else full_prompt
        log.info("Trying %s (%s), prompt %d chars", provider.name, provider.client.model, len(prompt))
        try:
            text = provider.client.generate_json(prompt)
        except Exception as exc:
            log.warning("%s failed: %s", provider.name, exc)
            errors.append(f"{provider.name}: {exc}")
            continue
        result = BriefResult(parse_brief(text), provider.name, provider.client.model)
        if result.output.parsed:
            return result
        errors.append(f"{provider.name}: invalid JSON")
        unparsed = unparsed or result
    if unparsed:
        log.warning("No provider returned valid JSON; sending raw text from %s", unparsed.label)
        return unparsed
    raise AllProvidersFailed("; ".join(errors) or "no LLM provider configured")
