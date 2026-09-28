"""ESPN transaction log: adds, drops, waiver claims and trades.

ESPN serves these from a "league communication" endpoint whose filtering lives in an
x-fantasy-filter header rather than query parameters, which is why this extractor builds
a header the others do not need.

Completeness is proven on every run, not assumed (#26):

* No message-type filter. A topic's totalMessageCount counts every message in it, so
  with a filter, a topic that also holds a lineup move (type 188) looks short and a
  genuinely missing message looks the same. Unfiltered, every topic must be exactly
  complete. Staging keeps only the types that move a player (espn_activity_types).
* Paged by offset. One request returns at most `limit` topics, newest first, and
  truncates silently. Pages are requested until one comes back short; each is landed
  as it arrived, under an `offset=` partition, sharing the run's fetched_at.
* New activity between two page requests shifts later pages by one, so a topic can
  appear on two pages. Staging deduplicates by message id. Topics are only ever added
  at the top, so a shift duplicates rather than skips.

The payload identifies the ESPN member who made each move (a `author` account GUID).
Staging never selects it, and fixtures never contain it.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from front_office.espn.client import league_url
from front_office.http_client import HttpClient
from front_office.landing import LandingZone

SOURCE = "espn"
ENDPOINT = "transactions"
VIEW = "kona_league_communication"

DEFAULT_LIMIT = 2000
MESSAGES_PER_TOPIC = 25
# A safety stop, not an expected size: 2026's log was 3,098 topics (two pages).
MAX_PAGES = 50


class TransactionLogIncomplete(RuntimeError):
    """The landed log cannot be shown complete. The pages are landed; the run fails."""


def activity_filter(limit: int = DEFAULT_LIMIT, offset: int = 0) -> str:
    """The x-fantasy-filter header value ESPN expects for one page of the activity log."""
    return json.dumps(
        {
            "topics": {
                "filterType": {"value": ["ACTIVITY_TRANSACTIONS"]},
                "limit": limit,
                "limitPerMessageSet": {"value": MESSAGES_PER_TOPIC},
                "offset": offset,
                "sortMessageDate": {"sortPriority": 1, "sortAsc": False},
                "sortFor": {"sortPriority": 2, "sortAsc": False},
            }
        }
    )


def incomplete_topics(topics: list[dict[str, Any]]) -> list[str]:
    """Topic ids holding fewer messages than ESPN says they have."""
    return [
        str(topic.get("id"))
        for topic in topics
        if len(topic.get("messages", [])) < int(topic.get("totalMessageCount", 0))
    ]


def backfill_transactions(
    *,
    zone: LandingZone,
    client: HttpClient,
    season: int,
    league_id: str,
    fetched_at: str,
    limit: int = DEFAULT_LIMIT,
) -> list[Path]:
    """Land every page of the log, then fail if any topic is incomplete."""
    paths: list[Path] = []
    topics: list[dict[str, Any]] = []
    for page in range(MAX_PAGES):
        offset = page * limit
        response = client.get(
            f"{league_url(season, league_id)}/communication/",
            params={"view": VIEW},
            headers={"x-fantasy-filter": activity_filter(limit, offset)},
        )
        payload = response.json()
        paths.append(
            zone.write(
                source=SOURCE,
                endpoint=ENDPOINT,
                partitions={"season": season, "league_id": league_id, "offset": offset},
                name=f"fetched_at={fetched_at}",
                payload=payload,
                request={
                    "url": str(response.request.url),
                    "params": {"view": VIEW, "limit": limit, "offset": offset},
                },
                fetched_at=fetched_at,
            )
        )
        page_topics = payload.get("topics", [])
        topics += page_topics
        if len(page_topics) < limit:
            break
    else:
        raise TransactionLogIncomplete(
            f"transaction log still full after {MAX_PAGES} pages of {limit}; stopped"
        )

    short = incomplete_topics(topics)
    if short:
        raise TransactionLogIncomplete(
            f"{len(short)} transaction topic(s) hold fewer messages than totalMessageCount "
            f"(e.g. {short[0]}); pages landed, but the log is not complete"
        )
    return paths
