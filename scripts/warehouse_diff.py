"""Compare relations between DuckDB warehouses, as multisets.

Shared by scripts/compare_warehouses.py and scripts/check_tenant_isolation.py. Pure
functions over one connection with the warehouses ATTACHED.

Attach a warehouse file under its own stem (`attach` does): DuckDB views store the name
of the catalog they were created in, so a file attached under any other name fails with
`Catalog "..." does not exist` the moment a view is queried. That suits files each built
under its own name. A COPY of a warehouse (warehouse_before.duckdb) has views that still
name the original's catalog, and next to that original its views would read the original's
tables. `materialise` handles both: it opens one file alone, under the catalog its views
name (`view_catalog`), and copies its relations into a scratch database, which is what
compare_warehouses.py compares.

Comparison is EXCEPT ALL both ways, never plain EXCEPT: EXCEPT compares sets and would call
the rows A, A, B, C and A, B, B, C equal.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import duckdb

SCHEMAS = ("staging", "intermediate", "marts", "reconciliation")
FLOAT_TYPES = ("DOUBLE", "FLOAT")


def attach(con: duckdb.DuckDBPyConnection, path: Path | str) -> str:
    """Attach a warehouse read-only under its file stem; returns the catalog name."""
    catalog = Path(path).stem
    con.execute(f"attach '{path}' as \"{catalog}\" (read_only)")
    return catalog


IDENT = r'(?:"(?:[^"]|"")+"|[A-Za-z_][A-Za-z0-9_$]*)'
THREE_PART = re.compile(f"({IDENT})\\s*\\.\\s*({IDENT})\\s*\\.\\s*{IDENT}")
BUILT_IN_CATALOGS = {"system", "temp", "memory"}
# One left-to-right scan: at each position the first alternative that matches wins, so a
# quoted identifier swallows any `--` or `'` inside it, and a string literal any `"`.
SQL_TEXT = re.compile(
    r"""(?P<ident>"(?:[^"]|"")*")|(?P<drop>'(?:[^']|'')*'|--[^\n]*|/\*.*?\*/)""",
    re.DOTALL,
)


def strip_literals_and_comments(sql: str) -> str:
    """The SQL without single-quoted string literals and comments; identifiers stay."""
    return SQL_TEXT.sub(lambda m: m["ident"] or " ", sql)


def unquote(ident: str) -> str:
    return ident[1:-1].replace('""', '"') if ident.startswith('"') else ident


def view_catalogs(path: Path | str) -> set[str]:
    """The catalogs a file's views name in three-part names (catalog.schema.name).

    String literals and comments are removed from each view's SQL first, so catalog-shaped
    text in them names nothing. A match then counts only if its middle part is a schema of
    the file. Opens the file read-only on its own.
    """
    con = duckdb.connect(str(path), read_only=True)
    try:
        schemas = {
            row[0] for row in con.execute("select schema_name from duckdb_schemas()").fetchall()
        }
        sqls = con.execute("select sql from duckdb_views() where not internal").fetchall()
    finally:
        con.close()
    found = set()
    for (sql,) in sqls:
        for catalog, schema in (
            (unquote(m[0]), unquote(m[1]))
            for m in THREE_PART.findall(strip_literals_and_comments(sql))
        ):
            if schema in schemas and catalog.lower() not in BUILT_IN_CATALOGS:
                found.add(catalog)
    return found


def view_catalog(path: Path | str) -> str:
    """The one catalog a file's views expect; the file's stem if it has no views.

    Raises ValueError, naming the file and the catalogs, if its views name more than one.
    """
    catalogs = view_catalogs(path)
    if len(catalogs) > 1:
        raise ValueError(
            f"{path}: its views name more than one catalog ({', '.join(sorted(catalogs))})"
        )
    return next(iter(catalogs), Path(path).stem)


def materialise(path: Path | str, scratch: Path | str) -> None:
    """Copy a warehouse's tables and views, as tables, into a new scratch database.

    The warehouse is attached read-only under the catalog its views name, in a connection
    where it is the only warehouse. The scratch holds the model schemas under the same
    names and column types, so it is compared like any warehouse (attach it with `attach`).
    """
    catalog = view_catalog(path)
    con = duckdb.connect()
    try:
        con.execute(f"attach '{path}' as {quote(catalog)} (read_only)")
        relations = sorted(list_relations(con, catalog))
        con.execute(f"use {quote(catalog)}")
        con.execute(f"attach '{scratch}' as scratch")
        for schema in SCHEMAS:
            con.execute(f"create schema if not exists scratch.{quote(schema)}")
        for relation in relations:
            con.execute(
                f"create table {qualified('scratch', relation)} as "
                f"select * from {qualified(catalog, relation)}"
            )
    finally:
        con.close()


def list_relations(con: duckdb.DuckDBPyConnection, catalog: str) -> set[str]:
    """Tables and views of the model schemas, as `schema.name`."""
    placeholders = ", ".join("?" for _ in SCHEMAS)
    rows = con.execute(
        "select table_schema, table_name from information_schema.tables "
        f"where table_catalog = ? and table_schema in ({placeholders})",
        [catalog, *SCHEMAS],
    ).fetchall()
    return {f"{schema}.{name}" for schema, name in rows}


def columns(con: duckdb.DuckDBPyConnection, catalog: str, relation: str) -> dict[str, str]:
    """Column name -> type, in column order."""
    schema, name = relation.split(".")
    rows = con.execute(
        "select column_name, data_type from information_schema.columns "
        "where table_catalog = ? and table_schema = ? and table_name = ? "
        "order by ordinal_position",
        [catalog, schema, name],
    ).fetchall()
    return {column: data_type for column, data_type in rows}


def quote(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def qualified(catalog: str, relation: str) -> str:
    schema, name = relation.split(".")
    return f"{quote(catalog)}.{quote(schema)}.{quote(name)}"


@dataclass
class RelationDiff:
    relation: str
    left_rows: int
    right_rows: int
    only_left: int
    only_right: int
    left_only_columns: list[str] = field(default_factory=list)
    right_only_columns: list[str] = field(default_factory=list)
    shared_columns: list[str] = field(default_factory=list)

    @property
    def differs(self) -> bool:
        """A row or count difference. A column on one side only is not one."""
        return bool(self.only_left or self.only_right or self.left_rows != self.right_rows)


def select_list(cols: dict[str, str], names: list[str], round_doubles: int | None) -> str:
    parts = []
    for name in names:
        if round_doubles is not None and cols[name].upper() in FLOAT_TYPES:
            parts.append(f"round({quote(name)}, {round_doubles}) as {quote(name)}")
        else:
            parts.append(quote(name))
    return ", ".join(parts)


def sql_select(catalog: str, relation: str, selection: str, where: str | None) -> str:
    clause = f" where {where}" if where else ""
    return f"select {selection} from {qualified(catalog, relation)}{clause}"


def count_rows(
    con: duckdb.DuckDBPyConnection, catalog: str, relation: str, where: str | None = None
) -> int:
    row = con.execute("select count(*) from (" + sql_select(catalog, relation, "*", where) + ")")
    return int(row.fetchone()[0])  # type: ignore[index]


def compare_relation(
    con: duckdb.DuckDBPyConnection,
    left: str,
    right: str,
    relation: str,
    *,
    left_where: str | None = None,
    right_where: str | None = None,
    round_doubles: int | None = None,
) -> RelationDiff:
    """Compare one relation over the columns both sides have, as multisets."""
    left_cols, right_cols = columns(con, left, relation), columns(con, right, relation)
    shared = [c for c in left_cols if c in right_cols]
    diff = RelationDiff(
        relation=relation,
        left_rows=count_rows(con, left, relation, left_where),
        right_rows=count_rows(con, right, relation, right_where),
        only_left=0,
        only_right=0,
        left_only_columns=[c for c in left_cols if c not in right_cols],
        right_only_columns=[c for c in right_cols if c not in left_cols],
        shared_columns=shared,
    )
    if shared:
        left_sql = sql_select(
            left, relation, select_list(left_cols, shared, round_doubles), left_where
        )
        right_sql = sql_select(
            right, relation, select_list(right_cols, shared, round_doubles), right_where
        )
        diff.only_left = count_except(con, left_sql, right_sql)
        diff.only_right = count_except(con, right_sql, left_sql)
    return diff


def count_except(con: duckdb.DuckDBPyConnection, left_sql: str, right_sql: str) -> int:
    row = con.execute(f"select count(*) from ({left_sql} except all {right_sql})").fetchone()
    return int(row[0]) if row else 0


def rows_missing_from(
    con: duckdb.DuckDBPyConnection,
    left: str,
    right: str,
    relation: str,
    *,
    left_where: str | None = None,
    right_where: str | None = None,
) -> int:
    """Rows of left that right does not hold (EXCEPT ALL one way), over shared columns."""
    left_cols, right_cols = columns(con, left, relation), columns(con, right, relation)
    shared = [c for c in left_cols if c in right_cols]
    if not shared:
        return 0
    selection = ", ".join(quote(c) for c in shared)
    return count_except(
        con,
        sql_select(left, relation, selection, left_where),
        sql_select(right, relation, selection, right_where),
    )
