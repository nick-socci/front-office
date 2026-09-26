"""The `front-office` CLI: the one entry point for ingestion.

Orchestration (Dagster locally, Cloud Run in production) will call these commands rather
than importing the package, so scheduling never needs to know how ingestion works inside.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Annotated

import typer

from front_office.http_client import HttpClient
from front_office.landing import LandingZone
from front_office.load import connect, load_landing_zone
from front_office.mlb import schedule as mlb_schedule

DEFAULT_RAW_ROOT = Path("data/raw")
DEFAULT_DB = Path("data/warehouse.duckdb")

app = typer.Typer(
    help="Front Office ingestion: fetch raw data, land it, load it.", no_args_is_help=True
)
backfill_app = typer.Typer(
    help="Fetch historical data and land it as raw JSON.", no_args_is_help=True
)
app.add_typer(backfill_app, name="backfill")

RawRoot = Annotated[Path, typer.Option("--raw-root", help="Landing zone root directory.")]
DbPath = Annotated[Path, typer.Option("--db", help="DuckDB warehouse file.")]


def utc_stamp() -> str:
    """The fetched_at stamp used in filenames: compact, sortable, unambiguous."""
    return dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")


@backfill_app.command("mlb")
def backfill_mlb(
    season: Annotated[int, typer.Option("--season", help="Season year, e.g. 2026.")],
    raw_root: RawRoot = DEFAULT_RAW_ROOT,
    only: Annotated[
        str | None, typer.Option("--only", help="Limit to one endpoint: schedule.")
    ] = None,
) -> None:
    """Back-fill MLB Stats API data for a season."""
    zone = LandingZone(root=raw_root)
    fetched_at = utc_stamp()
    with HttpClient("mlb") as client:
        if only in (None, "schedule"):
            path = mlb_schedule.backfill_schedule(
                zone=zone, client=client, season=season, fetched_at=fetched_at
            )
            typer.echo(f"landed schedule -> {path}")
        if only not in (None, "schedule"):
            raise typer.BadParameter(f"unknown endpoint: {only}")


@app.command("load")
def load(raw_root: RawRoot = DEFAULT_RAW_ROOT, db: DbPath = DEFAULT_DB) -> None:
    """Load landed JSON into raw.api_responses (safe to rerun)."""
    zone = LandingZone(root=raw_root)
    with connect(db) as con:
        inserted = load_landing_zone(con, zone)
    typer.echo(f"loaded {inserted} new response(s) into {db}")


if __name__ == "__main__":
    app()
