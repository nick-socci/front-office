"""Spec 0140, C10: the landing zone's captures and the uploaded table's rows, by key and path.

Read through LandingZone and the table read API, which bills nothing. Prints counts only.
"""

from __future__ import annotations

import collections
import os

from google.cloud import bigquery

from front_office.landing import LandingZone

COLUMNS = ("source", "endpoint", "request_path", "request_key", "fetched_at", "file_path")
zone = LandingZone("data/raw")  # type: ignore[arg-type]
UPLOADED = {
    ("mlb", "boxscore"),
    ("mlb", "schedule"),
    ("mlb", "players"),
    ("idmap", "player_id_map"),
    ("espn", "roster"),
    ("espn", "matchups"),
    ("espn", "settings"),
    ("espn", "pro_schedule"),
    ("espn", "teams"),
    ("espn", "transactions"),
    ("espn", "matchup_days"),
}
landed = collections.Counter()
for item in zone.iter_landed():
    meta = item.meta
    if (meta["source"], meta["endpoint"]) in UPLOADED:
        landed[
            (
                meta["source"],
                meta["endpoint"],
                LandingZone.request_path(meta["url"]),
                meta["request_key"],
                meta["fetched_at"],
                item.path.relative_to(zone.root).as_posix(),
            )
        ] += 1
client = bigquery.Client(project=os.environ["FO_BQ_PROJECT"], location="US")
table = client.get_table("raw.api_responses")
fields = [field for field in table.schema if field.name in COLUMNS]
stored = collections.Counter()
for row in client.list_rows(table, selected_fields=fields, page_size=20000):
    stored[tuple(row[name] for name in COLUMNS)] += 1
print("landed", sum(landed.values()), "stored", sum(stored.values()))
print(
    "only landed", sum((landed - stored).values()), "only stored", sum((stored - landed).values())
)
print("repeated in table", sum(1 for count in stored.values() if count > 1))
