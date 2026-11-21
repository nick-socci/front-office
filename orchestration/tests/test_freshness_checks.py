"""R4.3, R4.4: `source_freshness` turns dbt's `sources.json` into one check per feed.

`freshness_checks` is held on dicts shaped like dbt's file; the asset is held with the dbt
invocation faked (`DbtCliResource.cli`), so no dbt runs.

Catches: a stale feed that fails the asset (it must only fail its check); a warn-status feed
reported as passed; `idmap` stale as an ERROR (it is weekly and stale before the season's first
Monday); a `runtime error` or a missing artifact passing silently as "all fresh"; an age in
seconds, or unrounded; a check missing for a feed dbt did not report.
"""

from pathlib import Path
from typing import Any

import pytest
from dagster import AssetCheckSeverity, Failure, materialize
from dagster_dbt import DbtCliResource

from front_office_pipeline import assets, settings

PREFIX = "source.front_office.raw_feeds."
FEEDS = ("mlb_runs", "espn_runs", "idmap_runs")
CHECKS = ("mlb_runs_fresh", "espn_runs_fresh", "idmap_runs_fresh")


def sources(**statuses: str) -> dict[str, Any]:
    """A `sources.json` with one result per feed: `pass` unless the keyword says otherwise."""
    ages = {"mlb_runs": 37800.0, "espn_runs": 134999.96, "idmap_runs": 90000.0}
    results = []
    for feed in FEEDS:
        status = statuses.get(feed, "pass")
        result: dict[str, Any] = {"unique_id": PREFIX + feed, "status": status}
        if status != "runtime error":
            result["max_loaded_at_time_ago_in_s"] = ages[feed]
        results.append(result)
    return {"metadata": {}, "results": results, "elapsed_time": 0.1}


def by_name(results: list[Any]) -> dict[str, Any]:
    return {r.check_name: r for r in results}


def test_all_fresh_gives_three_passing_checks() -> None:
    got = assets.freshness_checks(sources())
    assert [r.check_name for r in got] == list(CHECKS)
    assert all(r.passed for r in got)
    assert {r.asset_key and r.asset_key.to_user_string() for r in got} == {"source_freshness"}


def test_a_warn_feed_fails_its_check_with_the_feed_severity_and_metadata() -> None:
    got = by_name(assets.freshness_checks(sources(espn_runs="warn", idmap_runs="warn")))
    espn, idmap = got["espn_runs_fresh"], got["idmap_runs_fresh"]
    assert (espn.passed, espn.severity) == (False, AssetCheckSeverity.ERROR)
    assert (idmap.passed, idmap.severity) == (False, AssetCheckSeverity.WARN)
    assert espn.metadata["status"].value == "warn"
    assert espn.metadata["age_hours"].value == 37.5  # 134999.96 s, in hours to 0.1
    assert got["mlb_runs_fresh"].passed
    assert got["mlb_runs_fresh"].metadata["age_hours"].value == 10.5


def test_an_error_feed_fails_its_check() -> None:
    got = by_name(assets.freshness_checks(sources(mlb_runs="error")))
    mlb = got["mlb_runs_fresh"]
    assert (mlb.passed, mlb.severity) == (False, AssetCheckSeverity.ERROR)
    assert mlb.metadata["status"].value == "error"


def test_a_runtime_error_raises_a_failure_that_names_the_feed_only() -> None:
    with pytest.raises(Failure, match="mlb_runs") as raised:
        assets.freshness_checks(sources(mlb_runs="runtime error"))
    assert "runtime error" in str(raised.value.description)


def test_a_feed_dbt_did_not_report_raises() -> None:
    partial = sources()
    partial["results"] = partial["results"][:2]
    with pytest.raises(Failure, match="idmap_runs"):
        assets.freshness_checks(partial)


@pytest.fixture
def ready(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("FO_LANDING_ROOT", str(tmp_path / "raw"))
    monkeypatch.delenv("FO_WAREHOUSE", raising=False)
    monkeypatch.delenv("FO_BQ_PROJECT", raising=False)


class FakeInvocation:
    def __init__(self, artifact: dict[str, Any] | None) -> None:
        self.artifact = artifact

    def wait(self) -> "FakeInvocation":
        return self

    def get_artifact(self, name: str) -> dict[str, Any]:
        """As the real one: it reads the file, so an absent one raises, never returns `None`."""
        assert name == "sources.json"
        if self.artifact is None:
            raise FileNotFoundError(name)
        return self.artifact


def run_asset(
    monkeypatch: pytest.MonkeyPatch, artifact: dict[str, Any] | None
) -> tuple[Any, list[Any]]:
    calls: list[Any] = []

    def cli(self: object, args: list[str], **kwargs: Any) -> FakeInvocation:
        calls.append((args, kwargs))
        return FakeInvocation(artifact)

    monkeypatch.setattr(DbtCliResource, "cli", cli)
    resource = DbtCliResource(project_dir=str(settings.DBT_DIR))
    result = materialize(
        [assets.source_freshness_asset([])], resources={"dbt": resource}, raise_on_error=False
    )
    return result, calls


@pytest.mark.usefixtures("ready")
def test_the_asset_materializes_and_checks_when_feeds_are_stale(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """R4.4: a stale feed alone does not fail the asset; only its check."""
    result, calls = run_asset(monkeypatch, sources(mlb_runs="error", espn_runs="warn"))
    assert result.success
    [(args, kwargs)] = calls
    assert args[:2] == ["source", "freshness"]
    assert kwargs == {"raise_on_error": False}
    evaluated = {e.check_name: e for e in result.get_asset_check_evaluations()}
    assert set(evaluated) == set(CHECKS)
    assert [evaluated[c].passed for c in CHECKS] == [False, False, True]
    assert {e.asset_key.to_user_string() for e in result.get_asset_materialization_events()} == {
        "source_freshness"
    }


@pytest.mark.usefixtures("ready")
def test_no_artifact_fails_the_asset_with_fixed_text(monkeypatch: pytest.MonkeyPatch) -> None:
    result, _ = run_asset(monkeypatch, None)
    assert not result.success
    [failure] = result.get_step_failure_events()
    assert failure.step_key == "source_freshness"
    error = failure.event_specific_data.error
    assert error.cls_name == "Failure"
    assert "dbt source freshness wrote no sources.json" in error.message
    assert error.cause is not None
    assert error.cause.cls_name == "FileNotFoundError"


@pytest.mark.usefixtures("ready")
def test_a_runtime_error_fails_the_asset(monkeypatch: pytest.MonkeyPatch) -> None:
    result, _ = run_asset(monkeypatch, sources(idmap_runs="runtime error"))
    assert not result.success


def test_the_three_checks_are_declared_and_not_blocking() -> None:
    definition = assets.source_freshness_asset([])
    specs = list(definition.check_specs)
    assert sorted(spec.name for spec in specs) == sorted(CHECKS)
    assert all(spec.blocking is False for spec in specs)
