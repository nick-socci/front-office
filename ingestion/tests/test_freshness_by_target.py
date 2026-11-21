"""The source-freshness declarations render per warehouse (spec 0219, R4.1; ADR 0143).

`dbt source freshness` runs on both warehouses, and the YAML in `_raw_feeds__sources.yml`
cannot call a project macro, so it branches on `target.type` itself. Three renderings are held:

- `ci`: dbt parses the project for DuckDB, and the declarations are read from `manifest.json`.
  This shows dbt renders the Jinja in these keys at all.
- `bigquery`: the YAML's values rendered with Jinja and `target.type == 'bigquery'`, as dbt
  renders them. CI and the gates install no BigQuery adapter (it is the `bigquery` group), so
  dbt itself cannot parse the `bq` target there; this case runs everywhere.
- `bq`: dbt parses the `bq` target (a dummy project id: parse opens no connection), when the
  adapter is installed; skipped otherwise. It ties the `bigquery` rendering to dbt's own.

They catch a branch that renders DuckDB SQL on BigQuery (`strptime`, `json_extract_string`),
BigQuery SQL on DuckDB, or the id map's filter changing on either.
"""

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import jinja2
import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
DBT_ROOT = REPO / "dbt"
DBT = Path(sys.executable).parent / "dbt"

SOURCES = ["mlb_runs", "espn_runs", "idmap_runs"]
SOURCES_YAML = DBT_ROOT / "models/staging/_raw_feeds__sources.yml"
DUCKDB_PARSE = "strptime(fetched_at, '%Y%m%dT%H%M%SZ')"
BIGQUERY_PARSE = "parse_timestamp('%Y%m%dT%H%M%SZ', fetched_at)"
LOADED_AT = {"ci": DUCKDB_PARSE, "bigquery": BIGQUERY_PARSE, "bq": BIGQUERY_PARSE}
SEASON_FUNCTION = {"ci": "json_extract_string", "bigquery": "json_value", "bq": "json_value"}
OTHER_FUNCTION = {
    "ci": "json_value",
    "bigquery": "json_extract_string",
    "bq": "json_extract_string",
}
IDMAP_FILTER = "source = 'idmap' and endpoint = 'player_id_map'"


def parsed_sources(target: str, path: Path) -> dict[str, dict[str, object]]:
    if not (DBT_ROOT / "dbt_packages" / "dbt_utils").exists():
        deps = subprocess.run(
            [str(DBT), "deps"],
            cwd=DBT_ROOT,
            env={**os.environ, "DBT_PROFILES_DIR": str(DBT_ROOT)},
            capture_output=True,
            text=True,
            check=False,
        )
        assert deps.returncode == 0, deps.stdout + deps.stderr
    env = {**os.environ, "DBT_PROFILES_DIR": str(DBT_ROOT)}
    env["FO_CI_DUCKDB_PATH"] = str(path / "unused_ci.duckdb")
    env["FO_DUCKDB_PATH"] = str(path / "unused_dev.duckdb")
    env["FO_BQ_PROJECT"] = "fo-parse-only"
    result = subprocess.run(
        [str(DBT), "parse", "--target", target, "--target-path", str(path)],
        cwd=DBT_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    manifest = json.loads((path / "manifest.json").read_text())
    return {name: manifest["sources"][f"source.front_office.raw_feeds.{name}"] for name in SOURCES}


def rendered_with_jinja(target_type: str) -> dict[str, dict[str, object]]:
    """Each declaration with its `loaded_at_field` and filter rendered for `target_type`."""
    environment = jinja2.Environment(undefined=jinja2.StrictUndefined)
    target = {"type": target_type}
    raw_feeds = next(
        source
        for source in yaml.safe_load(SOURCES_YAML.read_text())["sources"]
        if source["name"] == "raw_feeds"
    )
    sources: dict[str, dict[str, object]] = {}
    for table in raw_feeds["tables"]:
        freshness = dict(table["freshness"])
        freshness["filter"] = environment.from_string(freshness["filter"]).render(target=target)
        loaded_at = environment.from_string(table["loaded_at_field"]).render(target=target)
        sources[table["name"]] = {"loaded_at_field": loaded_at, "freshness": freshness}
    return sources


@pytest.fixture(scope="module", params=["ci", "bigquery", "bq"])
def rendered(
    request: pytest.FixtureRequest, tmp_path_factory: pytest.TempPathFactory
) -> tuple[str, dict[str, dict[str, object]]]:
    target: str = request.param
    if target == "bigquery":
        return target, rendered_with_jinja("bigquery")
    if target == "bq" and importlib.util.find_spec("dbt.adapters.bigquery") is None:
        pytest.skip("no BigQuery adapter installed: the `bigquery` rendering stands in")
    path = tmp_path_factory.mktemp(f"dbt_target_{target}")
    return target, parsed_sources(target, path)


def test_loaded_at_field_is_the_warehouses_timestamp_parse(
    rendered: tuple[str, dict[str, dict[str, object]]],
) -> None:
    target, sources = rendered
    for name in SOURCES:
        assert sources[name]["loaded_at_field"] == LOADED_AT[target], (target, name)


def test_season_filters_use_the_warehouses_json_function(
    rendered: tuple[str, dict[str, dict[str, object]]],
) -> None:
    target, sources = rendered
    for name in ("mlb_runs", "espn_runs"):
        freshness: dict[str, str] = sources[name]["freshness"]  # type: ignore[assignment]
        text = freshness["filter"]
        assert f"{SEASON_FUNCTION[target]}(partitions, '$.season')" in text, (target, name)
        assert OTHER_FUNCTION[target] not in text, (target, name)


def test_the_idmap_filter_is_the_same_on_both_warehouses(
    rendered: tuple[str, dict[str, dict[str, object]]],
) -> None:
    target, sources = rendered
    freshness: dict[str, str] = sources["idmap_runs"]["freshness"]  # type: ignore[assignment]
    assert freshness["filter"] == IDMAP_FILTER, target
