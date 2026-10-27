"""Shared fixtures. Tests never touch the network."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest
import requests

FIXTURES = Path(__file__).parent / "fixtures"
NOW = datetime(2026, 10, 26, 18, 30, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail loudly if any test tries a real HTTP request."""

    def blocked(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("network access in tests")

    monkeypatch.setattr(requests.Session, "request", blocked)


@pytest.fixture
def bc_bytes() -> bytes:
    return (FIXTURES / "bleepingcomputer.xml").read_bytes()


@pytest.fixture
def tm_bytes() -> bytes:
    return (FIXTURES / "techmeme.xml").read_bytes()


@pytest.fixture
def kev_data() -> dict[str, Any]:
    return json.loads((FIXTURES / "kev.json").read_text())


@pytest.fixture
def models_data() -> dict[str, Any]:
    return json.loads((FIXTURES / "gemini_models.json").read_text())
