"""R4.1, R3.6: `daily` runs end to end on the committed fixtures, with only the fetches faked.

The `load` is the real CLI, `dbt build` is real (the `ci` target, the unit tests excluded), and
`source_freshness` is real. Catches: a job that does not select what it should; a `load` and a
dbt build reading different landing zones; a dbt step that is not wired to the environment (the
landing root); a failure in the dbt asset wiring that the faked-asset tests cannot see.
"""

from collections.abc import Sequence
from pathlib import Path

import duckdb
import pytest
from dagster import DagsterInstance

import front_office_pipeline
from front_office_pipeline import cli, dbt_assets, season, settings

FIXTURES = settings.REPO_ROOT / "fixtures" / "landing"


def test_daily_builds_the_fixtures(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    database = tmp_path / "ci.duckdb"
    monkeypatch.delenv("FO_WAREHOUSE", raising=False)
    monkeypatch.setenv("FO_LANDING_ROOT", str(FIXTURES))
    monkeypatch.setenv("FO_DUCKDB_PATH", str(database))
    monkeypatch.setenv("FO_CI_DUCKDB_PATH", str(database))
    monkeypatch.setenv("FO_DASHBOARD_EXTRACT", str(tmp_path / "extract.duckdb"))
    monkeypatch.setenv("FO_SEASON", "2026")
    # The `ci` target is what the fixtures build on; the manifest is the same project's.
    monkeypatch.setattr(settings, "dbt_target", lambda *, environ=None: "ci")
    monkeypatch.setattr(season, "is_over", lambda root, year: False)

    real_run = cli.run
    fetches: list[list[str]] = []

    def run(
        args: Sequence[str], context: cli.HasLog, *, prefix: Sequence[str] = cli.FRONT_OFFICE
    ) -> cli.Result:
        if args[0] == "backfill":
            fetches.append(list(args))
            return cli.Result(0, ())
        return real_run(args, context, prefix=prefix)

    monkeypatch.setattr(cli, "run", run)
    monkeypatch.setattr(dbt_assets, "build_args", _ci_args(dbt_assets.build_args))

    job = front_office_pipeline.build_defs().resolve_job_def("daily")
    result = job.execute_in_process(instance=DagsterInstance.ephemeral(), raise_on_error=False)

    # The fixtures' newest capture is months old by design (`_raw_feeds__sources.yml`), so the
    # one failure expected is `dbt source freshness` saying so, as failed checks of
    # `source_freshness` (spec 0219 R4.4: a stale feed fails its check, not the step); every
    # step succeeded.
    assert [event.step_key for event in result.get_step_failure_events()] == []
    fresh = {e.check_name: e.passed for e in result.get_asset_check_evaluations()}
    assert fresh["mlb_runs_fresh"] is False
    assert fresh["espn_runs_fresh"] is False
    assert fetches == [
        ["backfill", "mlb", "--season", "2026", "--raw-root", str(FIXTURES)],
        ["backfill", "espn", "--season", "2026", "--raw-root", str(FIXTURES)],
    ]
    materialized = {
        event.asset_key.to_user_string()
        for event in result.get_asset_materialization_events()
        if event.asset_key
    }
    assert {"raw_in_warehouse", "mlb_captures", "espn_matchup_days"} <= materialized
    assert "source_freshness" in materialized
    assert any(name.startswith("marts/") for name in materialized)
    assert "idmap_capture" not in materialized
    # The one landing root: `load` recorded the fixtures' captures, and dbt read the same ones.
    with duckdb.connect(str(database), read_only=True) as connection:
        listed = connection.execute("select count(*) from raw.captures").fetchone()
        assert listed is not None and listed[0] > 0
        built = connection.execute("select count(*) from marts.dim_players").fetchone()
        assert built is not None and built[0] > 0


def test_no_extract_is_made_when_the_dbt_step_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """R2.6. Runs the real `daily` job and graph on an ephemeral instance with every command
    faked to succeed, and the dbt step made to fail (dbt refuses an unknown flag, exit 2).

    Catches an extract that does not wait for the build, or one that runs after it failed,
    which would publish marts of a build that did not finish. It proves Dagster skips the steps
    below a failed one in this graph; it does not run a real failing model or test.
    """
    monkeypatch.delenv("FO_WAREHOUSE", raising=False)
    monkeypatch.setenv("FO_LANDING_ROOT", str(tmp_path / "raw"))
    monkeypatch.setenv("FO_DUCKDB_PATH", str(tmp_path / "w.duckdb"))
    monkeypatch.setenv("FO_DASHBOARD_EXTRACT", str(tmp_path / "extract.duckdb"))
    monkeypatch.setenv("FO_SEASON", "2026")
    monkeypatch.setattr(season, "is_over", lambda root, year: False)
    commands: list[str] = []

    def run(
        args: Sequence[str], context: cli.HasLog, *, prefix: Sequence[str] = cli.FRONT_OFFICE
    ) -> cli.Result:
        commands.append(args[0])
        return cli.Result(0, ())

    monkeypatch.setattr(cli, "run", run)
    monkeypatch.setattr(
        dbt_assets, "build_args", lambda *, environ=None: ["build", "--no-such-flag"]
    )

    job = front_office_pipeline.build_defs().resolve_job_def("daily")
    result = job.execute_in_process(instance=DagsterInstance.ephemeral(), raise_on_error=False)

    assert not result.success
    failed = [event.step_key for event in result.get_step_failure_events()]
    assert failed == ["front_office_dbt"]
    assert "load" in commands  # the steps above the build did run
    assert "extract-marts" not in commands
    ran = {event.step_key for event in result.get_step_success_events()}
    assert "marts_extract" not in ran
    assert not any(
        event.asset_key and event.asset_key.to_user_string() == "marts_extract"
        for event in result.get_asset_materialization_events()
    )


def _ci_args(original: "object") -> "object":
    """The CI's build adds `--vars '{anonymize: true}'`: fixtures are anonymised, never real."""

    def args(*, environ: object = None) -> list[str]:
        return [*original(environ=environ), "--vars", "{anonymize: true}"]  # type: ignore[operator]

    return args
