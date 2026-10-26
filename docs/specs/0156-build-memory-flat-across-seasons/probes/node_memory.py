"""Spec 0156 probe: the smallest DuckDB memory limit under which one compiled node runs alone.

Runs a compiled model's or test's SQL as `create table … as`, in a fresh scratch database
that attaches the warehouse read-only under its own catalog name, at each rung of a ladder
of memory limits, and prints the first rung that passes. Each rung is a new process, so
the resident peak printed is that rung's alone.

    uv run python docs/specs/0156-build-memory-flat-across-seasons/probes/node_memory.py \
        <warehouse.duckdb> <compiled.sql> --threads 4 [--disable common_subplan]

The warehouse must hold the node's upstream relations (a full `dbt build` of the same
landing root), and the compiled SQL must come from that build's target directory, so its
catalog name and its capture views' landing root match. Run from the repository root.
"""

from __future__ import annotations

import argparse
import os
import resource
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import duckdb

RUNGS = (0.25, 0.5, 0.75, 1, 1.5, 2, 3, 4)


def run_once(warehouse: Path, sql_file: Path, gb: float, threads: int, disable: str) -> str:
    """One rung in this process: 'ok <seconds> <peak GB> <rows>' or 'err <message>'."""
    scratch = Path(tempfile.mkdtemp())
    try:
        con = duckdb.connect(str(scratch / "probe.duckdb"))
        con.execute(f"attach '{warehouse}' as {warehouse.stem} (read_only)")
        con.execute(f"set memory_limit = '{gb}GB'")
        con.execute(f"set threads = {threads}")
        con.execute(f"set temp_directory = '{scratch / 'spill'}'")
        if disable:
            con.execute(f"set disabled_optimizers = '{disable}'")
        started = time.monotonic()
        try:
            con.execute("create table probe_out as " + sql_file.read_text())
        except duckdb.Error as error:
            return "err " + str(error).splitlines()[0][:120]
        row = con.execute("select count(*) from probe_out").fetchone()
        peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1048576
        rows = row[0] if row else None
        return f"ok {time.monotonic() - started:.1f}s peak={peak:.2f}GB rows={rows}"
    finally:
        shutil.rmtree(scratch)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("warehouse", type=Path)
    parser.add_argument("sql_file", type=Path)
    parser.add_argument("--threads", type=int, default=os.cpu_count())
    parser.add_argument("--disable", default="", help="DuckDB optimizers to disable")
    parser.add_argument("--rung", type=float, help="run one rung in this process")
    args = parser.parse_args()
    if args.rung is not None:
        print(run_once(args.warehouse, args.sql_file, args.rung, args.threads, args.disable))
        return
    name = args.sql_file.name
    for gb in RUNGS:
        command = [
            sys.executable, __file__, str(args.warehouse), str(args.sql_file),
            "--threads", str(args.threads), "--disable", args.disable, "--rung", str(gb),
        ]  # fmt: skip
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        if result.stdout.startswith("ok"):
            print(f"{name} threads={args.threads}: {gb} GB {result.stdout.strip()}")
            return
    print(f"{name} threads={args.threads}: above {RUNGS[-1]} GB")


if __name__ == "__main__":
    main()
