"""Check the dashboard's queries: they compute nothing, read only the exposure's marts, and run.

Spec 0232 R4.1-R4.3 and R7.1 (ADR 0147). The dashboard's pages read one extract of the marts
(`front_office.extract`), and each page runs queries from
dashboard/front_office_dashboard/queries/*.sql, one query per file, DuckDB SQL with named
parameters (`$season`). A query's leading `--` comments may hold

    -- example: {"season": 2026, "team_id": 1}     a value for every $parameter it uses
    -- may-be-empty: <reason>                      the query may return no rows on fixtures

The rules, read from the parsed query (sqlglot), CTEs and subqueries included:

  R4.1  every table is `marts.<name>`; no other schema, no bare table, no table function
        (`read_csv`, `read_parquet`...), no `attach`, one statement.
  R4.2  no GROUP BY, HAVING, QUALIFY, window, or aggregate, and no arithmetic whose two sides
        between them hold two or more distinct columns, wherever it stands. The marts hold
        every number; the dashboard only selects, joins, filters and sorts. Arithmetic
        between a column and a literal (`season - 1`) is allowed.
  R4.3  the marts the queries read are exactly the `front_office_dashboard` exposure's refs.
  R7.1  an extract of --db is made, as the app's is, and every query runs on it with its
        example parameters, and returns a row unless it says may-be-empty.
  R7.3  every table of that extract equals its source mart in --db: `except all` both ways,
        any differing row failing, the table and the two counts named.
  R7.2  when the queries sit beside an `app.py` (the dashboard's), every page is rendered
        headless (Streamlit's AppTest) over that extract: no exception, no error element, the
        freshness banner on each, no stale warning on a fresh extract; and an extract planted
        37 hours old, at a fixed time in May, shows the stale warning on every page (R6.2).

Without a `queries/` directory there is nothing to check yet: it says so and exits 0. A
directory that exists and holds no query is a failure. Every problem is printed, not just the
first. Exit 1 if there is any.

Usage:  uv run python scripts/check_dashboard.py --db dbt/ci.duckdb
        [--queries-dir dashboard/front_office_dashboard/queries] [--exposures PATH]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import duckdb
import sqlglot
from sqlglot import exp

from front_office.extract import (
    DEFAULT_EXPOSURES,
    DuckDBMartReader,
    ExtractRefused,
    dashboard_tables,
    extract,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_QUERIES = REPO_ROOT / "dashboard" / "front_office_dashboard" / "queries"
SCHEMA = "marts"

_EXAMPLE = re.compile(r"--\s*example:\s*(.*)", re.IGNORECASE)
_MAY_BE_EMPTY = re.compile(r"--\s*may-be-empty:\s*(.*)", re.IGNORECASE)
_ARITHMETIC = (exp.Add, exp.Sub, exp.Mul, exp.Div, exp.IntDiv, exp.Mod, exp.Pow)


@dataclass
class QueryReport:
    """One query file: what it reads, what its header says, and what is wrong with it."""

    name: str
    sql: str
    tables: set[str] = field(default_factory=set)
    example: dict[str, Any] | None = None
    may_be_empty: str | None = None
    problems: list[str] = field(default_factory=list)


def _header(sql: str) -> tuple[dict[str, Any] | None, str | None, list[str]]:
    """The example parameters and the may-be-empty reason from the leading comment lines."""
    example: dict[str, Any] | None = None
    may_be_empty: str | None = None
    problems: list[str] = []
    for line in sql.splitlines():
        line = line.strip()
        if not line:
            continue
        if not line.startswith("--"):
            break
        found = _EXAMPLE.fullmatch(line)
        if found:
            try:
                value = json.loads(found.group(1))
            except ValueError:
                value = None
            if isinstance(value, dict):
                example = value
            else:
                problems.append("example is not a JSON object")
            continue
        found = _MAY_BE_EMPTY.fullmatch(line)
        if found:
            if found.group(1).strip():
                may_be_empty = found.group(1).strip()
            else:
                problems.append("may-be-empty gives no reason")
    return example, may_be_empty, problems


def _columns(node: exp.Expression) -> set[tuple[str, str]]:
    return {(c.table.lower(), c.name.lower()) for c in node.find_all(exp.Column)}


def _rules(statement: exp.Expression) -> tuple[list[str], set[str], set[str]]:
    """Problems (constructs), the marts read, and the parameter names, from one statement."""
    problems: list[str] = []
    marts: set[str] = set()
    parameters: set[str] = set()
    ctes = {c.alias.lower() for c in statement.find_all(exp.CTE)}
    for node in statement.walk():
        if isinstance(node, exp.Table):
            name = node.name
            if not isinstance(node.this, exp.Identifier):
                problems.append(f"table function {node.this.sql('duckdb')[:40]} is not allowed")
            elif node.catalog or (node.db and node.db.lower() != SCHEMA):
                problems.append(
                    f"table {node.sql('duckdb')} is not {SCHEMA}.<name> (schema {SCHEMA} only)"
                )
            elif node.db:
                marts.add(name)
            elif name.lower() not in ctes:
                problems.append(f"table {name} is not schema-qualified ({SCHEMA}.{name})")
        elif isinstance(node, exp.Group):
            problems.append("group by is not allowed (the marts hold the aggregates)")
        elif isinstance(node, exp.Having):
            problems.append("having is not allowed")
        elif isinstance(node, exp.Qualify):
            problems.append("qualify is not allowed")
        elif isinstance(node, exp.Window):
            problems.append("window function is not allowed")
        elif isinstance(node, exp.AggFunc):
            problems.append(f"aggregate {node.sql_name().lower()}() is not allowed")
        elif isinstance(node, _ARITHMETIC):
            if len(_columns(node)) >= 2:
                problems.append(
                    f"arithmetic across columns is not allowed: {node.sql('duckdb')[:60]}"
                )
        elif isinstance(node, exp.Placeholder):
            if node.name:
                parameters.add(node.name)
            else:
                problems.append("a positional parameter ? is not allowed; name it ($name)")
    return list(dict.fromkeys(problems)), marts, parameters


def analyse(name: str, sql: str) -> QueryReport:
    """Hold one query's text to R4.1 and R4.2 and to its header; nothing is run."""
    report = QueryReport(name, sql)
    report.example, report.may_be_empty, found = _header(sql)
    problems = list(found)
    try:
        statements = [s for s in sqlglot.parse(sql, read="duckdb") if s is not None]
    except sqlglot.errors.SqlglotError as error:
        report.problems = [f"{name}: cannot parse: {str(error).splitlines()[0]}"]
        return report
    if len(statements) != 1:
        problems.append(f"the file must hold one statement, found {len(statements)}")
    for statement in statements[:1]:
        if not isinstance(statement, exp.Query):
            problems.append(f"{type(statement).__name__.lower()} statement is not a select")
            continue
        constructs, report.tables, parameters = _rules(statement)
        problems.extend(constructs)
        given = set(report.example or {})
        for parameter in sorted(parameters - given):
            problems.append(f"parameter ${parameter} has no value in the example header")
        for parameter in sorted(given - parameters):
            problems.append(f"example gives {parameter}, which the query does not use")
    report.problems = [f"{name}: {p}" for p in problems]
    return report


def load_queries(queries_dir: Path) -> tuple[list[QueryReport], list[str]] | None:
    """Every query file analysed; None if the directory does not exist."""
    if not queries_dir.is_dir():
        return None
    files = sorted(queries_dir.glob("*.sql"))
    problems = [] if files else [f"{queries_dir}: no queries (an empty directory checks nothing)"]
    return [analyse(p.name, p.read_text()) for p in files], problems


EXTRACT_INFO = "extract_info"


def check_exposure(reports: list[QueryReport], exposures: Path) -> list[str]:
    """R4.3: the marts read, across every query, equal the exposure's refs; both ways."""
    try:
        declared = set(dashboard_tables(exposures))
    except ExtractRefused as error:
        return [str(error)]
    read: dict[str, list[str]] = {}
    for report in reports:
        for table in report.tables:
            # The extract's own table (when it was made, from which build) is not a mart: the
            # freshness banner reads it (R6.1), and no exposure names it.
            if table != EXTRACT_INFO:
                read.setdefault(table, []).append(report.name)
    problems = [
        f"{table}: read by {', '.join(sorted(read[table]))}, which the exposure does not name"
        for table in sorted(set(read) - declared)
    ]
    problems += [
        f"{table}: the exposure names it, but no query reads it"
        for table in sorted(declared - set(read))
    ]
    return problems


def run_queries(
    db: Path, reports: list[QueryReport], exposures: Path, app: Path | None = None
) -> list[str]:
    """R7.1: extract --db as the app's extract is made, open it read-only, run each query that
    passed the static rules with its example, and require a row unless it may be empty. With an
    `app`, and every query clean, R7.2 then renders its pages over the same extract."""
    runnable = [r for r in reports if not r.problems]
    if not runnable:
        return []
    try:
        tables = dashboard_tables(exposures)
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory) / "extract.duckdb"
            reader = DuckDBMartReader(db)
            try:
                extract(reader, tables, out)
            finally:
                reader.close()
            problems = _compare_with_source(out, db, tables)
            problems += _run_on(out, runnable)
            if app is not None and len(runnable) == len(reports):
                problems += render_pages(out, app)
            return problems
    except ExtractRefused as error:
        return [f"extract of {db} refused: {error}"]


def _compare_with_source(extract_file: Path, db: Path, tables: list[str]) -> list[str]:
    """R7.3: each table of the extract has its source mart's columns and types, in order, and
    exactly its rows: `except all` both ways, so a missing, extra or retyped column, or a
    dropped, added or changed row, or a duplicate, is a failure naming the table."""
    problems: list[str] = []
    con = duckdb.connect()
    try:
        con.execute(f"attach '{extract_file}' as ext (read_only)")
        con.execute(f"attach '{db}' as src (read_only)")
        # Names and types: `except all` coerces one type to the other, so a column whose type
        # changed could hold a changed value and still compare equal (round 3).
        listed = (
            "select column_name, data_type from information_schema.columns"
            " where table_catalog = ? and table_schema = 'marts' and table_name = ?"
            " order by ordinal_position"
        )
        for table in tables:
            names = con.execute(listed, ["ext", table]).fetchall()
            source_names = con.execute(listed, ["src", table]).fetchall()
            # The rows are compared over the extract's columns, so the columns themselves must
            # be the source's first: an extract missing one would otherwise compare equal.
            if names != source_names:
                problems.append(
                    f"extract of marts.{table} has columns {[f'{n} {t}' for n, t in names]}, its"
                    f" source {[f'{n} {t}' for n, t in source_names]}"
                )
                continue
            columns = ", ".join(f'"{name}"' for name, _ in names)
            ext = f"select {columns} from ext.marts.{table}"
            src = f"select {columns} from src.marts.{table}"
            (extra,) = con.execute(f"select count(*) from ({ext} except all {src})").fetchone()  # type: ignore[misc]
            (missing,) = con.execute(f"select count(*) from ({src} except all {ext})").fetchone()  # type: ignore[misc]
            if extra or missing:
                problems.append(
                    f"extract of marts.{table} differs from its source: {extra} rows in the"
                    f" extract and not the source, {missing} in the source and not the extract"
                )
    except duckdb.Error as error:
        problems.append(f"comparing the extract with {db}: {str(error).splitlines()[0]}")
    finally:
        con.close()
    return problems


def _run_on(extract_file: Path, reports: list[QueryReport]) -> list[str]:
    problems: list[str] = []
    con = duckdb.connect(str(extract_file), read_only=True)
    try:
        for report in reports:
            try:
                rows = con.execute(report.sql, report.example or {}).fetchall()
            except duckdb.Error as error:
                problems.append(f"{report.name}: {str(error).splitlines()[0]}")
                continue
            if not rows and report.may_be_empty is None:
                problems.append(f"{report.name}: returned 0 rows with its example parameters")
    finally:
        con.close()
    return problems


BANNER = "Extract made"
STALE_WARNING = "may be stale"
# A fixed in-season "now" (the app reads it from FO_DASHBOARD_NOW) and an extract 37 hours before.
PLANTED_NOW = "2026-05-20T12:00:00+00:00"
PLANTED_AGE_HOURS = 37


@contextmanager
def _environment(**values: str) -> Iterator[None]:
    saved = {k: os.environ.get(k) for k in values}
    os.environ.update(values)
    try:
        yield
    finally:
        for key, old in saved.items():
            if old is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = old


def _page_problems(label: str, at: Any) -> list[str]:
    problems = [f"page {label}: exception: {str(e.value).splitlines()[0]}" for e in at.exception]
    problems += [f"page {label}: error shown: {str(e.value)[:80]}" for e in at.error]
    if not any(str(c.value).startswith(BANNER) for c in at.caption):
        problems.append(f"page {label}: no freshness banner")
    return problems


def _warned(at: Any) -> bool:
    return any(STALE_WARNING in str(w.value) for w in at.warning)


def render_pages(extract_file: Path, app: Path) -> list[str]:
    """R7.2 and R6.2: render the app and each page of `pages/` headless over the extract, then
    plant an old `extracted_at` and require the stale warning. The extract is edited in place, so
    it must be the gate's own temporary copy."""
    try:
        from streamlit.testing.v1 import AppTest
    except ImportError:
        return ["cannot render the pages: streamlit is not installed (uv sync --group dashboard)"]
    pages = sorted(p.name for p in (app.parent / "pages").glob("*.py"))
    problems: list[str] = []
    if not pages:
        return [f"{app.parent / 'pages'}: no pages to render"]
    sys.path.insert(0, str(app.parent.parent))
    try:
        with _environment(FO_DASHBOARD_EXTRACT=str(extract_file)):
            os.environ.pop("FO_DASHBOARD_NOW", None)
            at = AppTest.from_file(str(app), default_timeout=120).run()
            problems += _page_problems("(first)", at)
            if _warned(at):
                problems.append("a stale warning on an extract made a moment ago")
            for page in pages:
                at.switch_page(f"pages/{page}").run()
                problems += _page_problems(page, at)
            problems += _plant_stale(extract_file, app, AppTest, pages)
    finally:
        sys.path.remove(str(app.parent.parent))
    return problems


def _plant_stale(extract_file: Path, app: Path, app_test: Any, pages: list[str]) -> list[str]:
    import streamlit as st

    con = duckdb.connect(str(extract_file))
    try:
        con.execute(
            "update marts.extract_info set extracted_at ="
            f" timestamptz '{PLANTED_NOW}' - interval '{PLANTED_AGE_HOURS} hours'"
        )
        con.execute("checkpoint")
    finally:
        con.close()
    st.cache_data.clear()
    with _environment(FO_DASHBOARD_NOW=PLANTED_NOW):
        at = app_test.from_file(str(app), default_timeout=120).run()
        problems = _page_problems("(planted)", at)
        if not _warned(at):
            problems.append(
                f"an extract {PLANTED_AGE_HOURS} hours old in May shows no stale warning (R6.2)"
            )
        for page in pages:
            at.switch_page(f"pages/{page}").run()
            problems += _page_problems(f"{page} (planted)", at)
            if not _warned(at):
                problems.append(
                    f"page {page}: an extract {PLANTED_AGE_HOURS} hours old in May shows no"
                    " stale warning (R6.2)"
                )
    return problems


def check_all(
    db: Path, queries_dir: Path, exposures: Path, app: Path | None = None
) -> tuple[int, list[str]]:
    """The number of queries checked and every problem, from all four rules."""
    loaded = load_queries(queries_dir)
    if loaded is None:
        return 0, []
    reports, problems = loaded
    for report in reports:
        problems.extend(report.problems)
    if reports:
        problems.extend(check_exposure(reports, exposures))
        problems.extend(run_queries(db, reports, exposures, app))
    return len(reports), problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--queries-dir", type=Path, default=DEFAULT_QUERIES)
    parser.add_argument("--exposures", type=Path, default=DEFAULT_EXPOSURES)
    args = parser.parse_args(argv)
    if not args.queries_dir.is_dir():
        print("no dashboard queries yet")
        return 0
    app = args.queries_dir.parent / "app.py"
    checked, problems = check_all(
        args.db, args.queries_dir, args.exposures, app if app.is_file() else None
    )
    for problem in problems:
        print(problem)
    if problems:
        return 1
    print(f"dashboard queries: {checked} checked, all pass")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
