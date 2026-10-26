"""Spec 0156 probe (R6.3): every relation of two real-season warehouses, compared exactly.

`scripts/compare_warehouses.py` materializes every capture view into a scratch table first,
which on eight seasons needs more memory than the machine has. This compares the same
relations without that step: both files attached read-only (each under its own name, in
its own scratch copy of nothing: tables are read in place), and for every table and every
view of staging, intermediate, marts and reconciliation:

- the column names must match (as `--strict-columns`), except the named exclusions;
- the row counts must match, and EXCEPT ALL both ways over the shared columns gives 0.

The capture views (`staging.stg_raw__*`) are skipped: their columns are parsed payloads
(JSON, structs, maps), which no EXCEPT compares; R3.4's probe compares the schedule's.
A view names the catalog it was built in (`warehouse`, the file stem), so each file is
attached as `warehouse` in turn, read-only, and each relation's rows are copied into a
local table before the other file is attached.

    uv run python docs/specs/0156-build-memory-flat-across-seasons/probes/compare_bounded.py \
        OLD_WAREHOUSE NEW_WAREHOUSE [--memory-gb 10]

Prints one line per relation that differs and a summary; exit 1 if any differs. Run from
the repository root.
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

import duckdb

SCHEMAS = ("staging", "intermediate", "marts", "reconciliation")
RELATIONS = """
    select table_schema, table_name, table_type
    from information_schema.tables
    where table_catalog = 'warehouse' and table_schema in ({schemas})
      and table_name not like 'stg_raw\\_\\_%' escape '\\'
    order by 1, 2
"""


def relations(con: duckdb.DuckDBPyConnection) -> dict[str, list[str]]:
    """schema.name -> its column names, in order."""
    schemas = ", ".join(f"'{s}'" for s in SCHEMAS)
    found = {}
    for schema, name, _ in con.execute(RELATIONS.format(schemas=schemas)).fetchall():
        columns = con.execute(
            "select column_name from information_schema.columns where table_catalog = "
            "'warehouse' and table_schema = ? and table_name = ? order by ordinal_position",
            [schema, name],
        ).fetchall()
        found[f"{schema}.{name}"] = [c[0] for c in columns]
    return found


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("old", type=Path)
    parser.add_argument("new", type=Path)
    parser.add_argument("--memory-gb", type=int, default=10)
    args = parser.parse_args()

    with tempfile.TemporaryDirectory() as scratch:
        work = duckdb.connect(str(Path(scratch) / "work.duckdb"))
        work.execute(f"set memory_limit = '{args.memory_gb}GB'")
        work.execute(f"set temp_directory = '{scratch}/spill'")

        def attach(path: Path) -> None:
            work.execute(f"attach '{path}' as warehouse (read_only)")

        listed = {}
        for label, path in (("old", args.old), ("new", args.new)):
            attach(path)
            listed[label] = relations(work)
            work.execute("detach warehouse")
        old_rel, new_rel = listed["old"], listed["new"]

        problems = []
        for name in sorted(set(old_rel) | set(new_rel)):
            if name not in new_rel or name not in old_rel:
                problems.append(f"{name}: only in {'old' if name in old_rel else 'new'}")
                continue
            if old_rel[name] != new_rel[name]:
                problems.append(f"{name}: columns differ {old_rel[name]} vs {new_rel[name]}")
                continue
            cols = ", ".join(f'"{c}"' for c in old_rel[name])
            for label, path in (("o", args.old), ("n", args.new)):
                attach(path)
                copy = f"create or replace table {label} as select {cols} from warehouse.{name}"
                work.execute(copy)
                work.execute("detach warehouse")
            counts = work.execute(
                "select (select count(*) from o), (select count(*) from n), "
                "(select count(*) from (select * from o except all select * from n)), "
                "(select count(*) from (select * from n except all select * from o))"
            ).fetchone()
            assert counts is not None
            if counts[0] != counts[1] or counts[2] or counts[3]:
                problems.append(
                    f"{name}: rows {counts[0]} vs {counts[1]}, "
                    f"old-new {counts[2]}, new-old {counts[3]}"
                )
        compared = len(set(old_rel) & set(new_rel))
        for problem in problems:
            print(problem)
        print(f"relations compared: {compared}; differing: {len(problems)}")
        return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
