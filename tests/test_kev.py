from datetime import datetime, timezone

from brief.kev import build_kev_index, diff_new_kev, enrich_items
from brief.sources import parse_bleepingcomputer, parse_kev
from brief.state import State
from conftest import NOW


def test_enrich_items_tags_kev_and_ransomware(bc_bytes: bytes, kev_data: dict) -> None:
    items = parse_bleepingcomputer(bc_bytes)
    for item in items:
        item.text = item.summary
    enrich_items(items, build_kev_index(parse_kev(kev_data)))
    acme, widget, kali, _ = items
    assert acme.cves == ["CVE-2026-1001", "CVE-2026-1002"]
    assert acme.kev_exploited and acme.ransomware
    assert {k["cveID"] for k in acme.kev} == {"CVE-2026-1001", "CVE-2026-1002"}
    assert set(acme.kev[0]) >= {"vendorProject", "dueDate", "knownRansomwareCampaignUse"}
    assert widget.cves == ["CVE-2026-55555"]
    assert not widget.kev_exploited and not widget.ransomware
    assert kali.cves == [] and not kali.kev_exploited


def test_kev_match_without_ransomware(kev_data: dict) -> None:
    from brief.sources import SecurityItem

    item = SecurityItem("Niche HMI bug CVE-2026-2000", "x", None, "", [])
    enrich_items([item], build_kev_index(parse_kev(kev_data)))
    assert item.kev_exploited and not item.ransomware


def test_first_run_only_recent_entries(kev_data: dict) -> None:
    new = diff_new_kev(parse_kev(kev_data), None, NOW)
    # NOW is 2026-10-26; cutoff 2026-10-23 inclusive; newest first
    assert [e["cveID"] for e in new] == ["CVE-2026-1001", "CVE-2026-1002", "CVE-2026-2000"]


def test_later_runs_use_id_diff_not_dates(kev_data: dict) -> None:
    entries = parse_kev(kev_data)
    known = {"CVE-2026-1001", "CVE-2026-1002", "CVE-2026-2000", "CVE-2021-44228"}
    # CVE-2025-3000 is old by date but was never seen: it counts as new
    later = datetime(2026, 12, 1, tzinfo=timezone.utc)
    assert [e["cveID"] for e in diff_new_kev(entries, known, later)] == ["CVE-2025-3000"]
    assert diff_new_kev(entries, {e["cveID"] for e in entries}, later) == []


def test_state_remember_trims_and_keeps_kev_ids() -> None:
    state = State(seen_links=[f"l{i}" for i in range(995)], kev_ids=["CVE-1"])
    state.remember([f"n{i}" for i in range(10)] + ["l5", "n0"], None, "2026-10-26T18:30:00")
    assert len(state.seen_links) == 1000
    assert state.seen_links[-1] == "n9" and "l0" not in state.seen_links
    assert state.kev_ids == ["CVE-1"]  # KEV fetch failed -> keep previous IDs
    state.remember([], ["CVE-2", "CVE-1"], "x")
    assert state.kev_ids == ["CVE-1", "CVE-2"]


def test_state_from_bad_dict() -> None:
    state = State.from_dict({"seen_links": "oops", "kev_ids": [1, "CVE-1"]})
    assert state.seen_links == []
    assert state.kev_ids == ["CVE-1"]
    assert state.is_first_run is False
    assert State.from_dict({}).is_first_run
