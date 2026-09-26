"""The `front-office` CLI: the one entry point for ingestion.

Orchestration (Dagster locally, Cloud Run in production) will call these commands rather
than importing the package, so scheduling never needs to know how ingestion works inside.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Annotated

import typer

from front_office.espn import rosters as espn_rosters
from front_office.espn import settings as espn_settings
from front_office.espn import teams as espn_teams
from front_office.espn.client import EspnCredentials, espn_client, load_env_file
from front_office.http_client import HttpClient
from front_office.landing import LandingZone
from front_office.load import connect, load_landing_zone
from front_office.mlb import boxscore as mlb_boxscore
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
        str | None,
        typer.Option("--only", help="Limit to one endpoint: schedule or boxscore."),
    ] = None,
    limit: Annotated[
        int | None, typer.Option("--limit", help="Stop after this many boxscore fetches.")
    ] = None,
    refresh: Annotated[
        bool, typer.Option("--refresh", help="Re-fetch even settled boxscores.")
    ] = False,
) -> None:
    """Back-fill MLB Stats API data for a season."""
    endpoints = ("schedule", "boxscore")
    if only is not None and only not in endpoints:
        raise typer.BadParameter(
            f"unknown endpoint: {only} (expected one of {', '.join(endpoints)})"
        )

    zone = LandingZone(root=raw_root)
    fetched_at = utc_stamp()
    with HttpClient("mlb") as client:
        if only in (None, "schedule"):
            path = mlb_schedule.backfill_schedule(
                zone=zone, client=client, season=season, fetched_at=fetched_at
            )
            typer.echo(f"landed schedule -> {path}")
        if only in (None, "boxscore"):
            summary = mlb_boxscore.backfill_boxscores(
                zone=zone,
                client=client,
                season=season,
                fetched_at=fetched_at,
                limit=limit,
                refresh=refresh,
            )
            typer.echo(
                f"boxscores: fetched={summary.fetched} skipped={summary.skipped} "
                f"failed={summary.failed}"
            )
            if summary.failed:
                typer.echo(f"failed game_pks: {summary.failed_game_pks}", err=True)
                raise typer.Exit(code=1)


@backfill_app.command("espn")
def backfill_espn(
    season: Annotated[int, typer.Option("--season", help="Season year, e.g. 2026.")],
    raw_root: RawRoot = DEFAULT_RAW_ROOT,
    refresh: Annotated[
        bool, typer.Option("--refresh", help="Re-fetch even settled scoring periods.")
    ] = False,
) -> None:
    """Back-fill ESPN league data: settings, teams, then one roster per scoring period."""
    load_env_file()
    credentials = EspnCredentials.from_env()
    zone = LandingZone(root=raw_root)
    fetched_at = utc_stamp()

    with espn_client(credentials) as client:
        settings_path, settings_payload = espn_settings.backfill_settings(
            zone=zone,
            client=client,
            season=season,
            league_id=credentials.league_id,
            fetched_at=fetched_at,
        )
        typer.echo(f"landed settings -> {settings_path}")

        teams_path = espn_teams.backfill_teams(
            zone=zone,
            client=client,
            season=season,
            league_id=credentials.league_id,
            fetched_at=fetched_at,
        )
        typer.echo(f"landed teams -> {teams_path}")

        status = settings_payload.get("status", {})
        typer.echo(
            f"scoring periods: latest={status.get('latestScoringPeriod')} "
            f"final={status.get('finalScoringPeriod')}"
        )
        summary = espn_rosters.backfill_rosters(
            zone=zone,
            client=client,
            season=season,
            league_id=credentials.league_id,
            status=status,
            fetched_at=fetched_at,
            refresh=refresh,
        )
        typer.echo(
            f"rosters: fetched={summary.fetched} skipped={summary.skipped} failed={summary.failed}"
        )
        if summary.failed:
            typer.echo(f"failed scoring periods: {summary.failed_periods}", err=True)
            raise typer.Exit(code=1)


@app.command("load")
def load(raw_root: RawRoot = DEFAULT_RAW_ROOT, db: DbPath = DEFAULT_DB) -> None:
    """Load landed JSON into raw.api_responses (safe to rerun)."""
    zone = LandingZone(root=raw_root)
    with connect(db) as con:
        inserted = load_landing_zone(con, zone)
    typer.echo(f"loaded {inserted} new response(s) into {db}")


if __name__ == "__main__":
    app()
