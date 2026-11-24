"""`front-office extract-marts`: a copy of the dashboard's marts, as one DuckDB file (spec 0232,
R2; ADR 0144).

The dashboard reads this file and never a warehouse. The tables are the models the exposure
`front_office_dashboard` names, and only those. Each is read through a `MartReader`:
BigQuery's by `tabledata.list` (`client.list_rows`, which bills nothing, never a query: the
project is always named explicitly, as in `bigquery.py`), DuckDB's by attaching the warehouse
read-only. The extract is written beside its destination as `<out>.tmp-<pid>` and published by
one rename (`os.replace`), so a reader that has the old file open keeps it (R2.3), and any
error leaves the destination as it was.

Like the upload, this module cuts and copies and interprets nothing: a type it has no mapping
for stops the extract (R2.5) rather than being guessed at. The client library and pyyaml are
imported inside the functions that need them, so the bare package installs without either.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import shutil
import subprocess
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import duckdb

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_EXPOSURES = REPO_ROOT / "dbt" / "models" / "marts" / "_exposures.yml"
EXPOSURE = "front_office_dashboard"
INFO_TABLE = "extract_info"
SCHEMA = "marts"
BATCH_ROWS = 2000

# BigQuery's type names (legacy and standard) to DuckDB's (C9). Nothing else is mapped.
TYPE_MAP = {
    "INTEGER": "BIGINT",
    "INT64": "BIGINT",
    "FLOAT": "DOUBLE",
    "FLOAT64": "DOUBLE",
    "STRING": "VARCHAR",
    "BOOLEAN": "BOOLEAN",
    "BOOL": "BOOLEAN",
    "DATE": "DATE",
    "TIMESTAMP": "TIMESTAMPTZ",
}
# REQUIRED is still a scalar column; REPEATED is an array and is refused.
ACCEPTED_MODES = ("NULLABLE", "REQUIRED")
REF = re.compile(r"""ref\(\s*['"]([^'"]+)['"]\s*\)""")


class ExtractRefused(Exception):
    """The extract stops; the message names the table (and column) and is printed as it is."""


@dataclass(frozen=True)
class MartTable:
    """One table as read: DuckDB column types, when the warehouse last changed it, its rows."""

    columns: list[tuple[str, str]]
    modified: dt.datetime
    rows: Iterable[tuple[Any, ...]]


class MartReader(Protocol):
    def read(self, table: str) -> MartTable:
        """The table, or `ExtractRefused` if it is missing or has a column that cannot map."""
        ...

    def modified(self, table: str) -> dt.datetime:
        """When the warehouse last changed the table, asked again after the read (R2.6)."""
        ...


def _quote(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def dashboard_tables(exposures: Path) -> list[str]:
    """The model names of the dashboard exposure's `ref('…')` dependencies, in file order."""
    import yaml

    document = yaml.safe_load(exposures.read_text())
    for exposure in (document or {}).get("exposures") or []:
        if exposure.get("name") == EXPOSURE:
            tables: list[str] = []
            for dependency in exposure.get("depends_on") or []:
                found = REF.fullmatch(str(dependency).strip())
                if found and found.group(1) not in tables:
                    tables.append(found.group(1))
            if not tables:
                raise ExtractRefused(f"exposure {EXPOSURE} in {exposures} names no model")
            return tables
    raise ExtractRefused(f"no exposure named {EXPOSURE} in {exposures}")


class BigQueryMartReader:
    """Reads `<project>.<dataset>.<table>` by the table read API. `client` is injectable for
    tests; by default it is `bigquery.Client(project=project)`. Never calls `client.query`."""

    def __init__(self, project: str, dataset: str = SCHEMA, client: Any = None) -> None:
        self.project = project
        self.dataset = dataset
        if client is None:
            from google.cloud import bigquery

            client = bigquery.Client(project=project)
        self.client = client

    def modified(self, table: str) -> dt.datetime:
        modified: dt.datetime = self.client.get_table(
            f"{self.project}.{self.dataset}.{table}"
        ).modified
        return modified

    def read(self, table: str) -> MartTable:
        reference = f"{self.project}.{self.dataset}.{table}"
        try:
            described = self.client.get_table(reference)
        except Exception as error:
            # google.api_core's NotFound, by name: the library is not imported at module level.
            if type(error).__name__ == "NotFound":
                raise ExtractRefused(f"table {table}: not found at {reference}") from None
            raise
        columns: list[tuple[str, str]] = []
        for field in described.schema:
            mode = (field.mode or "NULLABLE").upper()
            kind = TYPE_MAP.get(field.field_type.upper())
            if mode not in ACCEPTED_MODES or kind is None:
                raise ExtractRefused(
                    f"table {table}, column {field.name}: BigQuery type {field.field_type} "
                    f"mode {mode} is not one the extract maps"
                )
            columns.append((field.name, kind))
        rows = (tuple(row.values()) for row in self.client.list_rows(reference))
        return MartTable(columns, described.modified, rows)


class DuckDBMartReader:
    """Reads `<dataset>.<table>` of a warehouse file attached read-only; types as they are."""

    def __init__(self, path: Path, dataset: str = SCHEMA) -> None:
        if not path.is_file():
            raise ExtractRefused(f"warehouse {path} does not exist")
        self.path = path
        self.dataset = dataset
        self.connection = duckdb.connect()
        self.connection.execute(f"attach {_literal(str(path))} as src (read_only)")

    def modified(self, table: str) -> dt.datetime:
        return dt.datetime.fromtimestamp(self.path.stat().st_mtime, dt.UTC)

    def read(self, table: str) -> MartTable:
        described = self.connection.execute(
            "select column_name, data_type from information_schema.columns"
            " where table_catalog = 'src' and table_schema = ? and table_name = ?"
            " order by ordinal_position",
            [self.dataset, table],
        ).fetchall()
        if not described:
            raise ExtractRefused(f"table {table}: not found in {self.path} ({self.dataset})")
        modified = self.modified(table)
        query = f"select * from src.{_quote(self.dataset)}.{_quote(table)}"
        return MartTable([(str(n), str(t)) for n, t in described], modified, self._rows(query))

    def _rows(self, query: str) -> Iterator[tuple[Any, ...]]:
        cursor = self.connection.cursor()
        cursor.execute(query)
        while batch := cursor.fetchmany(BATCH_ROWS):
            yield from batch

    def close(self) -> None:
        self.connection.close()


def _literal(text: str) -> str:
    return "'" + text.replace("'", "''") + "'"


def git_commit() -> str:
    """`FO_GIT_COMMIT`, else `git rev-parse HEAD` at the repository root, else `unknown`."""
    from_env = os.environ.get("FO_GIT_COMMIT", "").strip()
    if from_env:
        return from_env
    try:
        done = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    return done.stdout.strip() or "unknown"


def _json_value(value: Any) -> Any:
    """A date or a timestamp as ISO 8601 text, which DuckDB casts back to the column's type."""
    if isinstance(value, dt.date | dt.datetime | dt.time):
        return value.isoformat()
    raise TypeError(f"no JSON form for {type(value).__name__}")


def _write_table(
    target: duckdb.DuckDBPyConnection, name: str, table: MartTable, staging: Path
) -> int:
    """Stage the rows as newline-delimited JSON, then load them in one `read_json`, typed by
    the declared columns. Row-by-row inserts took 4.5 minutes for the real season's 185,546
    rows. Python writes a float as its shortest exact text, so doubles round-trip unchanged.
    A NaN or an infinity stops the extract (`allow_nan=False`): JSON has no form for them."""
    definition = ", ".join(f"{_quote(column)} {kind}" for column, kind in table.columns)
    target.execute(f"create table {SCHEMA}.{_quote(name)} ({definition})")
    names = [column for column, _ in table.columns]
    rows_file = staging / f"{len(list(staging.iterdir()))}.ndjson"
    written = 0
    with rows_file.open("w", encoding="utf-8") as handle:
        for row in table.rows:
            handle.write(
                json.dumps(dict(zip(names, row, strict=True)), default=_json_value, allow_nan=False)
            )
            handle.write("\n")
            written += 1
    if written:
        types = ", ".join(f"{_literal(column)}: {_literal(kind)}" for column, kind in table.columns)
        selected = ", ".join(_quote(column) for column in names)
        target.execute(
            f"insert into {SCHEMA}.{_quote(name)} select {selected} from read_json("
            f"{_literal(str(rows_file))}, format = 'newline_delimited', columns = {{{types}}})"
        )
    rows_file.unlink()
    return written


def extract(reader: MartReader, tables: list[str], out: Path) -> dict[str, int]:
    """Write `tables` from `reader` to `out` by one rename; return the rows written per table.
    On any error the temporary file is removed, `out` is untouched, and `ExtractRefused` names
    the table."""
    out.parent.mkdir(parents=True, exist_ok=True)
    temporary = out.with_name(f"{out.name}.tmp-{os.getpid()}")
    staging = out.with_name(f"{out.name}.tmp-{os.getpid()}.rows")
    counts: dict[str, int] = {}
    try:
        staging.mkdir()
        # The file's catalog is named, so that a file called `marts.*` does not make the
        # schema `marts` ambiguous with it.
        target = duckdb.connect()
        try:
            target.execute(f"attach {_literal(str(temporary))} as extract_target")
            target.execute("use extract_target")
            target.execute(f"create schema {SCHEMA}")
            info: list[tuple[str, int, dt.datetime]] = []
            for name in tables:
                try:
                    table = reader.read(name)
                    counts[name] = _write_table(target, name, table, staging)
                except ExtractRefused:
                    raise
                except Exception as error:
                    raise ExtractRefused(f"table {name}: {error}") from error
                info.append((name, counts[name], table.modified))
            # R2.6: every table must be of one build. A table the warehouse changed since it was
            # read means a build ran meanwhile, and the tables may come from two of them.
            for name, _, read_at in info:
                if reader.modified(name) != read_at:
                    raise ExtractRefused(
                        f"table {name} changed while the extract read it (a build was running): "
                        "nothing published; run it again once the build ends"
                    )
            extracted_at = dt.datetime.now(dt.UTC)
            commit = git_commit()
            target.execute(
                f"create table {SCHEMA}.{INFO_TABLE} (table_name varchar, row_count bigint,"
                " warehouse_modified_at timestamptz, extracted_at timestamptz, git_commit varchar)"
            )
            target.executemany(
                f"insert into {SCHEMA}.{INFO_TABLE} values (?, ?, ?, ?, ?)",
                [(n, c, m, extracted_at, commit) for n, c, m in info],
            )
            target.execute("checkpoint")
        finally:
            target.close()
        temporary.replace(out)  # os.replace: one atomic rename
    except BaseException:
        temporary.unlink(missing_ok=True)
        temporary.with_name(temporary.name + ".wal").unlink(missing_ok=True)
        raise
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    return counts
