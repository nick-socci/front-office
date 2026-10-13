"""The six staging models built a season at a time (spec 0143, R1.1, R1.5, R1.7, R5.4).

Six staging models parse one large payload per game or per scoring period. On DuckDB they
are incremental models with the microbatch strategy: dbt runs each once per calendar year,
filtering every input that declares an event time to that year. These tests read dbt's
manifest and hold the project to that: exactly those six are batched, with the settings
that keep one season in memory at a time, and each reads only inputs dbt can filter.

dbt is run as a subprocess, on the `ci` (DuckDB) target, with its target directory in a
temporary place. `dbt parse` opens no connection. It needs the dbt packages, which CI
installs only after pytest, so the first use installs them if they are missing.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[2]
DBT_ROOT = REPO / "dbt"
DBT = Path(sys.executable).parent / "dbt"

BATCHED = {
    "stg_mlb__batting_game_logs",
    "stg_mlb__pitching_game_logs",
    "stg_espn__roster_entries",
    "stg_espn__roster_entry_slots",
    "stg_espn__player_game_stats",
    "stg_espn__matchup_days",
}

# Inputs a batched model may read whole, by model: {batched model: {input: reason}}. A
# lookup has no event time, so every batch reads all of it; that is safe only if the join
# to it cannot multiply rows, and each entry says why. Decided by the owner on 2026-10-13.
LOOKUPS: dict[str, dict[str, str]] = {
    "stg_espn__roster_entry_slots": {
        "stg_espn__lineup_slot_limits": (
            "joined on league, season and slot, which is that view's unique key, so a batch "
            "that reads it whole gains no row; it keeps an eligibility only for a slot the "
            "league-season has (spec 0083, the owner's decision of 2026-10-12)"
        ),
    },
}


@pytest.fixture(scope="module")
def manifest(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    """The parsed project on the ci target, as dbt writes it to manifest.json."""
    target_path = tmp_path_factory.mktemp("dbt_target")
    env = {k: v for k, v in os.environ.items() if k != "FO_BQ_PROJECT"}
    env["DBT_PROFILES_DIR"] = str(DBT_ROOT)
    env["FO_CI_DUCKDB_PATH"] = str(target_path / "unused_ci.duckdb")
    env["FO_DUCKDB_PATH"] = str(target_path / "unused_dev.duckdb")
    if not (DBT_ROOT / "dbt_packages" / "dbt_utils").exists():
        deps = subprocess.run(
            [str(DBT), "deps"], cwd=DBT_ROOT, env=env, capture_output=True, text=True, check=False
        )
        assert deps.returncode == 0, deps.stdout + deps.stderr
    parse = subprocess.run(
        [str(DBT), "parse", "--target", "ci", "--target-path", str(target_path)],
        cwd=DBT_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert parse.returncode == 0, parse.stdout + parse.stderr
    return json.loads((target_path / "manifest.json").read_text())  # type: ignore[no-any-return]


def model_nodes(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        node["name"]: node
        for node in manifest["nodes"].values()
        if node["resource_type"] == "model"
    }


def test_exactly_the_six_models_are_microbatch(manifest: dict[str, Any]) -> None:
    """Catches a seventh model batched by accident, and one of the six left a plain table.
    Any other incremental materialization is caught too: the set is of incremental models
    of every strategy, and each must be a microbatch one."""
    models = model_nodes(manifest)
    batched = {
        name
        for name, node in models.items()
        if node["config"].get("materialized") == "incremental"
        and node["config"].get("incremental_strategy") == "microbatch"
    }
    incremental = {
        name for name, node in models.items() if node["config"].get("materialized") == "incremental"
    }
    assert batched == incremental, (
        f"incremental but not microbatch: {sorted(incremental - batched)}"
    )
    assert batched == BATCHED, (
        f"not batched: {sorted(BATCHED - batched)}; batched but not in the six: "
        f"{sorted(batched - BATCHED)}"
    )


@pytest.mark.parametrize("name", sorted(BATCHED))
def test_the_batches_run_one_at_a_time_by_year_and_fail_on_an_old_table(
    manifest: dict[str, Any], name: str
) -> None:
    """Catches batches of one model running at once (several seasons in memory), a batch
    size other than a year, and an old table without season_start being silently kept."""
    config = model_nodes(manifest)[name]["config"]
    assert config.get("concurrent_batches") is False, name
    assert config.get("on_schema_change") == "fail", name
    assert config.get("batch_size") == "year", name
    assert config.get("event_time") == "season_start", name


@pytest.mark.parametrize("name", sorted(BATCHED))
def test_every_input_of_a_batched_model_is_a_seed_or_has_an_event_time(
    manifest: dict[str, Any], name: str
) -> None:
    """Catches an input dbt cannot filter to a batch: it is read whole by every batch, so
    every batch would insert every season's rows. A lookup is the one exception: an input
    listed in LOOKUPS for this model, which is read whole but joined on its unique key, so
    it adds no row. Each entry must say why it cannot multiply rows."""
    node = model_nodes(manifest)[name]
    unfiltered = []
    for parent_id in node["depends_on"]["nodes"]:
        parent = manifest["nodes"].get(parent_id) or manifest["sources"].get(parent_id)
        assert parent is not None, f"{name} depends on {parent_id}, not in the manifest"
        if parent["resource_type"] == "seed":
            continue
        if parent["name"] in LOOKUPS.get(name, {}):
            continue
        if not parent.get("config", {}).get("event_time"):
            unfiltered.append(parent_id)
    assert not unfiltered, f"{name} reads inputs with no event_time: {unfiltered}"


@pytest.mark.parametrize(
    ("name", "lookup"),
    sorted((name, lookup) for name, lookups in LOOKUPS.items() for lookup in lookups),
)
def test_every_lookup_is_still_a_real_input_with_a_unique_key(
    manifest: dict[str, Any], name: str, lookup: str
) -> None:
    """Catches a stale exception: the model is no longer batched, no longer reads the
    lookup, or the lookup lost the uniqueness test that makes reading it whole safe."""
    assert name in BATCHED, f"{name} is not a batched model"
    models = model_nodes(manifest)
    parents = {
        manifest["nodes"][parent_id]["name"]
        for parent_id in models[name]["depends_on"]["nodes"]
        if parent_id in manifest["nodes"]
    }
    assert lookup in parents, f"{name} no longer reads {lookup}"
    lookup_id = models[lookup]["unique_id"]
    unique_tests = [
        node
        for node in manifest["nodes"].values()
        if node["resource_type"] == "test"
        and node.get("attached_node") == lookup_id
        and node.get("test_metadata", {}).get("name") in {"unique", "unique_combination_of_columns"}
    ]
    assert unique_tests, f"{lookup} has no unique or unique_combination_of_columns test"
