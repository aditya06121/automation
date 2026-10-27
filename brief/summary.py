"""summary.json written to the gist for the lockscreen wallpaper flow."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from brief.config import IST

QUIET_LOCKSCREEN = "Quiet night: no new tech or security stories and no new CISA KEV entries since the last brief."


def build_summary(
    now: datetime,
    lockscreen: str,
    new_kev_count: int = 0,
    exploited_in_news_count: int = 0,
    error: str | None = None,
    generated_by: str | None = None,
) -> dict[str, Any]:
    """Return the summary.json payload."""
    summary: dict[str, Any] = {
        "generated_at": now.astimezone(IST).isoformat(timespec="seconds"),
        "date_ist": now.astimezone(IST).strftime("%d %b").lstrip("0"),
        "lockscreen": lockscreen,
        "new_kev_count": new_kev_count,
        "exploited_in_news_count": exploited_in_news_count,
        "status": "error" if error else "ok",
    }
    if generated_by:
        summary["generated_by"] = generated_by
    if error:
        summary["error"] = error[:300]
    return summary
