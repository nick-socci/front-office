"""Spec 0156 probe (R3.4): the schedule's games are the same read with a structure as whole.

Compares the games two warehouses give. The OLD one holds the capture view that gives each
schedule capture's whole response as `payload`; the NEW one holds the view that declares
`dates[].games[]` (ADR 0101). From OLD, per capture, `file_path` and each element of
`json_extract(payload, '$.dates[*].games[*]')`; from NEW, `file_path` and each game of
`dates[].games[]`. Each game is canonicalised in Python (`json.dumps(json.loads(text),
sort_keys=True)`), so key order and spacing do not count, and the two are compared as
multisets of (file_path, game). Prints the counts and the number differing each way, and
exits 1 if any differ.

Each warehouse is opened in its own connection, read-only, as the catalog `warehouse`: the
views inside name their own catalog, so attaching both in one connection under aliases
would leave one of them unable to find its manifest.

    uv run python docs/specs/0156-build-memory-flat-across-seasons/probes/schedule_games_equal.py \
        OLD_WAREHOUSE NEW_WAREHOUSE

Run from the repository root.
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

import duckdb

OLD_GAMES = """
    select file_path, unnest(json_extract(payload, '$.dates[*].games[*]')) as game
    from (select file_path, payload from warehouse.staging.stg_raw__mlb_schedule)
"""
NEW_GAMES = """
    select file_path, game
    from (select file_path, unnest(dates) as schedule_day
          from warehouse.staging.stg_raw__mlb_schedule)
    cross join unnest(schedule_day.games) as u(game)
"""


def games(warehouse: str, query: str) -> Counter[tuple[str, str]]:
    """The multiset of (file_path, canonical game) one warehouse's view gives."""
    con = duckdb.connect(warehouse, read_only=True)
    try:
        con.execute("set memory_limit = '10GB'")
        counts: Counter[tuple[str, str]] = Counter()
        cursor = con.execute(query)
        while batch := cursor.fetchmany(1000):
            for file_path, game in batch:
                counts[(file_path, json.dumps(json.loads(str(game)), sort_keys=True))] += 1
        return counts
    finally:
        con.close()


def main(old_warehouse: str, new_warehouse: str) -> int:
    old = games(str(Path(old_warehouse)), OLD_GAMES)
    new = games(str(Path(new_warehouse)), NEW_GAMES)
    only_old = sum((old - new).values())
    only_new = sum((new - old).values())
    print(f"old games: {sum(old.values())}")
    print(f"new games: {sum(new.values())}")
    print(f"in old, not in new: {only_old}")
    print(f"in new, not in old: {only_new}")
    print("equal" if not (only_old or only_new) else "DIFFERENT")
    return 1 if only_old or only_new else 0


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    sys.exit(main(sys.argv[1], sys.argv[2]))
