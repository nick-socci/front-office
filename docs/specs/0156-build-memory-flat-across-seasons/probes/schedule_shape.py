"""Spec 0156 probe (C24): the MLB schedule read as a whole payload, or with a structure.

Reads every committed schedule capture under a landing root, as `LandingZone.iter_landed`
lists them (AGENTS.md: the landing zone is read through `LandingZone`), and takes each game's
`gamePk` and `status.detailedState`, two ways:

    payload    the whole document as one JSON value, games taken with JSON functions
               (how `stg_raw__mlb_schedule` gives it today, spec 0150 R3.3)
    structure  `dates[].games[]` declared, each game kept as JSON (as spec 0150 does for
               the heavy endpoints)

and prints the smallest memory limit (4 DuckDB threads) under which each runs, with the
rows it gives. Each rung is a new process.

    uv run python docs/specs/0156-build-memory-flat-across-seasons/probes/schedule_shape.py

Run from the repository root, against data/raw_2026 and data/raw.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import duckdb

from front_office.landing import LandingZone

RUNGS = (0.25, 0.5, 0.75, 1, 1.5, 2)
ROOTS = ("data/raw_2026", "data/raw")
GAMES = """
    select distinct
        cast(json_extract_string(game, '$.gamePk') as bigint) as game_pk,
        json_extract_string(game, '$.status.detailedState') as state
    from game_lists
    cross join unnest(game_lists.games) as u(game)
"""


def query(root: str, shape: str) -> str:
    landed = LandingZone(Path(root)).iter_landed(source="mlb", endpoint="schedule")
    files = "[" + ", ".join(f"'{capture.path}'" for capture in landed) + "]"
    if shape == "payload":
        return f"""
            with files as (
                select json as payload
                from read_json_objects({files}, format = 'unstructured',
                                       hive_partitioning = false)
            ),
            game_lists as (
                select cast(json_extract(payload, '$.dates[*].games[*]') as json[]) as games
                from files
            )
            {GAMES}"""
    return f"""
        with files as (
            select dates
            from read_json({files}, columns = {{'dates': 'STRUCT(games JSON[])[]'}},
                           format = 'auto', records = true, hive_partitioning = false)
        ),
        days as (select day from files cross join unnest(files.dates) as u(day)),
        game_lists as (select day.games as games from days)
        {GAMES}"""


def one(root: str, shape: str, gb: str) -> None:
    con = duckdb.connect()
    con.execute(f"set memory_limit = '{gb}GB'")
    con.execute("set threads = 4")
    try:
        counts = con.execute(
            f"select count(*), count(distinct game_pk) from ({query(root, shape)})"
        ).fetchone()
        print("ok", counts)
    except duckdb.Error as error:
        print("err", str(error)[:80])


def main() -> None:
    if len(sys.argv) > 1:
        one(*sys.argv[1:4])
        return
    for root in ROOTS:
        for shape in ("payload", "structure"):
            for gb in RUNGS:
                command = [sys.executable, __file__, root, shape, str(gb)]
                out = subprocess.run(command, capture_output=True, text=True, check=False)
                if out.stdout.startswith("ok"):
                    print(root, shape, gb, "GB", out.stdout.strip())
                    break
            else:
                print(root, shape, f"above {RUNGS[-1]} GB")


if __name__ == "__main__":
    main()
