"""The `front-office` CLI: the one entry point for ingestion.

Orchestration (Dagster locally, Cloud Run in production) will call these commands rather
than importing the package, so scheduling never needs to know how ingestion works inside.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Annotated

import duckdb
import typer

from front_office import audit as landing_audit
from front_office.espn import matchups as espn_matchups
from front_office.espn import rosters as espn_rosters
from front_office.espn import settings as espn_settings
from front_office.espn import teams as espn_teams
from front_office.espn import transactions as espn_transactions
from front_office.espn.client import EspnCredentials, espn_client, load_env_file
from front_office.http_client import AuthExpired, HttpClient
from front_office.idmap import sfbb
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


@contextmanager
def exit_on_expired_auth() -> Iterator[None]:
    """Turn rejected credentials into a one-line error and exit 1, not a traceback.

    A traceback would be noise (nothing in the stack helps) and, with typer's
    locals-printing tracebacks, a needless place for session details to surface.
    """
    try:
        yield
    except AuthExpired as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(code=1) from None


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
    with exit_on_expired_auth(), HttpClient("mlb") as client:
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

    with exit_on_expired_auth(), espn_client(credentials) as client:
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

        matchups_path = espn_matchups.backfill_matchups(
            zone=zone,
            client=client,
            season=season,
            league_id=credentials.league_id,
            fetched_at=fetched_at,
        )
        typer.echo(f"landed matchups -> {matchups_path}")

        transactions_path = espn_transactions.backfill_transactions(
            zone=zone,
            client=client,
            season=season,
            league_id=credentials.league_id,
            fetched_at=fetched_at,
        )
        typer.echo(f"landed transactions -> {transactions_path}")

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


@backfill_app.command("idmap")
def backfill_idmap(raw_root: RawRoot = DEFAULT_RAW_ROOT) -> None:
    """Fetch the SFBB player id map: the ESPN <-> MLBAM crosswalk."""
    zone = LandingZone(root=raw_root)
    with HttpClient("idmap") as client:
        path, rows = sfbb.backfill_player_id_map(zone=zone, client=client, fetched_at=utc_stamp())
    typer.echo(f"landed {rows} id-map rows -> {path}")


@app.command("load")
def load(raw_root: RawRoot = DEFAULT_RAW_ROOT, db: DbPath = DEFAULT_DB) -> None:
    """Load landed JSON into raw.api_responses (safe to rerun)."""
    zone = LandingZone(root=raw_root)
    with connect(db) as con:
        inserted = load_landing_zone(con, zone)
    typer.echo(f"loaded {inserted} new response(s) into {db}")


@app.command("audit")
def audit(
    season: Annotated[int, typer.Option("--season", help="Season year, e.g. 2026.")],
    raw_root: RawRoot = DEFAULT_RAW_ROOT,
    db: DbPath = DEFAULT_DB,
    today: Annotated[
        str | None,
        typer.Option("--today", help="Eastern date to judge settle windows by (YYYY-MM-DD)."),
    ] = None,
) -> None:
    """Check that landed data is complete, loaded and final. Exits 1 on any ERROR."""
    zone = LandingZone(root=raw_root)
    as_of = dt.date.fromisoformat(today) if today else dt.datetime.now(landing_audit.EASTERN).date()
    if db.exists():
        with duckdb.connect(str(db), read_only=True) as con:
            findings = landing_audit.run_audit(zone, con, season=season, today=as_of)
    else:
        findings = landing_audit.run_audit(zone, None, season=season, today=as_of)
    typer.echo(landing_audit.format_report(findings))
    if any(finding.severity == landing_audit.Severity.ERROR for finding in findings):
        raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
