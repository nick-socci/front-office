"""ESPN transaction log: adds, drops, waiver claims and trades.

ESPN serves these from a "league communication" endpoint whose filtering lives in an
x-fantasy-filter header rather than query parameters, which is why this extractor builds
a header the others do not need.

The payload identifies the ESPN member who made each move (a `author` account GUID).
Staging never selects it, and fixtures never contain it.
"""

from __future__ import annotations

import json
from pathlib import Path

from front_office.espn.client import league_url
from front_office.http_client import HttpClient
from front_office.landing import LandingZone

SOURCE = "espn"
ENDPOINT = "transactions"
VIEW = "kona_league_communication"

# Add, waiver add, drop (three variants ESPN uses), and trade.
MESSAGE_TYPE_IDS = (178, 179, 180, 181, 239, 244)
DEFAULT_LIMIT = 2000
MESSAGES_PER_TOPIC = 25


def activity_filter(limit: int = DEFAULT_LIMIT) -> str:
    """The x-fantasy-filter header value ESPN expects for the activity log."""
    return json.dumps(
        {
            "topics": {
                "filterType": {"value": ["ACTIVITY_TRANSACTIONS"]},
                "limit": limit,
                "limitPerMessageSet": {"value": MESSAGES_PER_TOPIC},
                "offset": 0,
                "sortMessageDate": {"sortPriority": 1, "sortAsc": False},
                "sortFor": {"sortPriority": 2, "sortAsc": False},
                "filterIncludeMessageTypeIds": {"value": list(MESSAGE_TYPE_IDS)},
            }
        }
    )


def backfill_transactions(
    *,
    zone: LandingZone,
    client: HttpClient,
    season: int,
    league_id: str,
    fetched_at: str,
    limit: int = DEFAULT_LIMIT,
) -> Path:
    response = client.get(
        f"{league_url(season, league_id)}/communication/",
        params={"view": VIEW},
        headers={"x-fantasy-filter": activity_filter(limit)},
    )
    return zone.write(
        source=SOURCE,
        endpoint=ENDPOINT,
        partitions={"season": season, "league_id": league_id},
        name=f"fetched_at={fetched_at}",
        payload=response.json(),
        request={"url": str(response.request.url), "params": {"view": VIEW, "limit": limit}},
        fetched_at=fetched_at,
    )
