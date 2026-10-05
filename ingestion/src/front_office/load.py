"""Load the landing zone into raw.api_responses.

One row per API response, payload kept as JSON. The table is append-only: a re-fetch of
the same request gets a new fetched_at and therefore a new row, so history is never
overwritten and "what did ESPN say on this date?" stays answerable. dbt does the parsing.

A response is identified by source, endpoint, request path, parameters and fetch time
(ADR 0011). Two different files with one key are an error, never a silent first-wins.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Sequence
from pathlib import Path

import duckdb

from front_office.landing import LandingZone

logger = logging.getLogger(__name__)

SCHEMA = "raw"
TABLE = "api_responses"
QUALIFIED = f"{SCHEMA}.{TABLE}"
REQUIRED_META = ("source", "endpoint", "fetched_at", "url")
KEY_COLUMNS = ("source", "endpoint", "request_path", "request_key", "fetched_at")

CREATE_SQL = f"""
create schema if not exists {SCHEMA};
create table if not exists {QUALIFIED} (
    source varchar not null,
    endpoint varchar not null,
    request_path varchar not null,
    request_key varchar not null,
    fetched_at varchar not null,
    partitions json not null,
    payload json not null,
    file_path varchar not null,
    primary key (source, endpoint, request_path, request_key, fetched_at)
);
"""


class RawKeyCollision(Exception):
    """Two different files claim one raw key; loading either would silently lose the other."""


class RawSchemaOutdated(Exception):
    """The warehouse's raw table predates request_path and cannot take the new rows."""


def load_landing_zone(
    con: duckdb.DuckDBPyConnection,
    zone: LandingZone,
    *,
    source: str | None = None,
    endpoint: str | None = None,
) -> int:
    """Insert every landed response not already present. Returns the number inserted.

    Raises RawSchemaOutdated if the raw table has the pre-request_path shape, and
    RawKeyCollision if two different files share a key; in both cases nothing is changed.
    """
    _refuse_old_table(con)
    con.execute(CREATE_SQL)

    rows = []
    skipped = 0
    for landed in zone.iter_landed(source=source, endpoint=endpoint):
        # A response with no complete metadata sidecar has no key: it was landed outside
        # the ingestion package (e.g. by a throwaway spike script). Those files are
        # backups, not pipeline inputs, so they are skipped rather than loaded with empty
        # keys. request_key and partitions are legitimately empty for some endpoints, so
        # they only have to be present, not truthy.
        meta = landed.meta
        loadable = (
            "request_key" in meta
            and isinstance(meta.get("partitions"), dict)
            and all(meta.get(field) for field in REQUIRED_META)
        )
        if not loadable:
            skipped += 1
            continue
        rows.append(
            (
                meta["source"],
                meta["endpoint"],
                LandingZone.request_path(meta["url"]),
                meta["request_key"],
                meta["fetched_at"],
                json.dumps(meta["partitions"]),
                json.dumps(landed.payload),
                str(landed.path),
            )
        )
    if skipped:
        logger.warning("skipped %s landed file(s) with no complete metadata sidecar", skipped)
    if not rows:
        return 0

    _raise_on_collision(con, rows)
    new_rows = [row for row in rows if not _exists(con, row)]
    if new_rows:
        con.executemany(f"insert into {QUALIFIED} values (?, ?, ?, ?, ?, ?, ?, ?)", new_rows)
    return len(new_rows)


def _refuse_old_table(con: duckdb.DuckDBPyConnection) -> None:
    columns = {
        name
        for (name,) in con.execute(
            "select column_name from information_schema.columns "
            "where table_schema = ? and table_name = ?",
            [SCHEMA, TABLE],
        ).fetchall()
    }
    if columns and "request_path" not in columns:
        raise RawSchemaOutdated(
            f"{QUALIFIED} in this warehouse has the old shape (no request_path column). "
            "Load into a new warehouse file instead (use --db); the table is left unchanged."
        )


def _raise_on_collision(con: duckdb.DuckDBPyConnection, rows: Sequence[tuple[str, ...]]) -> None:
    """Fail if two files in the batch, or a file and an existing row, share a key."""
    seen: dict[tuple[str, ...], str] = {}
    for row in rows:
        key, file_path = row[:5], row[7]
        if key in seen and seen[key] != file_path:
            raise RawKeyCollision(_collision_message(key, seen[key], file_path))
        seen[key] = file_path
    for row in rows:
        existing = con.execute(
            f"select file_path from {QUALIFIED} where "
            + " and ".join(f"{c} = ?" for c in KEY_COLUMNS),
            list(row[:5]),
        ).fetchone()
        if existing and existing[0] != row[7]:
            raise RawKeyCollision(_collision_message(row[:5], existing[0], row[7]))


def _collision_message(key: tuple[str, ...], first: str, second: str) -> str:
    named = ", ".join(f"{column}={value!r}" for column, value in zip(KEY_COLUMNS, key, strict=True))
    return (
        f"two files share one raw key ({named}): {first} and {second}. "
        "Nothing was loaded; remove or fix one of them."
    )


def _exists(con: duckdb.DuckDBPyConnection, row: tuple[str, ...]) -> bool:
    found = con.execute(
        f"select 1 from {QUALIFIED} where " + " and ".join(f"{c} = ?" for c in KEY_COLUMNS),
        list(row[:5]),
    ).fetchone()
    return found is not None


def connect(db_path: Path | str) -> duckdb.DuckDBPyConnection:
    """Open (creating if needed) the DuckDB warehouse file."""
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    return duckdb.connect(str(path))
