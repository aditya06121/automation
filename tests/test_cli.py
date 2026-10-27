import json
from pathlib import Path
from typing import Any

import pytest

from brief import cli
from brief.config import Settings
from brief.sources import parse_bleepingcomputer, parse_kev, parse_techmeme
from brief.state import LocalStore, State
from conftest import NOW


def settings(tmp_path: Path, dry_run: bool = False) -> Settings:
    return Settings("k", "m", "t", "c", "", "", dry_run=dry_run, no_fulltext=True, local_state=tmp_path / "s.json")


class FakeTelegram:
    def __init__(self) -> None:
        self.html: list[str] = []
        self.plain: list[str] = []

    def send_html(self, text: str) -> None:
        self.html.append(text)

    def send_plain(self, text: str) -> None:
        self.plain.append(text)


@pytest.fixture
def sources(monkeypatch: pytest.MonkeyPatch, bc_bytes: bytes, tm_bytes: bytes, kev_data: dict) -> None:
    monkeypatch.setattr(cli, "fetch_bleepingcomputer", lambda s: parse_bleepingcomputer(bc_bytes))
    monkeypatch.setattr(cli, "fetch_techmeme", lambda s: parse_techmeme(tm_bytes))
    monkeypatch.setattr(cli, "fetch_kev", lambda s: parse_kev(kev_data))


def test_full_run_sends_then_saves_state(tmp_path: Path, sources: None, monkeypatch: pytest.MonkeyPatch) -> None:
    prompts: list[str] = []

    def fake_generate(self: Any, prompt: str) -> str:
        prompts.append(prompt)
        return json.dumps({"telegram": "<b>Brief</b>", "lockscreen": "⚠️ Acme VPN exploited."})

    monkeypatch.setattr(cli.GeminiClient, "generate_json", fake_generate)
    tg = FakeTelegram()
    store = LocalStore(tmp_path / "s.json")
    code = cli.Runner(settings(tmp_path), None, store, tg, NOW).run()  # type: ignore[arg-type]
    assert code == 0
    assert tg.html[0].startswith("<b>📰 Tech &amp; Security Brief — Tue 27 Oct 2026</b>")
    payload = json.loads(prompts[0].split("INPUT DATA (JSON):\n", 1)[1])
    assert len(payload["security_news"]) == 3
    assert payload["security_news"][0]["kev_exploited"] is True
    assert [k["cveID"] for k in payload["new_kev"]] == ["CVE-2026-1001", "CVE-2026-1002", "CVE-2026-2000"]
    assert payload["tech_news"][1]["source_url"].startswith("https://www.wsj.com/")

    state = store.load()
    assert len(state.seen_links) == 6 and len(state.kev_ids) == 5
    summary = json.loads(store.summary_path.read_text())
    assert summary["status"] == "ok" and summary["date_ist"] == "27 Oct"
    assert summary["new_kev_count"] == 3 and summary["exploited_in_news_count"] == 1

    # second run: nothing new -> quiet night
    tg2 = FakeTelegram()
    assert cli.Runner(settings(tmp_path), None, store, tg2, NOW).run() == 0  # type: ignore[arg-type]
    assert "Quiet night" in tg2.html[0]
    assert len(prompts) == 1


def test_partial_source_failure_is_noted(tmp_path: Path, sources: None, monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(s: Any) -> None:
        raise ConnectionError("down")

    monkeypatch.setattr(cli, "fetch_techmeme", boom)
    monkeypatch.setattr(cli.GeminiClient, "generate_json", lambda self, p: '{"telegram": "x", "lockscreen": "y"}')
    tg = FakeTelegram()
    cli.Runner(settings(tmp_path), None, LocalStore(tmp_path / "s.json"), tg, NOW).run()  # type: ignore[arg-type]
    assert "could not fetch Techmeme" in tg.html[0]


def test_all_sources_failing_is_fatal(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(s: Any) -> None:
        raise ConnectionError("down")

    for name in ("fetch_bleepingcomputer", "fetch_techmeme", "fetch_kev"):
        monkeypatch.setattr(cli, name, boom)
    runner = cli.Runner(settings(tmp_path), None, LocalStore(tmp_path / "s.json"), FakeTelegram(), NOW)  # type: ignore[arg-type]
    with pytest.raises(cli.FatalError):
        runner.run()


def test_fail_writes_error_summary_and_alert(tmp_path: Path) -> None:
    store = LocalStore(tmp_path / "s.json")
    store.save(State(seen_links=["a"]), {"status": "ok"})
    tg = FakeTelegram()
    cli.Runner(settings(tmp_path), None, store, tg, NOW).fail("Gemini failed: boom")  # type: ignore[arg-type]
    summary = json.loads(store.summary_path.read_text())
    assert summary["status"] == "error" and "boom" in summary["error"]
    assert "boom" in tg.plain[0]
    assert store.load().seen_links == ["a"]  # state untouched


def test_gemini_failure_does_not_save_state(tmp_path: Path, sources: None, monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(self: Any, prompt: str) -> str:
        raise cli.GeminiError("quota")

    monkeypatch.setattr(cli.GeminiClient, "generate_json", fail)
    store = LocalStore(tmp_path / "s.json")
    with pytest.raises(cli.FatalError):
        cli.Runner(settings(tmp_path), None, store, FakeTelegram(), NOW).run()  # type: ignore[arg-type]
    assert not store.path.exists()


def test_dry_run_prints_and_saves_nothing(tmp_path: Path, sources: None, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
    monkeypatch.setattr(cli.GeminiClient, "generate_json", lambda self, p: '{"telegram": "BRIEF", "lockscreen": "PARA"}')
    store = LocalStore(tmp_path / "s.json")
    assert cli.Runner(settings(tmp_path, dry_run=True), None, store, None, NOW).run() == 0  # type: ignore[arg-type]
    out = capsys.readouterr().out
    assert "BRIEF" in out and '"lockscreen": "PARA"' in out
    assert not store.path.exists() and not store.summary_path.exists()
