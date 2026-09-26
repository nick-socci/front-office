"""Smart Fantasy Baseball's player id map: the ESPN <-> MLBAM crosswalk.

ESPN player ids and MLBAM player ids are unrelated, so nothing can join a fantasy roster
to MLB game logs without a crosswalk. Matching on name gets close but cannot be trusted:
three names in the 2026 season belong to two different major leaguers each.

The source is a CSV. It is converted to a JSON array of row objects when landed -- a
mechanical, lossless transformation (header cells become keys), so the landing zone can
stay uniformly JSON.
"""

from __future__ import annotations

import csv
import io
from pathlib import Path

from front_office.http_client import HttpClient
from front_office.landing import LandingZone

SOURCE = "idmap"
ENDPOINT = "player_id_map"
PROVIDER = "sfbb"
CSV_URL = "https://www.smartfantasybaseball.com/PLAYERIDMAPCSV"


def parse_csv(text: str) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(text)))


def backfill_player_id_map(
    *,
    zone: LandingZone,
    client: HttpClient,
    fetched_at: str,
    url: str = CSV_URL,
) -> tuple[Path, int]:
    response = client.get(url)
    rows = parse_csv(response.text)
    path = zone.write(
        source=SOURCE,
        endpoint=ENDPOINT,
        partitions={"provider": PROVIDER},
        name=f"fetched_at={fetched_at}",
        payload=rows,
        request={"url": url, "params": {"provider": PROVIDER}},
        fetched_at=fetched_at,
    )
    return path, len(rows)
