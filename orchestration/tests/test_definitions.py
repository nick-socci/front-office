"""R1.2, R1.3, R1.4, R3.2, R3.4, R3.5, R4.1, R4.2: what `defs` holds and what `daily` selects.

These load the real dbt manifest (`dbt parse`, cached for the session) and build `Definitions`
under different settings. Nothing is executed.
"""

import importlib.util
from typing import Any

import pytest
from dagster import AssetKey, Definitions, in_process_executor

import front_office_pipeline
from front_office_pipeline import dbt_assets, settings

HAND_WRITTEN = {
    "mlb_captures",
    "espn_captures",
    "espn_matchup_days",
    "idmap_capture",
    "raw_in_warehouse",
    "source_freshness",
}


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("FO_WAREHOUSE", "FO_BQ_PROJECT", "FO_LANDING_ROOT", "FO_SEASON"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def dev_manifest(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """The real manifest of the `dev` target, whatever target the test sets."""
    manifest = dbt_assets.load_manifest("dev")
    monkeypatch.setattr(dbt_assets, "load_manifest", lambda target: manifest)
    return manifest


def keys(defs: Definitions) -> set[AssetKey]:
    return set(defs.resolve_asset_graph().get_all_asset_keys())


def expected_dbt_keys(manifest: dict[str, Any]) -> int:
    return sum(
        node["resource_type"] == "seed"
        or (node["resource_type"] == "model" and node["config"]["materialized"] != "ephemeral")
        for node in manifest["nodes"].values()
    )


def test_the_hand_written_assets_and_one_asset_per_non_ephemeral_model_and_seed() -> None:
    """R1.2, R1.3. Catches a model no asset covers, a dropped hand-written asset, a manifest
    change that breaks the translator (the source keys must all be `raw_in_warehouse`)."""
    defs = front_office_pipeline.build_defs()
    names = {key.to_user_string() for key in keys(defs)}
    assert names >= HAND_WRITTEN
    manifest = dbt_assets.load_manifest("dev")
    assert len(names - HAND_WRITTEN) == expected_dbt_keys(manifest)
    # No stray key from a source: the sources are `raw_in_warehouse`, nothing else.
    assert not any(name.startswith(("raw/", "raw_feeds/")) for name in names)


def test_the_module_level_defs_loads_without_settings() -> None:
    """`dagster definitions validate` loads `defs` with FO_WAREHOUSE unset."""
    assert isinstance(front_office_pipeline.defs, Definitions)


def test_dbt_models_with_sources_depend_on_raw_in_warehouse() -> None:
    """R1.2. Catches lineage that stops at the staging layer."""
    graph = front_office_pipeline.build_defs().resolve_asset_graph()
    games = AssetKey(["staging", "stg_raw__mlb_schedule"])
    assert AssetKey("raw_in_warehouse") in graph.get(games).parent_keys
    assert games in graph.get(AssetKey("raw_in_warehouse")).child_keys


def selected(job_defs: Definitions) -> set[str]:
    job = job_defs.resolve_job_def("daily")
    return {k.to_user_string() for k in job.asset_layer.executable_asset_keys}


def test_daily_leaves_out_the_id_map(dev_manifest: dict[str, Any]) -> None:
    """R4.1, R4.2. Catches a daily run that fetches the id map."""
    chosen = selected(front_office_pipeline.build_defs())
    assert "idmap_capture" not in chosen
    assert {"mlb_captures", "espn_captures", "espn_matchup_days", "raw_in_warehouse"} <= chosen
    assert any(name.startswith("marts/") for name in chosen)


def test_daily_has_source_freshness_on_duckdb_only(
    monkeypatch: pytest.MonkeyPatch, dev_manifest: dict[str, Any]
) -> None:
    """R3.5. Catches a BigQuery run that fails after a good build (the freshness filters are
    DuckDB SQL)."""
    assert "source_freshness" in selected(front_office_pipeline.build_defs())
    monkeypatch.setenv("FO_WAREHOUSE", "bigquery")
    monkeypatch.setenv("FO_BQ_PROJECT", "p")
    bigquery = front_office_pipeline.build_defs()
    assert "source_freshness" not in selected(bigquery)
    assert "mlb_captures" in selected(bigquery)


def test_daily_runs_its_steps_one_at_a_time(dev_manifest: dict[str, Any]) -> None:
    """R1.4. Catches parallel steps: two writers of the landing zone (`LandingLocked`)."""
    job = front_office_pipeline.build_defs().resolve_job_def("daily")
    assert job.executor_def is in_process_executor


def test_the_fetch_checks_are_registered_and_not_blocking(dev_manifest: dict[str, Any]) -> None:
    """R2.1. Catches a check dropped from the definitions."""
    graph = front_office_pipeline.build_defs().resolve_asset_graph()
    names = {(key.asset_key.to_user_string(), key.name) for key in graph.asset_check_keys}
    assert {
        (asset, "fetch_complete")
        for asset in ("mlb_captures", "espn_captures", "espn_matchup_days", "idmap_capture")
    } <= names


def test_the_build_excludes_the_unit_tests_and_names_the_target() -> None:
    """R3.4, R3.2. Catches a BigQuery build with unit tests (billed), or the wrong target."""
    duckdb = dbt_assets.build_args(environ={})
    assert duckdb == ["build", "--exclude-resource-type", "unit_test", "--target", "dev"]
    bigquery = dbt_assets.build_args(environ={"FO_WAREHOUSE": "bigquery", "FO_BQ_PROJECT": "p"})
    assert bigquery == [
        "build",
        "--exclude-resource-type",
        "unit_test",
        "--target",
        "bq",
        "--selector",
        "bigquery",
    ]


def test_bigquery_without_a_project_still_loads_the_definitions() -> None:
    """R3.2. The assets fail before any command; the code location must still load."""
    assert dbt_assets.manifest_target(environ={"FO_WAREHOUSE": "bigquery"}) == "dev"
    assert (
        dbt_assets.manifest_target(environ={"FO_WAREHOUSE": "bigquery", "FO_BQ_PROJECT": "p"})
        == "bq"
    )
    assert dbt_assets.manifest_target(environ={}) == "dev"


def test_the_dbt_resource_is_the_repositorys_project() -> None:
    defs = front_office_pipeline.build_defs()
    assert defs.resources is not None and "dbt" in defs.resources
    assert str(settings.DBT_DIR) == defs.resources["dbt"].project_dir


def test_a_bigquery_manifest_without_the_adapter_says_which_group_to_install(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The adapter is in the `bigquery` group, not `orchestration`: parsing the `bq` target
    without it must stop with the group's name, not an opaque dbt error at start-up."""
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: None)
    with pytest.raises(RuntimeError, match="--group bigquery"):
        dbt_assets.require_adapter("bq")
    dbt_assets.require_adapter("dev")  # DuckDB's adapter is in the default group
