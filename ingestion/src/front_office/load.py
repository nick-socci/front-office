"""Load the landing zone into raw.captures, a manifest of what has landed.

One row per committed capture, naming its payload file (relative to the landing root) and
holding none of the payload. dbt reads the payloads from those files itself, so the load
reads sidecars only and a warehouse stays small however much has landed (spec 0150,
ADR 0066). The table is append-only: a re-fetch of the same request gets a new fetched_at
and therefore a new row, so history is never overwritten and "what did ESPN say on this
date?" stays answerable.

A capture is identified by source, endpoint, request path, parameters and fetch time
(ADR 0011). Two different files with one key are an error, never a silent first-wins.
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

import duckdb

from front_office.landing import LandingZone

SCHEMA = "raw"
TABLE = "captures"
QUALIFIED = f"{SCHEMA}.{TABLE}"
OLD_TABLE = "api_responses"
KEY_COLUMNS = ("source", "endpoint", "request_path", "request_key", "fetched_at")
STAMP_FORMAT = "%Y%m%dT%H%M%SZ"
_STAMP_SHAPE = re.compile(r"\d{8}T\d{6}Z")

CREATE_SQL = f"""
create schema if not exists {SCHEMA};
create table if not exists {QUALIFIED} (
    source varchar not null,
    endpoint varchar not null,
    request_path varchar not null,
    request_key varchar not null,
    fetched_at varchar not null,
    partitions json not null,
    file_path varchar not null,
    primary key (source, endpoint, request_path, request_key, fetched_at)
);
"""


class RawKeyCollision(Exception):
    """Two different files claim one raw key; loading either would silently lose the other."""


class RawSchemaOutdated(Exception):
    """The warehouse holds raw.api_responses, the table this manifest replaced."""


class CaptureStampInvalid(ValueError):
    """A committed capture's fetched_at is not `%Y%m%dT%H%M%SZ`, which dbt parses it as."""


def load_landing_zone(
    con: duckdb.DuckDBPyConnection,
    zone: LandingZone,
    *,
    source: str | None = None,
    endpoint: str | None = None,
) -> int:
    """Insert a row for every committed capture not already present. Returns the number.

    Raises RawSchemaOutdated if the warehouse holds raw.api_responses, RawKeyCollision if
    two different files share a key, and CaptureStampInvalid if a capture's fetched_at is
    not of the form `%Y%m%dT%H%M%SZ`; in every case nothing is changed. No payload is read:
    the rows come from the sidecars, in one transaction, so a load that fails or is
    interrupted leaves no row of the run.
    """
    _refuse_old_table(con)
    con.execute(CREATE_SQL)

    # iter_landed yields committed captures only (LandingZone.check): anything else under
    # the root, such as a temporary directory or an old-layout file, is not loaded.
    existing = _existing_file_paths(con)
    seen: dict[tuple[str, ...], str] = {}
    new: list[tuple[str, ...]] = []
    for landed in zone.iter_landed(source=source, endpoint=endpoint):
        meta = landed.meta
        file_path = landed.path.relative_to(zone.root).as_posix()
        _check_stamp(meta["fetched_at"], file_path)
        key: tuple[str, ...] = (
            meta["source"],
            meta["endpoint"],
            LandingZone.request_path(meta["url"]),
            meta["request_key"],
            meta["fetched_at"],
        )
        other = seen.get(key, existing.get(key))
        if other is not None and other != file_path:
            raise RawKeyCollision(_collision_message(key, other, file_path))
        seen[key] = file_path
        if key not in existing:
            new.append((*key, json.dumps(meta["partitions"]), file_path))
    if not new:
        return 0

    con.execute("begin transaction")
    try:
        con.executemany(f"insert into {QUALIFIED} values (?, ?, ?, ?, ?, ?, ?)", new)
    except BaseException:
        con.execute("rollback")
        raise
    con.execute("commit")
    return len(new)


def _check_stamp(stamp: object, file_path: str) -> None:
    """dbt parses fetched_at with this one format; refuse here what it would fail on there."""
    try:
        if not isinstance(stamp, str) or not _STAMP_SHAPE.fullmatch(stamp):
            raise ValueError(stamp)
        datetime.strptime(stamp, STAMP_FORMAT)
    except ValueError:
        raise CaptureStampInvalid(
            f"capture {file_path} has fetched_at {stamp!r}, not of the form {STAMP_FORMAT}. "
            "Nothing was loaded; fix or remove the capture."
        ) from None


def _existing_file_paths(con: duckdb.DuckDBPyConnection) -> dict[tuple[str, ...], str]:
    """The key of every row of the manifest, with the file it was loaded from."""
    rows = con.execute(f"select {', '.join(KEY_COLUMNS)}, file_path from {QUALIFIED}").fetchall()
    return {tuple(row[:5]): row[5] for row in rows}


def _refuse_old_table(con: duckdb.DuckDBPyConnection) -> None:
    (found,) = con.execute(
        "select count(*) from information_schema.tables where table_schema = ? and table_name = ?",
        [SCHEMA, OLD_TABLE],
    ).fetchone() or (0,)
    if found:
        raise RawSchemaOutdated(
            f"{SCHEMA}.{OLD_TABLE} in this warehouse is the table {QUALIFIED} replaced (it "
            "holds payloads; the manifest holds file paths). "
            "Load into a new warehouse file instead (use --db); the warehouse is left unchanged."
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
