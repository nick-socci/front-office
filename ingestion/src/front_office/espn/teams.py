"""ESPN teams: names, owners' team metadata, records and playoff seeds.

A snapshot endpoint -- records change daily. Note that this payload also contains league
members' personal details; staging never selects them (see stg_espn__teams).
"""

from __future__ import annotations

from pathlib import Path

from front_office.espn.client import league_url
from front_office.http_client import HttpClient
from front_office.landing import LandingZone

SOURCE = "espn"
ENDPOINT = "teams"
VIEWS = ("mTeam",)


def backfill_teams(
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
