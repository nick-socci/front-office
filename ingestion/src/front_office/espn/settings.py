"""ESPN league settings and status.

A snapshot endpoint: scoring rules can be edited mid-season and the status block moves
every day, so each run lands a new copy. The status block is also what tells roster
ingestion which scoring periods exist and which are finished.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from front_office.espn.client import league_url
from front_office.http_client import HttpClient
from front_office.landing import LandingZone

SOURCE = "espn"
ENDPOINT = "settings"
VIEWS = ("mSettings", "mStatus")


def backfill_settings(
    *,
    zone: LandingZone,
    client: HttpClient,
    season: int,
    league_id: str,
    fetched_at: str,
) -> tuple[Path, dict[str, Any]]:
    """Land the settings snapshot. Returns the path and the payload (for its status)."""
    params = [("view", view) for view in VIEWS]
    response = client.get(league_url(season, league_id), params=params)
    payload: dict[str, Any] = response.json()
    path = zone.write(
        source=SOURCE,
        endpoint=ENDPOINT,
        partitions={"season": season, "league_id": league_id},
        name=f"fetched_at={fetched_at}",
        payload=payload,
        request={"url": str(response.request.url), "params": {"view": ",".join(VIEWS)}},
        fetched_at=fetched_at,
    )
    return path, payload
