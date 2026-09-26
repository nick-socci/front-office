"""Load the landing zone into raw.api_responses.

One row per API response, payload kept as JSON. The table is append-only: a re-fetch of
the same request gets a new fetched_at and therefore a new row, so history is never
overwritten and "what did ESPN say on this date?" stays answerable. dbt does the parsing.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import duckdb

from front_office.landing import LandingZone

logger = logging.getLogger(__name__)

SCHEMA = "raw"
TABLE = "api_responses"
QUALIFIED = f"{SCHEMA}.{TABLE}"
REQUIRED_META = ("source", "endpoint", "fetched_at")

CREATE_SQL = f"""
create schema if not exists {SCHEMA};
create table if not exists {QUALIFIED} (
    source varchar not null,
    endpoint varchar not null,
    request_key varchar not null,
    fetched_at varchar not null,
    payload json not null,
    file_path varchar not null,
    primary key (source, endpoint, request_key, fetched_at)
);
"""


def load_landing_zone(
    con: duckdb.DuckDBPyConnection,
    zone: LandingZone,
    *,
    source: str | None = None,
    endpoint: str | None = None,
) -> int:
    """Insert every landed response not already present. Returns the number inserted."""
    con.execute(CREATE_SQL)

    rows = []
    skipped = 0
    for landed in zone.iter_landed(source=source, endpoint=endpoint):
        # A response with no metadata sidecar has no key: it was landed outside the
        # ingestion package (e.g. by a throwaway spike script). Those files are backups,
        # not pipeline inputs, so they are skipped rather than loaded with empty keys.
        # request_key is legitimately empty for endpoints that take no parameters, so it
        # only has to be present, not truthy.
        has_key = "request_key" in landed.meta and all(
            landed.meta.get(field) for field in REQUIRED_META
        )
        if not has_key:
            skipped += 1
            continue
        rows.append(
            (
                landed.meta["source"],
                landed.meta["endpoint"],
                landed.meta["request_key"],
                landed.meta["fetched_at"],
                json.dumps(landed.payload),
                str(landed.path),
            )
        )
    if skipped:
        logger.warning("skipped %s landed file(s) with no metadata sidecar", skipped)
    if not rows:
        return 0

    con.execute("create or replace temp table incoming as select * from " + QUALIFIED + " limit 0")
    con.executemany("insert into incoming values (?, ?, ?, ?, ?, ?)", rows)
    before = _count(con)
    con.execute(
        f"""
        insert into {QUALIFIED}
        select i.* from (
            select * from incoming
            qualify row_number() over (
                partition by source, endpoint, request_key, fetched_at
                order by file_path
            ) = 1
        ) i
        where not exists (
            select 1 from {QUALIFIED} r
            where r.source = i.source
              and r.endpoint = i.endpoint
              and r.request_key = i.request_key
              and r.fetched_at = i.fetched_at
        )
        """
    )
    return _count(con) - before


def connect(db_path: Path | str) -> duckdb.DuckDBPyConnection:
    """Open (creating if needed) the DuckDB warehouse file."""
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    return duckdb.connect(str(path))


def _count(con: duckdb.DuckDBPyConnection) -> int:
    row = con.execute(f"select count(*) from {QUALIFIED}").fetchone()
    return int(row[0]) if row else 0
