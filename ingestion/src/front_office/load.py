"""Load the landing zone into raw.api_responses.

One row per API response, payload kept as JSON. The table is append-only: a re-fetch of
the same request gets a new fetched_at and therefore a new row, so history is never
overwritten and "what did ESPN say on this date?" stays answerable. dbt does the parsing.

A response is identified by source, endpoint, request path, parameters and fetch time
(ADR 0011). Two different files with one key are an error, never a silent first-wins.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

import duckdb

from front_office.landing import VANISHED, LandedResponse, LandingZone

SCHEMA = "raw"
TABLE = "api_responses"
QUALIFIED = f"{SCHEMA}.{TABLE}"
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


# How many new captures are read and inserted at once. A roster payload is about 2.5 MB,
# so a batch is at most a few hundred megabytes of text, whatever the landing zone holds.
BATCH_ROWS = 50


def load_landing_zone(
    con: duckdb.DuckDBPyConnection,
    zone: LandingZone,
    *,
    source: str | None = None,
    endpoint: str | None = None,
    batch_rows: int = BATCH_ROWS,
) -> int:
    """Insert every landed response not already present. Returns the number inserted.

    Raises RawSchemaOutdated if the raw table has the pre-request_path shape,
    RawKeyCollision if two different files share a key, and PayloadNotJson if a new
    committed capture's payload is not JSON; in every case nothing is changed.

    Memory is set by `batch_rows`, not by the landing zone (#149). The first pass reads
    sidecars only: it finds collisions and which captures are new. The second reads the
    payloads of the new ones, a batch at a time, and inserts them in one transaction, so
    a load that fails or is interrupted leaves no row of the run. A payload already in the
    table is never read: the landing zone is checked at rest by `front-office audit`.
    """
    if batch_rows < 1:
        raise ValueError(f"batch_rows must be at least 1, not {batch_rows}")
    _refuse_old_table(con)
    con.execute(CREATE_SQL)

    # iter_landed yields committed captures only (LandingZone.check): anything else under
    # the root, such as a temporary directory or an old-layout file, is not loaded.
    existing = _existing_file_paths(con)
    seen: dict[tuple[str, ...], str] = {}
    new: list[tuple[tuple[str, ...], str, LandedResponse]] = []
    for landed in zone.iter_landed(source=source, endpoint=endpoint):
        meta = landed.meta
        key: tuple[str, ...] = (
            meta["source"],
            meta["endpoint"],
            LandingZone.request_path(meta["url"]),
            meta["request_key"],
            meta["fetched_at"],
        )
        file_path = str(landed.path)
        other = seen.get(key, existing.get(key))
        if other is not None and other != file_path:
            raise RawKeyCollision(_collision_message(key, other, file_path))
        seen[key] = file_path
        if key not in existing:
            new.append((key, json.dumps(meta["partitions"]), landed))
    if not new:
        return 0

    # A committed capture whose payload does not parse is corruption at rest, so it fails
    # the load (PayloadNotJson names the file) instead of being skipped, and the
    # transaction is rolled back. A capture that vanishes mid-read (a sweep moved it) is
    # not committed any more and is passed over.
    inserted = 0
    con.execute("begin transaction")
    try:
        for start in range(0, len(new), batch_rows):
            rows = []
            for key, partitions, landed in new[start : start + batch_rows]:
                try:
                    payload = json.dumps(landed.payload)
                except VANISHED:
                    continue
                rows.append((*key, partitions, payload, str(landed.path)))
            if rows:
                con.executemany(f"insert into {QUALIFIED} values (?, ?, ?, ?, ?, ?, ?, ?)", rows)
                inserted += len(rows)
    except BaseException:
        con.execute("rollback")
        raise
    con.execute("commit")
    return inserted


def _existing_file_paths(con: duckdb.DuckDBPyConnection) -> dict[tuple[str, ...], str]:
    """The key of every row of the raw table, with the file it was loaded from. Keys and
    paths only: a few megabytes for eight seasons."""
    rows = con.execute(f"select {', '.join(KEY_COLUMNS)}, file_path from {QUALIFIED}").fetchall()
    return {tuple(row[:5]): row[5] for row in rows}


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


def _collision_message(key: Sequence[str], first: str, second: str) -> str:
    named = ", ".join(f"{column}={value!r}" for column, value in zip(KEY_COLUMNS, key, strict=True))
    return (
        f"two files share one raw key ({named}): {first} and {second}. "
        "Nothing was loaded; remove or fix one of them."
    )


def connect(db_path: Path | str) -> duckdb.DuckDBPyConnection:
    """Open (creating if needed) the DuckDB warehouse file."""
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    return duckdb.connect(str(path))
