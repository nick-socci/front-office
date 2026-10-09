"""Compare two warehouse files, relation by relation (spec 0028, R6.1).

Usage:  uv run python scripts/compare_warehouses.py OLD NEW [--round-doubles N] [--strict-columns]

First the relation names (tables and views of staging, intermediate, marts and
reconciliation); then for every relation in both, row counts, EXCEPT ALL both ways over the
columns they share, and columns only one side has. Exit 1 if any relation differs in a
shared column or in row count, or is missing from NEW. A relation only in NEW is reported,
not a failure (unless --strict-columns).

--round-doubles N is for the one-off comparison with an older real warehouse: it rounds
DOUBLE/FLOAT columns to N decimals and, for each relation that differs exactly, says whether
it still differs; a relation equal after rounding is then not a failure. It is off by default;
exact comparison is what the isolation check uses.

--strict-columns means the two warehouses must hold the same relations with the same
columns: a column on only one side of a relation, and a relation only in NEW, are failures
(exit 1), counted in the summary. (A relation only in OLD always is.) Without it such a column
or relation is printed and passed over, which suits a change that is meant to alter them; use
it where none should change.

The files may have any names, including the same one, and may be copies of a warehouse. A
view stores the catalog it was created in (dbt: the file stem), so each file is first read
alone, under the catalog its views name, and its relations are copied into a scratch database
in a temporary directory, removed on exit; the comparison runs on the two scratch databases.
The files themselves are opened read-only. If a file's views name more than one catalog the
run stops with exit 2 and compares nothing.
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

import duckdb

from warehouse_diff import RelationDiff, compare_relation, list_relations, materialise, view_catalog


def describe(diff: RelationDiff) -> str:
    return (
        f"rows {diff.left_rows} -> {diff.right_rows}; "
        f"only in OLD {diff.only_left}, only in NEW {diff.only_right}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("old", type=Path)
    parser.add_argument("new", type=Path)
    parser.add_argument("--round-doubles", type=int, default=None, metavar="N")
    parser.add_argument(
        "--strict-columns",
        action="store_true",
        help="the two warehouses must hold the same relations with the same columns",
    )
    args = parser.parse_args(argv)
    for path in (args.old, args.new):
        try:
            view_catalog(path)
        except ValueError as error:
            parser.error(str(error))

    with tempfile.TemporaryDirectory(prefix="compare_warehouses_") as scratch:
        scratch_old, scratch_new = Path(scratch) / "old.duckdb", Path(scratch) / "new.duckdb"
        materialise(args.old, scratch_old)
        materialise(args.new, scratch_new)
        con = duckdb.connect()
        # Aliases of the script's own: the scratch tables hold no catalog-qualified SQL.
        con.execute(f"attach '{scratch_old}' as old_wh (read_only)")
        con.execute(f"attach '{scratch_new}' as new_wh (read_only)")
        return compare(con, "old_wh", "new_wh", args)


def compare(con: duckdb.DuckDBPyConnection, old: str, new: str, args: argparse.Namespace) -> int:
    old_names, new_names = list_relations(con, old), list_relations(con, new)
    failed = False
    only_new = 0

    for name in sorted(old_names - new_names):
        print(f"MISSING from NEW: {name}")
        failed = True
    for name in sorted(new_names - old_names):
        if args.strict_columns:
            print(f"only in NEW (--strict-columns): {name}")
            only_new += 1
            failed = True
        else:
            print(f"only in NEW (not a failure): {name}")

    compared = same = last_digit = column_only = 0
    for name in sorted(old_names & new_names):
        compared += 1
        diff = compare_relation(con, old, new, name)
        notes = []
        if diff.left_only_columns:
            notes.append(f"columns only in OLD: {', '.join(diff.left_only_columns)}")
        if diff.right_only_columns:
            notes.append(f"columns only in NEW: {', '.join(diff.right_only_columns)}")
        if diff.differs:
            line = f"DIFFERS {name}: {describe(diff)}"
            still_differs = True
            if args.round_doubles is not None:
                rounded = compare_relation(con, old, new, name, round_doubles=args.round_doubles)
                still_differs = rounded.differs
                verdict = "still differs" if still_differs else "equal"
                line += f" | after rounding doubles to {args.round_doubles}: {verdict}"
            # With --round-doubles the rounded comparison is the verdict: a relation that is
            # equal after rounding is reported, but is not a failure.
            if still_differs:
                failed = True
            else:
                last_digit += 1
            print(line)
        else:
            same += 1
        for note in notes:
            print(f"  {name}: {note}")
        if args.strict_columns and notes:
            column_only += 1
            failed = True

    differ = compared - same - last_digit
    summary = f"compared {compared} relations: {same} identical, {differ} differ"
    if args.round_doubles is not None:
        summary += f", {last_digit} equal only after rounding doubles to {args.round_doubles}"
    if args.strict_columns:
        summary += f"; {column_only} with columns on one side only, {only_new} only in NEW"
    print(summary)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
