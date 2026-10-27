from datetime import datetime, timezone

import pytest

from brief.cli import filter_new
from brief.cves import extract_cves
from brief.sources import parse_bleepingcomputer, parse_kev, parse_techmeme, techmeme_source
from conftest import NOW


def test_parse_bleepingcomputer(bc_bytes: bytes) -> None:
    items = parse_bleepingcomputer(bc_bytes)
    assert len(items) == 4
    first = items[0]
    assert first.title.startswith("Hackers exploit Acme VPN")
    assert first.link == "https://www.bleepingcomputer.com/news/security/acme-vpn-flaw-exploited/"
    assert first.published == datetime(2026, 10, 26, 14, 0, 10, tzinfo=timezone.utc)
    assert first.categories == ["Security", "Ransomware"]
    assert "Threat actors are exploiting" in first.summary
    assert "<b>" not in items[1].summary


def test_parse_techmeme(tm_bytes: bytes) -> None:
    items = parse_techmeme(tm_bytes)
    assert [i.source_url for i in items] == [
        "https://www.example-news.com/2026/10/26/acme-ai-chip",
        "https://www.wsj.com/tech/big-co-earnings?st=x&ref=y",
        # no external link: fall back to the Techmeme link
        "https://www.techmeme.com/261026/p27#a261026p27",
    ]
    assert items[0].link.startswith("https://www.techmeme.com/")
    assert "3x faster & cheaper" in items[0].snippet
    assert "<" not in items[0].snippet


def test_techmeme_snippet_truncated() -> None:
    _, snippet = techmeme_source("<p>" + "word " * 200 + "</p>")
    assert len(snippet) <= 400
    assert snippet.endswith("…")


def test_parse_kev(kev_data: dict) -> None:
    assert len(parse_kev(kev_data)) == 5
    with pytest.raises(ValueError):
        parse_kev({"vulnerabilities": []})


def test_bad_feed_raises() -> None:
    with pytest.raises(ValueError):
        parse_bleepingcomputer(b"<html>not a feed</html>")


@pytest.mark.parametrize(
    ("texts", "expected"),
    [
        (("CVE-2026-1001 and cve-2026-1002",), ["CVE-2026-1001", "CVE-2026-1002"]),
        (("CVE-2026-1001", "again CVE-2026-1001"), ["CVE-2026-1001"]),
        (("CVE-2026-123456 long id",), ["CVE-2026-123456"]),
        (("CVE-2026-123 too short", None), []),
    ],
)
def test_extract_cves(texts: tuple, expected: list[str]) -> None:
    assert extract_cves(*texts) == expected


def test_filter_new_applies_seen_and_time_window(bc_bytes: bytes) -> None:
    items = parse_bleepingcomputer(bc_bytes)
    seen = {"https://www.bleepingcomputer.com/news/security/widget-cms-rce/"}
    titles = [i.title for i in filter_new(items, seen, NOW)]
    assert "Widget CMS patches critical RCE" not in titles  # seen
    assert "Old story from last week" not in titles  # older than 36h
    assert len(titles) == 2


def test_fulltext_budget_falls_back_to_teasers(bc_bytes: bytes) -> None:
    from brief.fulltext import add_fulltext

    items = parse_bleepingcomputer(bc_bytes)
    add_fulltext(None, items, budget=-1)  # type: ignore[arg-type]  # budget already spent: no fetches
    assert [i.text for i in items] == [i.summary for i in items]
