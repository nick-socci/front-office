"""ESPN matchup results: who played whom, and who won each category.

Fetched ONCE per run, not once per scoring period. These views return the whole season's
schedule on every call: the spike's per-period snapshots were ~3.5 MB each largely
because of this duplication.
"""

from __future__ import annotations

from pathlib import Path

from front_office.espn.client import league_url
from front_office.http_client import HttpClient
from front_office.landing import LandingZone

SOURCE = "espn"
ENDPOINT = "matchups"
VIEWS = ("mMatchupScore", "mScoreboard")


def backfill_matchups(
    *,
    zone: LandingZone,
    client: HttpClient,
    season: int,
    league_id: str,
    fetched_at: str,
) -> Path:
    params = [("view", view) for view in VIEWS]
    response = client.get(league_url(season, league_id), params=params)
    return zone.write(
        source=SOURCE,
        endpoint=ENDPOINT,
        partitions={"season": season, "league_id": league_id},
        name=f"fetched_at={fetched_at}",
        payload=response.json(),
        request={"url": str(response.request.url), "params": {"view": ",".join(VIEWS)}},
        fetched_at=fetched_at,
    )
