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
- `source_freshness` runs `dbt source freshness` after the build; a non-zero exit raises.
- The order `mlb_captures` -> `espn_captures` -> `espn_matchup_days` -> `raw_in_warehouse` is
  declared as dependencies that carry no data: the fetches share the landing zone's writer lock,
  and a second writer fails rather than waits (R1.4). `idmap_capture` is upstream of
  `raw_in_warehouse` too but outside `daily` (R4.2).

Every asset first calls `settings.check_ready`, so a BigQuery run without a project fails before
any command has run (R3.2). Settings are read when an asset runs, not when it is defined.
"""

from collections.abc import Generator, Iterable
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
    root, year = settings.landing_root(), season.current()
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
    root, year = settings.landing_root(), season.current()
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
    root, year = settings.landing_root(), season.current()
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


def source_freshness_asset(upstream: Iterable[AssetKey]) -> Any:
    """`dbt source freshness` after the build, downstream of every dbt asset (R1.2, R3.5)."""

    @asset(key="source_freshness", deps=list(upstream))
    def source_freshness(
        context: AssetExecutionContext, dbt: DbtCliResource
    ) -> MaterializeResult[None]:
        settings.check_ready()
        with dbt_environment():
            # `wait()` raises when dbt exits non-zero, which fails the asset (R2.2).
            dbt.cli(["source", "freshness", "--target", settings.dbt_target()]).wait()
        return MaterializeResult()

    return source_freshness
