"""When the extract is too old to trust (spec 0232 R6.2).

In season (March to October, New York time: ADR 0134) the daily run is expected every day, and
an extract over 36 hours old (the feeds' threshold, ADR 0050) means the run did not finish.
Out of season nothing is expected, so no age is stale.
"""

from __future__ import annotations

import datetime as dt
import os
from zoneinfo import ZoneInfo

NEW_YORK = ZoneInfo("America/New_York")
STALE_AFTER = dt.timedelta(hours=36)
SEASON_MONTHS = range(3, 11)
NOW_VARIABLE = "FO_DASHBOARD_NOW"


def is_stale(extracted_at: dt.datetime, now: dt.datetime) -> bool:
    """Whether the extract is over 36 hours old and `now` is from March to October in New York.
    Both times must be timezone-aware."""
    return now.astimezone(NEW_YORK).month in SEASON_MONTHS and now - extracted_at > STALE_AFTER


def current_time() -> dt.datetime:
    """The time the page judges staleness by. `FO_DASHBOARD_NOW` (an ISO time with an offset)
    replaces the clock, so the gate can plant an old extract in a fixed month (R7.2)."""
    fixed = os.environ.get(NOW_VARIABLE)
    return dt.datetime.fromisoformat(fixed) if fixed else dt.datetime.now(dt.UTC)
