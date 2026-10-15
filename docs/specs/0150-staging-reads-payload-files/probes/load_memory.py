"""Spec 0150 probe: load the landing zone from scratch, as the directions of #150 would.

    table   front_office.load.load_landing_zone into a fresh warehouse file, optionally with
            a smaller row group (direction 3: ATTACH ... (ROW_GROUP_SIZE n); a DuckDB file
            refuses anything below 2,048 rows)
    parquet one zstd Parquet file per batch of 50 captures, per source/endpoint/season
            (direction 1), with raw.api_responses a view over the files

    uv run python docs/specs/0150-staging-reads-payload-files/probes/load_memory.py \
        table data/exp150/rg2048.duckdb --row-group 2048 --memory-limit none

RSS is sampled every two seconds, so the printed curve shows memory falling back when a
row group is written. Run from the repository root; it writes only where it is told to.
"""

from __future__ import annotations

import argparse
import json
import resource
import threading
import time
from collections import defaultdict
from pathlib import Path

import duckdb

from front_office.landing import LandingZone
from front_office.load import load_landing_zone

BATCH = 50


def rss_gb() -> float:
    with Path("/proc/self/status").open() as status:
        kb = next(int(line.split()[1]) for line in status if line.startswith("VmRSS"))
    return kb / 1048576


def load_table(raw: Path, db: Path, row_group: int, con: duckdb.DuckDBPyConnection) -> str:
    options = f" (row_group_size {row_group})" if row_group else ""
    con.execute(f"attach '{db}' as warehouse{options}")
    con.execute("use warehouse")
    return f"rows={load_landing_zone(con, LandingZone(raw))}"


def load_parquet(raw: Path, out: Path, row_group: int, con: duckdb.DuckDBPyConnection) -> str:
    groups: dict[tuple[str, str, str], list[tuple[object, ...]]] = defaultdict(list)
    for landed in LandingZone(raw).iter_landed():
        meta = landed.meta
        season = str(meta["partitions"].get("season", "none"))
        groups[(meta["source"], meta["endpoint"], season)].append(
            (
                meta["source"],
                meta["endpoint"],
                LandingZone.request_path(meta["url"]),
                meta["request_key"],
                meta["fetched_at"],
                json.dumps(meta["partitions"]),
                str(landed.path),
            )
        )
    files = 0
    for (source, endpoint, season), rows in sorted(groups.items()):
        directory = out / f"source={source}" / f"endpoint={endpoint}" / f"season={season}"
        directory.mkdir(parents=True, exist_ok=True)
        for start in range(0, len(rows), BATCH):
            con.execute(
                "create or replace temp table batch (source varchar, endpoint varchar, "
                "request_path varchar, request_key varchar, fetched_at varchar, "
                "partitions json, payload json, file_path varchar)"
            )
            batch = rows[start : start + BATCH]
            con.executemany(
                "insert into batch values (?, ?, ?, ?, ?, ?, ?, ?)",
                [(*row[:6], Path(str(row[6])).read_text(), row[6]) for row in batch],
            )
            target = directory / f"part-{start // BATCH:05d}.parquet"
            con.execute(
                f"copy batch to '{target}' "
                f"(format parquet, row_group_size {row_group or 16}, compression zstd)"
            )
            files += 1
    return f"parquet_files={files} rows={sum(map(len, groups.values()))}"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("layout", choices=["table", "parquet"])
    parser.add_argument("target", type=Path, help="warehouse file, or Parquet directory")
    parser.add_argument("--raw", type=Path, default=Path("data/raw"))
    parser.add_argument("--row-group", type=int, default=0, help="0 = DuckDB's default")
    parser.add_argument("--memory-limit", default="none")
    parser.add_argument("--threads", type=int, default=0, help="0 = DuckDB's default")
    args = parser.parse_args()

    samples: list[tuple[float, float]] = []
    done = threading.Event()

    def sample() -> None:
        started = time.monotonic()
        while not done.is_set():
            samples.append((time.monotonic() - started, rss_gb()))
            time.sleep(2)

    threading.Thread(target=sample, daemon=True).start()
    con = duckdb.connect()
    if args.memory_limit != "none":
        con.execute(f"set memory_limit = '{args.memory_limit}'")
    if args.threads:
        con.execute(f"set threads = {args.threads}")
    started = time.monotonic()
    try:
        if args.layout == "table":
            result = load_table(args.raw, args.target, args.row_group, con)
        else:
            result = load_parquet(args.raw, args.target, args.row_group, con)
    except duckdb.OutOfMemoryException as error:
        result = f"OUT OF MEMORY: {str(error).splitlines()[0][:100]}"
    seconds = time.monotonic() - started
    done.set()
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1048576
    step = max(1, len(samples) // 15)
    curve = " ".join(f"{t:.0f}s:{gb:.1f}" for t, gb in samples[::step])
    print(
        f"{args.layout} row_group={args.row_group or 'default'} limit={args.memory_limit} "
        f"{result} {seconds:.0f}s peak_rss={peak:.1f}GB\n  curve (GB): {curve}"
    )


if __name__ == "__main__":
    main()
