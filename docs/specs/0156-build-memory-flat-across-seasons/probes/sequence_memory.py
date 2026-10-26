"""Spec 0156 probe (C19): the six heavy models one after another in one DuckDB instance.

Runs each model's compiled SQL from a build's target directory as `create or replace
table`, at one memory limit and thread count, and prints `duckdb_memory()` after each, to
show what the buffer pool still holds between models.

    uv run python docs/specs/0156-build-memory-flat-across-seasons/probes/sequence_memory.py \
        <build dir holding warehouse.duckdb and target/> <GB> <threads> <true|false>

The last argument sets `enable_external_file_cache`. Writes only <build dir>/../seq/.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import duckdb

MODELS = (
    "stg_espn__roster_entries",
    "stg_espn__player_game_stats",
    "stg_mlb__batting_game_logs",
    "stg_mlb__pitching_game_logs",
    "stg_espn__matchup_days",
    "stg_espn__matchup_player_lines",
)
MEMORY = """
    select tag, memory_usage_bytes / 1e6 as mb
    from duckdb_memory()
    where memory_usage_bytes > 1e6
    order by mb desc
"""


def main() -> None:
    build, gb, threads, cache = Path(sys.argv[1]), sys.argv[2], sys.argv[3], sys.argv[4]
    out = build.parent / "seq"
    out.mkdir(exist_ok=True)
    con = duckdb.connect(str(out / "out.duckdb"))
    con.execute(f"attach '{build / 'warehouse.duckdb'}' as warehouse (read_only)")
    con.execute(f"set memory_limit = '{gb}GB'")
    con.execute(f"set threads = {threads}")
    con.execute(f"set enable_external_file_cache = {cache}")

    def memory() -> str:
        return ", ".join(f"{tag}={mb:.0f}MB" for tag, mb in con.execute(MEMORY).fetchall())

    print("start", memory())
    compiled = build / "target" / "compiled" / "front_office" / "models"
    for name in MODELS:
        sql_file = next(p for p in compiled.rglob(f"{name}.sql") if ".yml" not in p.parent.name)
        started = time.monotonic()
        try:
            con.execute(f"create or replace table {name} as " + sql_file.read_text())
            status = "ok"
        except duckdb.Error as error:
            status = "ERR " + str(error).splitlines()[0][:90]
        print(f"{name}: {status} {time.monotonic() - started:.1f}s | {memory()}", flush=True)


if __name__ == "__main__":
    main()
