"""R1.2, R1.3, R1.4, R3.2, R3.4, R3.5, R4.1, R4.2: what `defs` holds and what `daily` selects.

These load the real dbt manifest (`dbt parse`, cached for the session) and build `Definitions`
under different settings. Nothing is executed.
"""

import copy
import importlib.util
from typing import Any

import dagster_dbt
import pytest
from dagster import (
    AssetKey,
    DagsterRunStatus,
    DefaultSensorStatus,
    Definitions,
    in_process_executor,
)
from dagster_dbt.core.dbt_cli_event import DbtCoreCliEventMessage

import front_office_pipeline
from front_office_pipeline import dbt_assets, settings

HAND_WRITTEN = {
    "mlb_captures",
    "espn_captures",
    "espn_matchup_days",
    "idmap_capture",
    "raw_in_warehouse",
    "source_freshness",
    "marts_extract",
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


def test_daily_has_source_freshness_under_both_warehouses(
    monkeypatch: pytest.MonkeyPatch, dev_manifest: dict[str, Any]
) -> None:
    """R4.2 (0219, replacing 0217 R3.5). Catches a BigQuery daily run that never checks the
    feeds' freshness, which is where the alert is needed."""
    assert "source_freshness" in selected(front_office_pipeline.build_defs())
    monkeypatch.setenv("FO_WAREHOUSE", "bigquery")
    monkeypatch.setenv("FO_BQ_PROJECT", "p")
    bigquery = front_office_pipeline.build_defs()
    assert "source_freshness" in selected(bigquery)
    assert "mlb_captures" in selected(bigquery)


@pytest.mark.parametrize("warehouse", ["duckdb", "bigquery"])
def test_three_running_sensors_monitor_exactly_the_two_jobs(
    monkeypatch: pytest.MonkeyPatch, dev_manifest: dict[str, Any], warehouse: str
) -> None:
    """R1.3. Catches a sensor missing for one end state, one that starts stopped (Dagster's
    default), or one that monitors every job."""
    monkeypatch.setenv("FO_WAREHOUSE", warehouse)
    monkeypatch.setenv("FO_BQ_PROJECT", "p")
    defs = front_office_pipeline.build_defs()
    made: list[Any] = list(defs.sensors or [])
    assert len(made) == 3
    assert {s._run_status for s in made} == {
        DagsterRunStatus.SUCCESS,
        DagsterRunStatus.FAILURE,
        DagsterRunStatus.CANCELED,
    }
    for sensor in made:
        assert sensor.default_status == DefaultSensorStatus.RUNNING
        assert sorted(job.name for job in sensor._monitored_jobs or []) == ["daily", "idmap"]


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


def test_sources_that_models_read_share_one_asset_key_as_on_bigquery() -> None:
    """On BigQuery the models read the `raw.*` sources, so dagster-dbt sees 15 sources the
    translator maps to one key (`raw_in_warehouse`) and refuses unless duplicate source keys
    are allowed. On DuckDB no model reads a source, so every other test misses this: give a
    model the sources as parents, as the BigQuery manifest does."""
    manifest = copy.deepcopy(dbt_assets.load_manifest("dev"))
    sources = [unique_id for unique_id in manifest["sources"]]
    model = next(n for n in manifest["nodes"].values() if n["name"] == "stg_mlb__games")
    model["depends_on"]["nodes"] = [*model["depends_on"]["nodes"], *sources]
    for unique_id in sources:
        manifest["child_map"][unique_id] = [
            *manifest["child_map"].get(unique_id, []),
            model["unique_id"],
        ]
    manifest["parent_map"][model["unique_id"]] = [
        *manifest["parent_map"][model["unique_id"]],
        *sources,
    ]

    definition = dbt_assets.build_dbt_assets(manifest)

    assert AssetKey("raw_in_warehouse") in {
        dep for spec in definition.specs for dep in (d.asset_key for d in spec.deps)
    }


def test_the_manifest_dagster_gets_survives_a_test_event_whose_parent_is_a_function(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """dagster-dbt 0.29.30 looks each parent of a singular test up in `nodes` or `sources` and
    crashes (`'NoneType' object has no attribute 'get'`) on a dbt function. On the BigQuery
    target two lineup tests depend on `sum_in_order`, which stopped the real build on
    mothership at node 539 of 579. This captures the manifest `build_dbt_assets` really hands
    to `@dbt_assets`, then runs dagster-dbt's own test-event conversion over it: it must not
    crash, and dbt's manifest (never read from here) keeps its edges."""
    manifest = copy.deepcopy(dbt_assets.load_manifest("dev"))
    test = next(n for n in manifest["nodes"].values() if n["resource_type"] == "test")
    function_id = "function.front_office.sum_in_order"
    test["depends_on"]["nodes"] = [*test["depends_on"]["nodes"], function_id]

    handed: list[Any] = []
    real_decorator = dagster_dbt.dbt_assets

    def spy(**kwargs: Any) -> Any:
        handed.append(kwargs["manifest"])
        return real_decorator(**kwargs)

    monkeypatch.setattr("front_office_pipeline.dbt_assets.dbt_assets", spy)
    dbt_assets.build_dbt_assets(manifest)
    given = handed[0]

    translator = dbt_assets.SourceToRawInWarehouse()
    event = DbtCoreCliEventMessage(
        raw_event={"data": {"node_info": {"unique_id": test["unique_id"]}}, "info": {}},
        event_history_metadata={},
    )

    def convert(manifest_given: Any) -> list[Any]:
        return list(event._to_observation_events_for_test(None, translator, manifest_given, {}))

    assert len(convert(given)) == len(test["depends_on"]["nodes"]) - 1
    assert function_id in manifest["nodes"][test["unique_id"]]["depends_on"]["nodes"]
    # The control: without the workaround dagster-dbt fails as it did on mothership. If this
    # stops raising, dagster-dbt has fixed it and `without_function_parents` can go.
    with pytest.raises(AttributeError):
        convert(manifest)


def test_without_function_parents_leaves_other_tests_alone() -> None:
    manifest = copy.deepcopy(dbt_assets.load_manifest("dev"))
    tests = [n for n in manifest["nodes"].values() if n["resource_type"] == "test"]
    cleaned = dbt_assets.without_function_parents(manifest)
    for node in tests:
        assert cleaned["nodes"][node["unique_id"]]["depends_on"] == node["depends_on"]


def exposure_model_keys(manifest: dict[str, Any]) -> set[AssetKey]:
    """The asset keys of the models `front_office_dashboard` names, read from the manifest."""
    exposure = manifest["exposures"]["exposure.front_office.front_office_dashboard"]
    names = exposure["depends_on"]["nodes"]
    assert names and all(name.startswith("model.") for name in names)
    return {AssetKey(["marts", manifest["nodes"][name]["name"]]) for name in names}


def test_marts_extract_depends_on_exactly_the_models_the_exposure_names(
    dev_manifest: dict[str, Any],
) -> None:
    """R2.1, R2.6. Catches deps that drift from the exposure (a mart added to it but not waited
    for, so the extract could run before it is built), or a hard-coded list."""
    graph = front_office_pipeline.build_defs().resolve_asset_graph()
    expected = exposure_model_keys(dev_manifest)
    assert len(expected) >= 11
    assert graph.get(AssetKey("marts_extract")).parent_keys == expected
    # Nothing waits for it: it is the last step.
    assert graph.get(AssetKey("marts_extract")).child_keys == set()


def test_daily_runs_marts_extract_and_idmap_does_not(dev_manifest: dict[str, Any]) -> None:
    """R2.1. Catches an extract left out of `daily`, or one the weekly id-map run makes."""
    defs = front_office_pipeline.build_defs()
    assert "marts_extract" in selected(defs)
    idmap = {
        k.to_user_string() for k in defs.resolve_job_def("idmap").asset_layer.executable_asset_keys
    }
    assert idmap == {"idmap_capture"}


def test_the_exposure_must_name_models_or_the_location_does_not_load(
    dev_manifest: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Catches an extract with no deps (it would run first, on the previous build) when the
    exposure is renamed or emptied."""
    emptied = copy.deepcopy(dev_manifest)
    del emptied["exposures"]["exposure.front_office.front_office_dashboard"]
    monkeypatch.setattr(dbt_assets, "load_manifest", lambda target: emptied)
    with pytest.raises(KeyError, match="front_office_dashboard"):
        front_office_pipeline.build_defs()
