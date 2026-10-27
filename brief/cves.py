"""CVE ID extraction."""

from __future__ import annotations

import re

CVE_RE = re.compile(r"CVE-\d{4}-\d{4,}", re.IGNORECASE)


def extract_cves(*texts: str | None) -> list[str]:
    """Return unique uppercase CVE IDs found in the texts, in first-seen order."""
    seen: dict[str, None] = {}
    for text in texts:
        for match in CVE_RE.findall(text or ""):
            seen.setdefault(match.upper(), None)
    return list(seen)
