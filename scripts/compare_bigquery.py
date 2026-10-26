"""Compare the BigQuery build with the DuckDB build of the same models.

Spec 0130, R5.2 to R5.5; ADR 0053. Everything that is not floating-point is held exactly;
floating-point columns are held to a tolerance, because BigQuery cannot be told the order
of a float sum and so cannot be made to agree to the last digit.

Usage:  uv run --group bigquery python scripts/compare_bigquery.py \\
            --db data/warehouse.duckdb --project "$FO_BQ_PROJECT" [--bq-against-bq SUFFIX]

1. The relations are the models of the dbt selector `bigquery` (every model, ADR 0105), less
   the ephemeral ones, which have no relation.
2. Each BigQuery relation is read back into a scratch DuckDB database, and the local
   warehouse is attached read-only beside it. A table is read through the client, which is
   not billed. A view has no rows to read, so it is queried, under the same cap on bytes
   billed as the dbt target.
3. Columns are compared by kind, not by type name: INT64 against BIGINT, HUGEINT or
   INTEGER as integers; a TIMESTAMP on either side as an instant in UTC; text, dates and
   booleans as they are. A column on one side only, or of a different kind, fails.
4. Columns that are not floating-point: EXCEPT ALL both ways, so as multisets.
5. Floating-point columns: the two sides are joined on the relation's declared unique key
   (its `unique` or `unique_combination_of_columns` test) and each pair must be equal
   within a relative 1e-9, or within an absolute 1e-12 where both values are below 1e-3 in
   magnitude; a null on one side only is a difference, and so is a row with no partner.
   For each column the count of exactly equal values and the largest differences are
   printed.

6. A JSON or nested column (a struct, list or map; a BigQuery RECORD or REPEATED field)
   is neither read back nor compared, and is printed as such: a JSON value is billed whole
   when queried and BigQuery rewrites its text, and the two warehouses spell a nested value
   differently. Both sides must still have the column.
7. The capture views (`stg_raw__*`, spec 0150) are compared like any relation, on their
   scalar columns: the manifest's key and path, and the payload fields read as plain
   values (a league id, a season). Selecting only those from a BigQuery view leaves its
   payload unread, so it costs little. Their nested fields are what the staging models
   built on them read, and those models are compared exactly.

8. For a relation in GROUPS (the lineup solver's rows, spec 0137, R3.3), a difference is
   printed as the groups that differ, here the team-days, each with its rows on each side,
   and not only as a count: whether the two warehouses broke a tie differently is a
   decision for the owner, who needs the rows to make it. At most MAX_GROUPS_LISTED are
   printed, and the rest are counted.

Exit 0 only if every relation passes. One line per relation either way.

`--bq-against-bq SUFFIX` compares two BigQuery builds with each other instead, exactly,
floats included: the second is the one built with --vars '{fo_schema_suffix: SUFFIX}'.

`--suffix SUFFIX` reads the (first) BigQuery build from the datasets of that suffix, so a
branch built beside the populated build is compared without replacing it (spec 0156).
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import duckdb

from warehouse_diff import (
    columns,
    count_except,
    count_rows,
    is_json,
    qualified,
    quote,
    view_catalog,
)

SELECTOR = "bigquery"
RELATIVE_TOLERANCE = 1e-9
ABSOLUTE_TOLERANCE = 1e-12
NEAR_ZERO = 1e-3
# Relations whose differences are listed by group, with the rows of each side (item 8): the
# columns that name a group. The solver's group is a team-day.
GROUPS = {
    "int_fantasy__optimal_lineups": [
        "platform",
        "league_id",
        "season",
        "scoring_date",
        "fantasy_team_id",
    ]
}
MAX_GROUPS_LISTED = 20
MAXIMUM_BYTES_BILLED = 10_000_000_000
DBT_ROOT = Path(__file__).resolve().parents[1] / "dbt"


def is_uncompared(data_type: str) -> bool:
    """A DuckDB column type that is not compared by value: JSON, or a nested type."""
    upper = data_type.upper()
    return (
        is_json(data_type) or upper.startswith(("STRUCT(", "MAP(", "UNION(")) or upper.endswith("]")
    )


def _bq_uncompared(field: Any) -> bool:
    mode = (getattr(field, "mode", None) or "NULLABLE").upper()
    return field.field_type.upper() in ("JSON", "RECORD", "STRUCT") or mode == "REPEATED"


_KINDS = {
    "TINYINT": "integer",
    "SMALLINT": "integer",
    "INTEGER": "integer",
    "BIGINT": "integer",
    "HUGEINT": "integer",
    "DOUBLE": "float",
    "FLOAT": "float",
    "VARCHAR": "text",
    "DATE": "date",
    "BOOLEAN": "boolean",
    "TIMESTAMP": "instant",
    "TIMESTAMP WITH TIME ZONE": "instant",
}


def kind(data_type: str) -> str:
    """What a DuckDB column type is compared as. An unknown type is its own kind, so it
    only ever matches itself."""
    return _KINDS.get(data_type.upper(), data_type.upper())


def _comparable(name: str, column_kind: str) -> str:
    """The column as a value both sides can be compared on."""
    if column_kind == "integer":
        return f"cast({quote(name)} as hugeint)"
    if column_kind == "instant":
        # microseconds since the epoch: a naive timestamp is read as UTC, as dbt wrote it
        return f"epoch_us({quote(name)})"
    if column_kind in ("float", "text", "date", "boolean"):
        return quote(name)
    return f"cast({quote(name)} as varchar)"


@dataclass
class FloatColumn:
    compared: int
    exactly_equal: int
    beyond_tolerance: int
    largest_absolute: float = 0.0
    largest_relative: float = 0.0


@dataclass
class GroupDifference:
    """One group (a team-day) whose rows differ, with its rows on each side."""

    group: tuple[Any, ...]
    left_rows: list[tuple[Any, ...]]
    right_rows: list[tuple[Any, ...]]


@dataclass
class Result:
    relation: str
    left_rows: int = 0
    right_rows: int = 0
    only_left: int = 0
    only_right: int = 0
    unjoined: int = 0
    problems: list[str] = field(default_factory=list)
    uncompared: list[str] = field(default_factory=list)
    floats: dict[str, FloatColumn] = field(default_factory=dict)
    group_columns: list[str] = field(default_factory=list)
    differing_groups: list[GroupDifference] = field(default_factory=list)
    groups_not_listed: int = 0

    @property
    def passed(self) -> bool:
        return (
            not self.problems
            and self.left_rows == self.right_rows
            and self.only_left == 0
            and self.only_right == 0
            and self.unjoined == 0
            and all(column.beyond_tolerance == 0 for column in self.floats.values())
        )


def compare_relation(
    con: duckdb.DuckDBPyConnection,
    left: str,
    right: str,
    relation: str,
    key: list[str] | None,
    *,
    exact_floats: bool = False,
    left_where: str | None = None,
    left_unread: set[str] | None = None,
    right_unread: set[str] | None = None,
    left_name: str = "DuckDB",
    right_name: str = "BigQuery",
) -> Result:
    """Compare one relation held in two attached catalogs; `left` is DuckDB's build.
    `left_where` holds the left side to some of its rows.
    `left_unread` and `right_unread` name the JSON columns a side has in BigQuery and that
    were not read back: such a column is present on that side, though not in the catalog."""
    left_unread, right_unread = left_unread or set(), right_unread or set()
    left_from = qualified(left, relation)
    if left_where:
        left_from = f"(select * from {left_from} where {left_where})"
    left_columns, right_columns = columns(con, left, relation), columns(con, right, relation)
    result = Result(
        relation=relation,
        left_rows=count_rows(con, left, relation, left_where),
        right_rows=count_rows(con, right, relation),
    )
    # JSON columns first, by schema alone: a side's are those its catalog types JSON and
    # those BigQuery's schema listed and that were not read back. They are never compared
    # by value; both sides must have the column, and have it as JSON.
    left_json = {n for n, t in left_columns.items() if is_uncompared(t)} | left_unread
    right_json = {n for n, t in right_columns.items() if is_uncompared(t)} | right_unread
    for name in sorted(left_json | right_json):
        if name in left_json and name in right_json:
            result.uncompared.append(name)
        elif name in left_json:
            other = right_columns.get(name)
            result.problems.append(
                f"{name}: only in {left_name}"
                if other is None
                else f"{name}: JSON in {left_name}, {kind(other)} in {right_name}"
            )
        else:
            other = left_columns.get(name)
            result.problems.append(
                f"{name}: only in {right_name}"
                if other is None
                else f"{name}: {kind(other)} in {left_name}, JSON in {right_name}"
            )
    json_names = left_json | right_json

    shared: dict[str, str] = {}
    for name, data_type in left_columns.items():
        if name in json_names:
            continue
        if name not in right_columns:
            result.problems.append(f"{name}: only in {left_name}")
        elif kind(data_type) != kind(right_columns[name]):
            result.problems.append(
                f"{name}: {kind(data_type)} in {left_name}, "
                f"{kind(right_columns[name])} in {right_name}"
            )
        else:
            shared[name] = kind(data_type)
    result.problems.extend(
        f"{name}: only in {right_name}"
        for name in right_columns
        if name not in left_columns and name not in json_names
    )

    float_names = [] if exact_floats else [n for n, k in shared.items() if k == "float"]
    exact = {name: k for name, k in shared.items() if name not in float_names}
    if exact:
        selection = ", ".join(f"{_comparable(n, k)} as {quote(n)}" for n, k in exact.items())
        left_sql = f"select {selection} from {left_from}"
        right_sql = f"select {selection} from {qualified(right, relation)}"
        result.only_left = count_except(con, left_sql, right_sql)
        result.only_right = count_except(con, right_sql, left_sql)
        group_columns = GROUPS.get(relation.split(".")[-1], [])
        if (
            group_columns
            and (result.only_left or result.only_right)
            and all(n in exact for n in group_columns)
        ):
            list_differing_groups(con, result, left_sql, right_sql, group_columns)
    if not float_names:
        return result
    if not key or any(name not in shared for name in key):
        result.problems.append("float columns and no declared unique key")
        return result

    on = " and ".join(f"l.{quote(n)} is not distinct from r.{quote(n)}" for n in key)
    joined = f"from {left_from} as l inner join {qualified(right, relation)} as r on {on}"
    pairs = int(con.execute(f"select count(*) {joined}").fetchone()[0])  # type: ignore[index]
    result.unjoined = (result.left_rows - pairs) + (result.right_rows - pairs)
    for name in float_names:
        a, b = f"l.{quote(name)}", f"r.{quote(name)}"
        difference = f"abs({a} - {b})"
        within = (
            f"({difference} <= {RELATIVE_TOLERANCE} * greatest(abs({a}), abs({b})) "
            f"or (abs({a}) < {NEAR_ZERO} and abs({b}) < {NEAR_ZERO} "
            f"and {difference} <= {ABSOLUTE_TOLERANCE}))"
        )
        row = con.execute(
            f"select count(*), "
            f"count(case when {a} is not distinct from {b} then 1 end), "
            f"count(case when ({a} is null) != ({b} is null) "
            f"or ({a} is not null and {b} is not null and not {within}) then 1 end), "
            f"coalesce(max({difference}), 0), "
            f"coalesce(max(case when greatest(abs({a}), abs({b})) > 0 "
            f"then {difference} / greatest(abs({a}), abs({b})) end), 0) {joined}"
        ).fetchone()
        assert row is not None
        result.floats[name] = FloatColumn(
            compared=int(row[0]),
            exactly_equal=int(row[1]),
            beyond_tolerance=int(row[2]),
            largest_absolute=float(row[3]),
            largest_relative=float(row[4]),
        )
    return result


def list_differing_groups(
    con: duckdb.DuckDBPyConnection,
    result: Result,
    left_sql: str,
    right_sql: str,
    group_columns: list[str],
) -> None:
    """Fill `result` with the groups that hold a row on one side only, up to
    MAX_GROUPS_LISTED, each with all its rows on both sides. The sql arguments select the
    same columns, comparable on both sides, the group columns among them."""
    names = ", ".join(quote(n) for n in group_columns)
    differing = con.execute(
        f"select distinct {names} from ("
        f"(select * from ({left_sql}) except all (select * from ({right_sql}))) "
        f"union all (select * from ({right_sql}) except all (select * from ({left_sql})))"
        f") order by {names}"
    ).fetchall()
    result.group_columns = group_columns
    result.groups_not_listed = max(0, len(differing) - MAX_GROUPS_LISTED)
    where = " and ".join(f"{quote(n)} is not distinct from ?" for n in group_columns)
    for group in differing[:MAX_GROUPS_LISTED]:
        sides = [
            con.execute(f"select * from ({sql}) where {where} order by all", list(group)).fetchall()
            for sql in (left_sql, right_sql)
        ]
        result.differing_groups.append(GroupDifference(tuple(group), sides[0], sides[1]))


def unique_key(manifest: dict[str, Any], unique_id: str) -> list[str] | None:
    """The columns of a model's declared unique key, from its tests in dbt's manifest."""
    for node in manifest["nodes"].values():
        if node.get("resource_type") != "test" or node.get("attached_node") != unique_id:
            continue
        metadata = node.get("test_metadata") or {}
        if metadata.get("name") == "unique":
            return [str(metadata["kwargs"]["column_name"])]
        if metadata.get("name") == "unique_combination_of_columns":
            return [str(name) for name in metadata["kwargs"]["combination_of_columns"]]
    return None


# -- what is compared, and reading BigQuery back --------------------------------------------


def selected_relations(target_path: Path) -> list[tuple[str, str, list[str] | None]]:
    """(schema, name, unique key) of every relation the selector selects, from dbt: its models
    and its seeds (spec 0135). A seed's key is read from its tests as a model's is; a seed with no
    float column needs none."""
    dbt = Path(sys.executable).parent / "dbt"
    listed = subprocess.run(
        [
            str(dbt),
            "ls",
            "--selector",
            SELECTOR,
            "--resource-type",
            "model",
            "--resource-type",
            "seed",
        ]
        + ["--output", "json"]
        + ["--output-keys", "unique_id name schema config", "-q"]
        + ["--target", "dev", "--target-path", str(target_path)],
        cwd=DBT_ROOT,
        env={**os.environ, "DBT_PROFILES_DIR": str(DBT_ROOT)},
        capture_output=True,
        text=True,
        check=True,
    )
    manifest = json.loads((target_path / "manifest.json").read_text())
    relations = []
    for line in listed.stdout.splitlines():
        if not line.startswith("{"):
            continue
        node = json.loads(line)
        if node["config"]["materialized"] == "ephemeral":
            continue
        key = unique_key(manifest, node["unique_id"])
        relations.append((str(node["schema"]), str(node["name"]), key))
    return sorted(relations)


def fields_read_back(schema: Any) -> list[Any]:
    """The fields of a BigQuery relation that are read back: every one that is neither
    JSON nor nested (6.)."""
    return [f for f in schema if not _bq_uncompared(f)]


def fields_left_unread(schema: Any) -> set[str]:
    """The names of the JSON and nested fields of a BigQuery relation, not read back."""
    return {f.name for f in schema if _bq_uncompared(f)}


def read_back(
    con: duckdb.DuckDBPyConnection,
    project: str,
    catalog: str,
    relations: list[tuple[str, str, list[str] | None]],
    suffix: str = "",
) -> dict[str, set[str]]:
    """Copy each BigQuery relation into `catalog`, under the schema names DuckDB uses.
    Returns, per `schema.name`, the JSON columns BigQuery's schema lists and that were not
    read: the comparison needs to know they exist."""
    unread: dict[str, set[str]] = {}
    from google.cloud import bigquery

    client = bigquery.Client(project=project, location="US")
    for schema, name, _ in relations:
        table_id = f"{project}.{schema}{suffix}.{name}"
        table = client.get_table(table_id)
        fields = fields_read_back(table.schema)
        unread[f"{schema}.{name}"] = fields_left_unread(table.schema)
        if table.table_type == "VIEW":
            config = bigquery.QueryJobConfig(maximum_bytes_billed=MAXIMUM_BYTES_BILLED)
            selection = ", ".join(f"`{f.name}`" for f in fields)
            job = client.query(f"select {selection} from `{table_id}`", job_config=config)
            arrow = job.result().to_arrow()
            print(f"queried view {schema}{suffix}.{name}: {job.total_bytes_billed} bytes billed")
        else:
            arrow = client.list_rows(table, selected_fields=fields).to_arrow()
        con.register("_arrow", arrow)
        con.execute(f"create schema if not exists {quote(catalog)}.{quote(schema)}")
        con.execute(
            f"create table {quote(catalog)}.{quote(schema)}.{quote(name)} as select * from _arrow"
        )
        con.unregister("_arrow")
    return unread


def describe(result: Result, left_name: str, right_name: str) -> list[str]:
    status = "ok  " if result.passed else "FAIL"
    lines = [
        f"{status} {result.relation}: rows {result.left_rows} / {result.right_rows}; "
        f"only in {left_name} {result.only_left}, only in {right_name} {result.only_right}"
        + (f"; rows with no partner on the key {result.unjoined}" if result.unjoined else "")
    ]
    lines.extend(f"       {problem}" for problem in result.problems)
    for difference in result.differing_groups:
        label = ", ".join(
            f"{name}={value}"
            for name, value in zip(result.group_columns, difference.group, strict=True)
        )
        lines.append(f"       differs: {label}")
        for side, rows in ((left_name, difference.left_rows), (right_name, difference.right_rows)):
            lines.append(f"         {side}: {rows}")
    if result.groups_not_listed:
        lines.append(
            f"       ... and {result.groups_not_listed} more that differ "
            f"(the first {MAX_GROUPS_LISTED} are listed)"
        )
    if result.uncompared:
        lines.append(f"       JSON or nested columns not compared: {', '.join(result.uncompared)}")
    for name, column in result.floats.items():
        lines.append(
            f"       float {name}: {column.compared} compared, {column.exactly_equal} "
            f"exactly equal, {column.beyond_tolerance} beyond tolerance, largest difference "
            f"{column.largest_absolute:.3g} absolute, {column.largest_relative:.3g} relative"
        )
    return lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", type=Path, required=True, help="the local warehouse")
    parser.add_argument("--project", required=True, help="the BigQuery project id")
    parser.add_argument(
        "--bq-against-bq",
        metavar="SUFFIX",
        help="compare the BigQuery build with the one built under this schema suffix, exactly",
    )
    parser.add_argument(
        "--suffix",
        default="",
        help="read the BigQuery build from the datasets of this schema suffix (fo_schema_suffix)",
    )
    args = parser.parse_args(argv)
    with tempfile.TemporaryDirectory() as scratch:
        relations = selected_relations(Path(scratch) / "dbt_target")
        con = duckdb.connect()
        con.execute(f"attach '{Path(scratch) / 'bq.duckdb'}' as bq")
        unread = read_back(con, args.project, "bq", relations, args.suffix)
        left_unread: dict[str, set[str]] = {}
        if args.bq_against_bq:
            con.execute(f"attach '{Path(scratch) / 'bq_second.duckdb'}' as bq_second")
            left_unread = unread
            unread = read_back(con, args.project, "bq_second", relations, args.bq_against_bq)
            left, right = "bq", "bq_second"
            names = ("BigQuery", f"BigQuery{args.bq_against_bq}")
        else:
            left = view_catalog(args.db)
            con.execute(f"attach '{args.db}' as {quote(left)} (read_only)")
            right, names = "bq", ("DuckDB", "BigQuery")
        failed = total_rows = 0
        for schema, name, key in relations:
            result = compare_relation(
                con,
                left,
                right,
                f"{schema}.{name}",
                key,
                exact_floats=bool(args.bq_against_bq),
                left_unread=left_unread.get(f"{schema}.{name}"),
                right_unread=unread.get(f"{schema}.{name}"),
                left_name=names[0],
                right_name=names[1],
            )
            print("\n".join(describe(result, *names)))
            failed += not result.passed
            total_rows += result.left_rows
        print(
            f"compared {len(relations)} relations, {total_rows} rows in {names[0]}: "
            f"{len(relations) - failed} pass, {failed} fail"
        )
        return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
