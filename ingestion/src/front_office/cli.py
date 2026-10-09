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
import httpx
import typer

from front_office import audit as landing_audit
from front_office.espn import matchups as espn_matchups
from front_office.espn import pro_schedule as espn_pro_schedule
from front_office.espn import rosters as espn_rosters
from front_office.espn import settings as espn_settings
from front_office.espn import teams as espn_teams
from front_office.espn import transactions as espn_transactions
from front_office.espn.client import (
    EspnCredentials,
    espn_client,
    espn_public_client,
    load_env_file,
)
from front_office.http_client import AuthExpired, HttpClient, RequestFailed
from front_office.idmap import sfbb
from front_office.landing import (
    LandingCollision,
    LandingLocked,
    LandingZone,
    NotMigrated,
    SweepTooLarge,
)
from front_office.load import RawKeyCollision, RawSchemaOutdated, connect, load_landing_zone
from front_office.mlb import boxscore as mlb_boxscore
from front_office.mlb import players as mlb_players
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


@contextmanager
def writing_session(zone: LandingZone, run_stamp: str) -> Iterator[None]:
    """Hold the writer lock, sweep what is not a capture, then let the run fetch.

    Anything that stops the run safely (another writer, a sweep over its limit, an
    unmigrated landing zone, a capture collision) is a one-line error and exit 1, with
    nothing fetched if it happened before the fetch.
    """
    try:
        with zone.writer_lock():
            moved = zone.sweep(run_stamp)
            for kind, path in moved:
                typer.echo(f"quarantined {kind}  {path}")
            if moved:
                typer.echo(f"quarantined {len(moved)} item(s) to {zone.quarantine_root}")
            yield
    except (LandingLocked, LandingCollision, SweepTooLarge, NotMigrated) as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(code=1) from None


def warn_if_writing(zone: LandingZone) -> None:
    """One line on stderr when a backfill holds the lock: a read now may be incomplete."""
    if zone.writer_active():
        typer.echo("warning: a backfill is in progress; the result may be incomplete", err=True)


@backfill_app.command("mlb")
def backfill_mlb(
    season: Annotated[int, typer.Option("--season", help="Season year, e.g. 2026.")],
    raw_root: RawRoot = DEFAULT_RAW_ROOT,
    only: Annotated[
        str | None,
        typer.Option("--only", help="Limit to one endpoint: schedule, players or boxscore."),
    ] = None,
    limit: Annotated[
        int | None, typer.Option("--limit", help="Stop after this many boxscore fetches.")
    ] = None,
    refresh: Annotated[
        bool, typer.Option("--refresh", help="Re-fetch even settled boxscores.")
    ] = False,
) -> None:
    """Back-fill MLB Stats API data for a season."""
    endpoints = ("schedule", "players", "boxscore")
    if only is not None and only not in endpoints:
        raise typer.BadParameter(
            f"unknown endpoint: {only} (expected one of {', '.join(endpoints)})"
        )

    zone = LandingZone(root=raw_root)
    fetched_at = utc_stamp()
    with writing_session(zone, fetched_at), exit_on_expired_auth(), HttpClient("mlb") as client:
        if only in (None, "schedule"):
            path = mlb_schedule.backfill_schedule(
                zone=zone, client=client, season=season, fetched_at=fetched_at
            )
            typer.echo(f"landed schedule -> {path}")
        # A failed list does not stop the boxscores; the run exits 1 at the end instead. A
        # 401/403 is MLB refusing a request that carries no login, not an expired one, so it
        # must not end the run as an expired ESPN login does.
        players_error = None
        if only in (None, "players"):
            try:
                players_path = mlb_players.backfill_players(
                    zone=zone, client=client, season=season, fetched_at=fetched_at
                )
            except (AuthExpired, RequestFailed, httpx.HTTPStatusError) as failure:
                typer.echo(f"player list: {failure}", err=True)
                players_error = failure
            else:
                typer.echo(f"landed players -> {players_path}")
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
                if players_error is None:
                    raise typer.Exit(code=1)
    if players_error is not None:
        raise typer.Exit(code=1)


def land_pro_schedule(zone: LandingZone, season: int, fetched_at: str) -> Exception | None:
    """Land the pro schedule with the public client; return the error if it failed.

    A malformed response, a refused one, or retries running out are returned (and printed)
    rather than raised, so the caller decides whether the run goes on. A 401 or 403 is one
    of them: no cookies are sent, so it is not an expired login but ESPN asking for one,
    and it must not end the league run as an expired login does (spec 0073, R1.7).
    """
    try:
        with espn_public_client() as public:
            path = espn_pro_schedule.backfill_pro_schedule(
                zone=zone, client=public, season=season, fetched_at=fetched_at
            )
    except AuthExpired:
        error: Exception = RuntimeError(
            "ESPN refused the request, which carries no login; the view may now need one"
        )
        typer.echo(f"pro schedule: {error}", err=True)
        return error
    except (
        espn_pro_schedule.ProScheduleMalformed,
        RequestFailed,
        httpx.HTTPStatusError,
    ) as failure:
        typer.echo(f"pro schedule: {failure}", err=True)
        return failure
    typer.echo(f"landed pro schedule -> {path}")
    return None


@backfill_app.command("espn")
def backfill_espn(
    season: Annotated[int, typer.Option("--season", help="Season year, e.g. 2026.")],
    raw_root: RawRoot = DEFAULT_RAW_ROOT,
    refresh: Annotated[
        bool, typer.Option("--refresh", help="Re-fetch even settled scoring periods.")
    ] = False,
    only: Annotated[
        str | None,
        typer.Option(
            "--only",
            help="Limit the run: pro-schedule (needs no login), or matchups "
            "(pro schedule, settings and matchups only).",
        ),
    ] = None,
) -> None:
    """Back-fill ESPN data: the pro schedule, then league settings, teams and rosters.

    The pro schedule is public and fetched without credentials; a failure there is
    reported and the league run goes on, then the command exits 1. `--only pro-schedule`
    fetches just that, and needs no .env. `--only matchups` fetches the pro schedule,
    settings and matchups, and no teams, transactions or rosters; it needs the .env.
    """
    if only is not None and only not in ("pro-schedule", "matchups"):
        raise typer.BadParameter(f"unknown endpoint: {only} (expected pro-schedule or matchups)")

    zone = LandingZone(root=raw_root)
    fetched_at = utc_stamp()

    if only == "pro-schedule":
        with writing_session(zone, fetched_at), exit_on_expired_auth():
            pro_schedule_error = land_pro_schedule(zone, season, fetched_at)
        if pro_schedule_error is not None:
            raise typer.Exit(code=1)
        return

    load_env_file()
    credentials = EspnCredentials.from_env()

    if only == "matchups":
        # A past season's league data without its rosters: the same calls as the full run
        # below, minus teams, transactions and rosters.
        with (
            writing_session(zone, fetched_at),
            exit_on_expired_auth(),
            espn_client(credentials) as client,
        ):
            pro_schedule_error = land_pro_schedule(zone, season, fetched_at)
            settings_path, settings_payload = espn_settings.backfill_settings(
                zone=zone,
                client=client,
                season=season,
                league_id=credentials.league_id,
                fetched_at=fetched_at,
            )
            typer.echo(f"landed settings -> {settings_path}")
            matchups_path = espn_matchups.backfill_matchups(
                zone=zone,
                client=client,
                season=season,
                league_id=credentials.league_id,
                fetched_at=fetched_at,
            )
            typer.echo(f"landed matchups -> {matchups_path}")
            status = settings_payload.get("status", {})
            typer.echo(
                f"scoring periods: latest={status.get('latestScoringPeriod')} "
                f"final={status.get('finalScoringPeriod')}"
            )
        if pro_schedule_error is not None:
            raise typer.Exit(code=1)
        return

    with (
        writing_session(zone, fetched_at),
        exit_on_expired_auth(),
        espn_client(credentials) as client,
    ):
        # First, so the schedule is landed even if the league run later stops. It uses its
        # own cookie-less client, never `client`.
        pro_schedule_error = land_pro_schedule(zone, season, fetched_at)

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

        # An incomplete log still lands its pages and does not stop the rosters; the run
        # exits non-zero at the end instead.
        transactions_error = None
        try:
            transaction_paths = espn_transactions.backfill_transactions(
                zone=zone,
                client=client,
                season=season,
                league_id=credentials.league_id,
                fetched_at=fetched_at,
            )
        except espn_transactions.TransactionLogIncomplete as error:
            transactions_error = error
            typer.echo(f"transactions: {error}", err=True)
        else:
            typer.echo(f"landed transactions: {len(transaction_paths)} page(s), complete")

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
        if summary.unproven:
            typer.echo(f"unproven scoring periods: {summary.unproven}", err=True)
        if (
            summary.failed
            or summary.unproven
            or transactions_error is not None
            or pro_schedule_error is not None
        ):
            raise typer.Exit(code=1)


@backfill_app.command("idmap")
def backfill_idmap(raw_root: RawRoot = DEFAULT_RAW_ROOT) -> None:
    """Fetch the SFBB player id map: the ESPN <-> MLBAM crosswalk."""
    zone = LandingZone(root=raw_root)
    fetched_at = utc_stamp()
    with writing_session(zone, fetched_at), HttpClient("idmap") as client:
        path, rows = sfbb.backfill_player_id_map(zone=zone, client=client, fetched_at=fetched_at)
    typer.echo(f"landed {rows} id-map rows -> {path}")


@app.command("repair")
def repair(
    raw_root: RawRoot = DEFAULT_RAW_ROOT,
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="List what would move; move nothing.")
    ] = False,
    deep: Annotated[
        bool,
        typer.Option("--deep", help="Also move captures whose payload fails its checksum."),
    ] = False,
    force: Annotated[
        bool, typer.Option("--force", help="Move even more than the sweep limit allows.")
    ] = False,
) -> None:
    """Move everything that is not a committed capture to the quarantine; fetch nothing."""
    zone = LandingZone(root=raw_root)
    try:
        if dry_run:
            plan = zone.sweep(utc_stamp(), dry_run=True, deep=deep)
            for kind, path in plan:
                typer.echo(f"{kind:<8}{path}")
            typer.echo(f"{len(plan)} item(s) would move to {zone.quarantine_root}")
            limit = zone.sweep_limit()
            if len(plan) > limit:
                typer.echo(
                    f"that is over the limit of {limit}: a real run would refuse without --force"
                )
            return
        with zone.writer_lock():
            plan = zone.sweep(utc_stamp(), deep=deep, force=force)
        for kind, path in plan:
            typer.echo(f"{kind:<8}{path}")
        typer.echo(f"moved {len(plan)} item(s) to {zone.quarantine_root}")
    except (LandingLocked, SweepTooLarge, NotMigrated) as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(code=1) from None


@app.command("load")
def load(raw_root: RawRoot = DEFAULT_RAW_ROOT, db: DbPath = DEFAULT_DB) -> None:
    """Load landed JSON into raw.api_responses (safe to rerun)."""
    zone = LandingZone(root=raw_root)
    warn_if_writing(zone)
    with connect(db) as con:
        try:
            inserted = load_landing_zone(con, zone)
        except (RawKeyCollision, RawSchemaOutdated) as error:
            typer.echo(str(error), err=True)
            raise typer.Exit(code=1) from None
    typer.echo(f"loaded {inserted} new response(s) into {db}")


@app.command("audit")
def audit(
    season: Annotated[int, typer.Option("--season", help="Season year, e.g. 2026.")],
    raw_root: RawRoot = DEFAULT_RAW_ROOT,
    db: DbPath = DEFAULT_DB,
    today: Annotated[
        str | None,
        typer.Option(
            "--today",
            help="Judge whether a settle window has closed at the end of this Eastern date "
            "(YYYY-MM-DD). Only that threshold moves: captures taken after it still count.",
        ),
    ] = None,
) -> None:
    """Check that landed data is complete, loaded and final. Exits 1 on any ERROR.

    The audit judges a season landed whole: a season landed with `backfill espn --only
    matchups` is reported as missing its rosters and boxscores.
    """
    zone = LandingZone(root=raw_root)
    warn_if_writing(zone)
    as_of = (
        landing_audit.end_of_eastern_day(dt.date.fromisoformat(today))
        if today
        else dt.datetime.now(dt.UTC)
    )
    if db.exists():
        with duckdb.connect(str(db), read_only=True) as con:
            findings = landing_audit.run_audit(zone, con, season=season, as_of=as_of)
    else:
        findings = landing_audit.run_audit(zone, None, season=season, as_of=as_of)
    typer.echo(landing_audit.format_report(findings))
    if any(finding.severity == landing_audit.Severity.ERROR for finding in findings):
        raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
