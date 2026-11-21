"""The six hand-written assets: one `front-office` command each (ADR 0127, 0129).

Why they are shaped as they are:

- A **fetch** (`mlb_captures`, `espn_captures`, `espn_matchup_days`, `idmap_capture`) always
  materializes, and a non-zero exit fails its asset check `fetch_complete` instead (ADR 0129).
  A check is a pass/fail test attached to an asset; this one is non-blocking (Dagster's default,
  stated here), so upload and build still run and one expired ESPN login does not leave BigQuery
  without that morning's MLB games. Its severity is ERROR: a WARN failure would not read as one.
  The command's last filtered stderr lines ride on the check as metadata (`cli.run` has dropped
  everything outside its allowlist, R2.4).
- `raw_in_warehouse` stands for the warehouse's view of the captures (`upload` or `load`). The
  dbt assets depend on it through the translator, which maps every dbt source to this key. A
  non-zero exit raises, which skips what depends on it (R2.2).
- `source_freshness` runs `dbt source freshness` after the build and reads dbt's `sources.json`
  (spec 0219): one non-blocking check per feed (`mlb_runs_fresh`, `espn_runs_fresh`,
  `idmap_runs_fresh`), failed when the feed is not `pass`. A stale feed fails its check, not the
  asset; only a `runtime error` or a missing `sources.json` raises.
- The order `mlb_captures` -> `espn_captures` -> `espn_matchup_days` -> `raw_in_warehouse` is
  declared as dependencies that carry no data: the fetches share the landing zone's writer lock,
  and a second writer fails rather than waits (R1.4). `idmap_capture` is upstream of
  `raw_in_warehouse` too but outside `daily` (R4.2).

Every asset first calls `settings.check_ready`, so a BigQuery run without a project fails before
any command has run (R3.2). Settings are read when an asset runs, not when it is defined.
"""

from collections.abc import Generator, Iterable, Mapping
from typing import Any

from dagster import (
    AssetCheckResult,
    AssetCheckSeverity,
    AssetCheckSpec,
    AssetExecutionContext,
    AssetKey,
    AssetSpec,
    Failure,
    MaterializeResult,
    MetadataValue,
    asset,
    multi_asset,
)
from dagster_dbt import DbtCliResource

from front_office_pipeline import cli, season, settings
from front_office_pipeline.dbt_assets import dbt_environment

FETCH_COMPLETE = "fetch_complete"
BIGQUERY_PREFIX = ("uv", "run", "--group", "bigquery", *cli.FRONT_OFFICE)

FetchResults = Generator[MaterializeResult[None] | AssetCheckResult]


_SEASON_OF_RUN: dict[str, int] = {}


def _season(context: AssetExecutionContext) -> int:
    """The season of this run, read from the clock once: the first step to ask decides it.

    A run that starts before New York midnight on 31 December and runs past it must not fetch
    2026 for one step and 2027 for the next (R3.1, ADR 0130).
    """
    run_id = context.run.run_id
    if run_id not in _SEASON_OF_RUN:
        _SEASON_OF_RUN[run_id] = season.current()
    return _SEASON_OF_RUN[run_id]


def _fetch_complete(key: str) -> AssetCheckSpec:
    # `blocking=False` is the default; it is stated because ADR 0129 depends on it.
    return AssetCheckSpec(FETCH_COMPLETE, asset=key, blocking=False)


def _fetch_results(key: str, result: cli.Result, extra: dict[str, Any]) -> FetchResults:
    """The materialization (always) and the `fetch_complete` result for a command's outcome."""
    yield MaterializeResult(asset_key=key, metadata={"exit_code": result.exit_code, **extra})
    yield AssetCheckResult(
        asset_key=AssetKey(key),
        check_name=FETCH_COMPLETE,
        passed=result.exit_code == 0,
        severity=AssetCheckSeverity.ERROR,
        metadata={
            "exit_code": result.exit_code,
            "stderr_tail": MetadataValue.text("\n".join(result.tail)),
        },
    )


def _fetch(
    context: AssetExecutionContext, key: str, args: list[str], extra: dict[str, Any] | None = None
) -> FetchResults:
    settings.check_ready()
    result = cli.run(args, context)
    yield from _fetch_results(key, result, extra or {})


@multi_asset(
    specs=[AssetSpec("mlb_captures")],
    check_specs=[_fetch_complete("mlb_captures")],
    name="mlb_captures",
)
def mlb_captures(context: AssetExecutionContext) -> FetchResults:
    root, year = settings.landing_root(), _season(context)
    yield from _fetch(
        context,
        "mlb_captures",
        ["backfill", "mlb", "--season", str(year), "--raw-root", str(root)],
    )


@multi_asset(
    specs=[AssetSpec("espn_captures", deps=["mlb_captures"])],
    check_specs=[_fetch_complete("espn_captures")],
    name="espn_captures",
)
def espn_captures(context: AssetExecutionContext) -> FetchResults:
    root, year = settings.landing_root(), _season(context)
    yield from _fetch(
        context,
        "espn_captures",
        ["backfill", "espn", "--season", str(year), "--raw-root", str(root)],
    )


@multi_asset(
    specs=[AssetSpec("espn_matchup_days", deps=["espn_captures"])],
    check_specs=[_fetch_complete("espn_matchup_days")],
    name="espn_matchup_days",
)
def espn_matchup_days(context: AssetExecutionContext) -> FetchResults:
    """Fetch matchup days once the season is over (R3.3); until then, no request is made."""
    settings.check_ready()
    root, year = settings.landing_root(), _season(context)
    if not season.is_over(root, year):
        context.log.info(f"season {year} is not over: no matchup days to fetch")
        yield from _fetch_results(
            "espn_matchup_days", cli.Result(0, ()), {"skipped": True, "season": year}
        )
        return
    yield from _fetch(
        context,
        "espn_matchup_days",
        [
            "backfill",
            "espn",
            "--season",
            str(year),
            "--only",
            "matchup-days",
            "--raw-root",
            str(root),
        ],
        {"skipped": False, "season": year},
    )


@multi_asset(
    specs=[AssetSpec("idmap_capture")],
    check_specs=[_fetch_complete("idmap_capture")],
    name="idmap_capture",
)
def idmap_capture(context: AssetExecutionContext) -> FetchResults:
    root = settings.landing_root()
    yield from _fetch(context, "idmap_capture", ["backfill", "idmap", "--raw-root", str(root)])


@asset(
    key="raw_in_warehouse",
    deps=["idmap_capture", "espn_matchup_days"],
    description="The landed captures, in the warehouse the build reads (`upload` or `load`).",
)
def raw_in_warehouse(context: AssetExecutionContext) -> MaterializeResult[None]:
    settings.check_ready()
    root = settings.landing_root()
    if settings.warehouse() == "bigquery":
        args = ["upload", "--project", settings.bq_project(), "--raw-root", str(root)]
        result = cli.run(args, context, prefix=BIGQUERY_PREFIX)
    else:
        db = settings.duckdb_path()
        args = ["load", "--raw-root", str(root), "--db", str(db)]
        result = cli.run(args, context)
    if result.exit_code != 0:
        raise Failure(
            description=f"`front-office {args[0]}` exited {result.exit_code}",
            metadata={"stderr_tail": MetadataValue.text("\n".join(result.tail))},
        )
    return MaterializeResult(metadata={"command": args[0]})


# The feeds dbt reports on (`_raw_feeds__sources.yml`), the check each gets, and its severity
# when stale (R4.3): `mlb` and `espn` are daily, so a failure there is an alert; `idmap` is
# weekly, always stale before the season's first Monday, and healthchecks.io already reports a
# missed id-map run, so its failure is a warning.
FRESHNESS_SOURCE_PREFIX = "source.front_office.raw_feeds."
FRESHNESS_FEEDS = {
    "mlb_runs": ("mlb_runs_fresh", AssetCheckSeverity.ERROR),
    "espn_runs": ("espn_runs_fresh", AssetCheckSeverity.ERROR),
    "idmap_runs": ("idmap_runs_fresh", AssetCheckSeverity.WARN),
}
SECONDS_PER_HOUR = 3600.0


def freshness_checks(sources: Mapping[str, Any]) -> list[AssetCheckResult]:
    """One check per feed from the parsed `sources.json`; raises when dbt could not judge a feed.

    A feed is fresh when dbt's status for it is `pass` (`warn` and `error` are its 36 hour and
    7 day limits). A feed with status `runtime error`, or one missing from the file, is not
    stale but unknown, so it raises `Failure` (R4.4); the message holds the feed's name and
    fixed text only, never dbt's own message.
    """
    results = {
        str(result.get("unique_id", "")).removeprefix(FRESHNESS_SOURCE_PREFIX): result
        for result in sources.get("results", [])
    }
    checks = []
    for feed, (check_name, severity) in FRESHNESS_FEEDS.items():
        result = results.get(feed)
        if result is None or result.get("status") == "runtime error":
            reason = "no result" if result is None else "runtime error"
            raise Failure(description=f"dbt source freshness: {feed}: {reason}")
        status = str(result["status"])
        age_seconds = result.get("max_loaded_at_time_ago_in_s")
        metadata: dict[str, Any] = {"status": status}
        if age_seconds is not None:
            metadata["age_hours"] = round(float(age_seconds) / SECONDS_PER_HOUR, 1)
        checks.append(
            AssetCheckResult(
                asset_key=AssetKey("source_freshness"),
                check_name=check_name,
                passed=status == "pass",
                severity=severity,
                metadata=metadata,
            )
        )
    return checks


def source_freshness_asset(upstream: Iterable[AssetKey]) -> Any:
    """`dbt source freshness` after the build, downstream of every dbt asset (R4.2, R4.3).

    dbt exits non-zero for a stale feed, so the command runs with `raise_on_error=False` and
    the verdict is read from `sources.json`: a stale feed fails its check, not the asset
    (R4.4). The checks are non-blocking: nothing is downstream of this asset.
    """

    @multi_asset(
        specs=[AssetSpec("source_freshness", deps=list(upstream))],
        check_specs=[
            AssetCheckSpec(name, asset="source_freshness", blocking=False)
            for name, _ in FRESHNESS_FEEDS.values()
        ],
        name="source_freshness",
    )
    def source_freshness(context: AssetExecutionContext, dbt: DbtCliResource) -> FetchResults:
        settings.check_ready()
        with dbt_environment():
            invocation = dbt.cli(
                ["source", "freshness", "--target", settings.dbt_target()], raise_on_error=False
            ).wait()
        artifact = invocation.get_artifact("sources.json")
        if artifact is None:
            raise Failure(description="dbt source freshness wrote no sources.json")
        checks = freshness_checks(artifact)
        yield MaterializeResult(asset_key="source_freshness")
        yield from checks

    return source_freshness
