"""CISA KEV lookup, story enrichment and new-entry detection."""

from __future__ import annotations

from datetime import date, datetime
from typing import Iterable

from brief.config import KEV_FIRST_RUN_WINDOW
from brief.cves import extract_cves
from brief.sources import SecurityItem

KEV_FIELDS = (
    "cveID",
    "vendorProject",
    "product",
    "vulnerabilityName",
    "shortDescription",
    "dateAdded",
    "dueDate",
    "requiredAction",
    "knownRansomwareCampaignUse",
)


def compact_entry(entry: dict[str, str]) -> dict[str, str]:
    """Return only the KEV fields we pass on, with the long action text trimmed."""
    out = {k: str(entry.get(k, "")) for k in KEV_FIELDS}
    if len(out["requiredAction"]) > 300:
        out["requiredAction"] = out["requiredAction"][:299].rstrip() + "…"
    return out


def build_kev_index(entries: Iterable[dict[str, str]]) -> dict[str, dict[str, str]]:
    """Map uppercase cveID -> KEV entry."""
    return {e["cveID"].strip().upper(): e for e in entries if e.get("cveID")}


def enrich_items(items: list[SecurityItem], index: dict[str, dict[str, str]]) -> None:
    """Extract CVEs from each item and tag KEV / ransomware matches in place."""
    for item in items:
        item.cves = extract_cves(item.title, item.text or item.summary)
        matches = [index[c] for c in item.cves if c in index]
        item.kev = [compact_entry(m) for m in matches]
        item.kev_exploited = bool(matches)
        item.ransomware = any(
            m.get("knownRansomwareCampaignUse", "").strip().lower() == "known" for m in matches
        )


def _date_added(entry: dict[str, str]) -> date | None:
    try:
        return date.fromisoformat(entry.get("dateAdded", "")[:10])
    except ValueError:
        return None


def diff_new_kev(
    entries: list[dict[str, str]], known_ids: set[str] | None, now: datetime
) -> list[dict[str, str]]:
    """Return KEV entries that are new since the last run, newest first.

    With no previous state (first run), only entries added in the last few days
    count as new. Afterwards the ID diff is authoritative, because CISA can add
    entries dated "yesterday" after our midnight IST run.
    """
    if known_ids:
        new = [e for e in entries if e["cveID"].strip().upper() not in known_ids]
    else:
        cutoff = (now - KEV_FIRST_RUN_WINDOW).date()
        new = [e for e in entries if (d := _date_added(e)) is not None and d >= cutoff]
    return sorted(new, key=lambda e: (e.get("dateAdded", ""), e["cveID"]), reverse=True)
