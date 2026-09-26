"""ESPN rosters, one snapshot per scoring period.

A scoring period is one day of fantasy scoring. Its roster is settled once the period
ends, and ESPN keeps serving historical periods -- verified by spike before this design
was chosen.

"Settled" is decided against the league's own status, not against the period number:
latestScoringPeriod is the period currently in progress, so only periods strictly before
it are final. Treating `period <= latest` as settled would freeze a day whose lineup can
still change.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from front_office.espn.client import league_url
from front_office.http_client import HttpClient
from front_office.landing import LandingZone

logger = logging.getLogger(__name__)

SOURCE = "espn"
ENDPOINT = "roster"
VIEWS = ("mRoster",)


@dataclass
class RosterBackfillSummary:
    fetched: int = 0
    skipped: int = 0
    failed: int = 0
    failed_periods: list[int] = field(default_factory=list)


def last_period(status: dict[str, Any]) -> int:
    """The highest scoring period that exists: the season's final period, or today's."""
    latest = int(status.get("latestScoringPeriod", 0))
    final = int(status.get("finalScoringPeriod", latest))
    return min(latest, final)


def period_is_over(period: int, status: dict[str, Any]) -> bool:
    """True when `period` can no longer change."""
    return period < int(status.get("latestScoringPeriod", 0))


def needs_fetch(
    zone: LandingZone,
    *,
    season: int,
    league_id: str,
    period: int,
    status: dict[str, Any],
    refresh: bool = False,
) -> bool:
    if refresh:
        return True
    if not _has_landed(zone, season=season, league_id=league_id, period=period):
        return True
    return not period_is_over(period, status)


def backfill_rosters(
    *,
    zone: LandingZone,
    client: HttpClient,
    season: int,
    league_id: str,
    status: dict[str, Any],
    fetched_at: str,
    refresh: bool = False,
) -> RosterBackfillSummary:
    """Land rosters for every scoring period up to the latest that exists."""
    summary = RosterBackfillSummary()
    for period in range(1, last_period(status) + 1):
        if not needs_fetch(
            zone,
            season=season,
            league_id=league_id,
            period=period,
            status=status,
            refresh=refresh,
        ):
            summary.skipped += 1
            continue
        try:
            _fetch_one(
                zone=zone,
                client=client,
                season=season,
                league_id=league_id,
                period=period,
                fetched_at=fetched_at,
            )
        except Exception:
            logger.exception("roster fetch failed for scoring period %s", period)
            summary.failed += 1
            summary.failed_periods.append(period)
        else:
            summary.fetched += 1
    return summary


def _fetch_one(
    *,
    zone: LandingZone,
    client: HttpClient,
    season: int,
    league_id: str,
    period: int,
    fetched_at: str,
) -> None:
    params: list[tuple[str, str | int]] = [("view", view) for view in VIEWS]
    params.append(("scoringPeriodId", period))
    response = client.get(league_url(season, league_id), params=params)
    zone.write(
        source=SOURCE,
        endpoint=ENDPOINT,
        partitions={"season": season, "league_id": league_id, "scoring_period": period},
        name=f"fetched_at={fetched_at}",
        payload=response.json(),
        request={
            "url": str(response.request.url),
            "params": {"view": ",".join(VIEWS), "scoringPeriodId": period},
        },
        fetched_at=fetched_at,
    )


def _has_landed(zone: LandingZone, *, season: int, league_id: str, period: int) -> bool:
    directory = zone.path_for(
        source=SOURCE,
        endpoint=ENDPOINT,
        partitions={"season": season, "league_id": league_id, "scoring_period": period},
        name="unused",
    ).parent
    if not directory.exists():
        return False
    return any(not path.name.endswith(".meta.json") for path in directory.glob("*.json"))
