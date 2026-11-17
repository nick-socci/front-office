"""Which season a run fetches, and whether its matchup days are due (ADR 0130).

Why this module reads the landing zone: `espn_matchup_days` must be skipped, without a
request, while the season is running, because the matchup days of a scoring period that has
not happened do not exist. ESPN's settings capture says where the season stands: once
`latestScoringPeriod` is past `finalScoringPeriod` the season is over (design.md, C3).

The read goes through `LandingZone`, the only way the repository allows to read the landing
zone (AGENTS.md), and nothing is written. It does not take the league id from the credentials
(the orchestration reads no credential file, R2.4): it finds the season's settings captures by
their sidecars, and refuses to choose between two leagues.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from front_office.landing import Capture, LandingZone

NEW_YORK = ZoneInfo("America/New_York")


class AmbiguousLeague(Exception):
    """The season has settings captures of more than one league; a run has one league."""


def current(*, now: datetime | None = None, environ: Mapping[str, str] | None = None) -> int:
    """`FO_SEASON` if set, else the calendar year in New York (R3.1)."""
    env = os.environ if environ is None else environ
    named = env.get("FO_SEASON")
    if named:
        try:
            return int(named)
        except ValueError:
            raise ValueError(f"FO_SEASON must be a year, not {named!r}") from None
    moment = now if now is not None else datetime.now(NEW_YORK)
    return moment.astimezone(NEW_YORK).year


def is_over(landing_root: Path, season: int) -> bool:
    """True when the newest settings capture of the season has latest > final (R3.3).

    No capture, or a status lacking either period, is "not over": the safe answer is the
    one that makes no request.
    """
    newest: Capture | None = None
    leagues: set[str] = set()
    for capture in LandingZone(landing_root).committed(source="espn", endpoint="settings"):
        partitions = capture.meta.get("partitions")
        if not isinstance(partitions, dict) or partitions.get("season") != season:
            continue
        leagues.add(str(partitions.get("league_id")))
        # Stamps sort as time; the path breaks a tie so the choice is deterministic.
        if newest is None or _order(capture) > _order(newest):
            newest = capture
    if len(leagues) > 1:
        raise AmbiguousLeague(
            f"settings of season {season} are captured for leagues {sorted(leagues)}"
        )
    if newest is None:
        return False
    payload = newest.payload
    status = payload.get("status") if isinstance(payload, dict) else None
    if not isinstance(status, dict):
        return False
    latest, final = status.get("latestScoringPeriod"), status.get("finalScoringPeriod")
    if not (isinstance(latest, int) and isinstance(final, int)):
        return False
    if isinstance(latest, bool) or isinstance(final, bool):
        return False
    return latest > final


def _order(capture: Capture) -> tuple[str, str]:
    return str(capture.meta.get("fetched_at")), str(capture.directory)
