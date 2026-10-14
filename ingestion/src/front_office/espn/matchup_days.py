"""ESPN matchups asked for one scoring period at a time, for seasons that are over.

ESPN, asked for one scoring period's matchups, attaches that day's rosters to the matchups
of exactly one matchup period (ADR 0055). One request per scoring period therefore says
which matchup period each day belongs to, which the whole-season `matchups` capture does
not. The rosters themselves come from the `roster` endpoint; this one is read for the
mapping only.

The periods come from the newest committed settings capture of the league-season, read
through `LandingZone`: `firstScoringPeriod` through `finalScoringPeriod`. With no such
capture nothing is requested (`SettingsNotLanded`).

The raw responses hold `teams` and `settings`, which carry member data as the matchups
capture does. They are gitignored and never selected, and this module never opens a
`matchup_days` payload.

There is no settle rule: the endpoint is fetched for seasons that are over, so a landed
period is skipped and `refresh` fetches it again. A running season has
`pointsByScoringPeriod` instead.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from front_office.espn.client import league_url
from front_office.http_client import AuthExpired, HttpClient
from front_office.landing import Capture, LandingCollision, LandingZone

logger = logging.getLogger(__name__)

SOURCE = "espn"
ENDPOINT = "matchup_days"
VIEWS = ("mMatchupScore", "mScoreboard")


class SettingsNotLanded(Exception):
    """No committed settings capture of the league-season, so the periods are unknown."""


@dataclass
class MatchupDaysSummary:
    fetched: int = 0
    skipped: int = 0
    failed: int = 0
    failed_periods: list[int] = field(default_factory=list)


def backfill_matchup_days(
    *,
    zone: LandingZone,
    client: HttpClient,
    season: int,
    league_id: str,
    fetched_at: str,
    refresh: bool = False,
) -> MatchupDaysSummary:
    """Land the matchups of every scoring period of the season that is not yet landed."""
    first, final = _period_range(zone, season=season, league_id=league_id)
    summary = MatchupDaysSummary()
    for period in range(first, final + 1):
        partitions = {"season": season, "league_id": league_id, "scoring_period": period}
        if not refresh and zone.has_landed(source=SOURCE, endpoint=ENDPOINT, partitions=partitions):
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
        except (AuthExpired, LandingCollision):
            # Every remaining period would be rejected too: stop, don't log 180 failures.
            # A collision likewise stops the run; it is not one failed period.
            raise
        except Exception:
            logger.exception("matchup-days fetch failed for scoring period %s", period)
            summary.failed += 1
            summary.failed_periods.append(period)
        else:
            summary.fetched += 1
    return summary


def _period_range(zone: LandingZone, *, season: int, league_id: str) -> tuple[int, int]:
    """First and final scoring period of the newest committed settings capture."""
    newest: Capture | None = None
    for capture in zone.committed(
        source=SOURCE,
        endpoint="settings",
        partitions={"season": season, "league_id": league_id},
    ):
        # Stamps sort as time; the path breaks a tie so the choice is deterministic.
        if newest is None or _order(capture) > _order(newest):
            newest = capture
    if newest is None:
        raise SettingsNotLanded(
            f"no settings captured for season {season}, league {league_id}: "
            "run `backfill espn --only rosters` or `--only matchups` first"
        )
    payload = newest.payload
    status = payload.get("status") if isinstance(payload, dict) else None
    status = status if isinstance(status, dict) else {}
    first, final = status.get("firstScoringPeriod"), status.get("finalScoringPeriod")
    if (
        not isinstance(first, int)
        or isinstance(first, bool)
        or not isinstance(final, int)
        or isinstance(final, bool)
    ):
        raise SettingsNotLanded(
            f"the newest settings capture for season {season}, league {league_id} has no "
            "firstScoringPeriod and finalScoringPeriod in its status"
        )
    return first, final


def _order(capture: Capture) -> tuple[str, str]:
    return str(capture.meta.get("fetched_at")), str(capture.directory)


def _fetch_one(
    *,
    zone: LandingZone,
    client: HttpClient,
    season: int,
    league_id: str,
    period: int,
    fetched_at: str,
) -> None:
    """Land one scoring period's matchups."""
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
