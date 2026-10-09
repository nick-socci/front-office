"""MLB Stats API: the season's player list.

One request per season returns every player MLB lists for it, with the attributes the
player dimension is built from (spec 0060, ADR 0035). Like the schedule it is a *snapshot*
endpoint: rosters change all season, so every MLB run lands a new copy with its fetched_at
rather than skipping because a previous copy exists (ADR 0036). Fetch-and-save only: nothing
here reads the response. The endpoint is public; no credential is involved.
"""

from __future__ import annotations

from pathlib import Path

from front_office.http_client import HttpClient
from front_office.landing import LandingZone

BASE_URL = "https://statsapi.mlb.com/api/v1"
SOURCE = "mlb"
ENDPOINT = "players"


def backfill_players(
    *,
    zone: LandingZone,
    client: HttpClient,
    season: int,
    fetched_at: str,
) -> Path:
    """Fetch one season's player list and land it. Returns the landed path."""
    params: dict[str, str | int] = {"season": season}
    response = client.get(f"{BASE_URL}/sports/1/players", params=params)
    return zone.write(
        source=SOURCE,
        endpoint=ENDPOINT,
        partitions={"season": season},
        name=f"fetched_at={fetched_at}",
        payload=response.json(),
        request={"url": str(response.request.url), "params": params},
        fetched_at=fetched_at,
    )
