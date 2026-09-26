"""MLB Stats API: the season schedule.

The schedule is the entry point for everything else on the MLB side — it produces the
game_pk list that boxscore ingestion walks. It is a *snapshot* endpoint: games get
postponed, rescheduled and resumed, so every run lands a new copy with its fetched_at
rather than skipping because a previous copy exists.
"""

from __future__ import annotations

from pathlib import Path

from front_office.http_client import HttpClient
from front_office.landing import LandingZone

BASE_URL = "https://statsapi.mlb.com/api/v1"
SOURCE = "mlb"
ENDPOINT = "schedule"
REGULAR_SEASON = "R"


def backfill_schedule(
    *,
    zone: LandingZone,
    client: HttpClient,
    season: int,
    fetched_at: str,
    game_type: str = REGULAR_SEASON,
) -> Path:
    """Fetch one season's schedule and land it. Returns the landed path."""
    params: dict[str, str | int] = {
        "sportId": 1,
        "season": season,
        "gameType": game_type,
        "startDate": f"{season}-01-01",
        "endDate": f"{season}-12-31",
    }
    response = client.get(f"{BASE_URL}/schedule", params=params)
    return zone.write(
        source=SOURCE,
        endpoint=ENDPOINT,
        partitions={"season": season, "game_type": game_type},
        name=f"fetched_at={fetched_at}",
        payload=response.json(),
        request={"url": str(response.request.url), "params": params},
        fetched_at=fetched_at,
    )
