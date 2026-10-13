"""The BigQuery slice, its target and its dependency group (spec 0130, R1 and R2).

The slice is fixed by a dbt selector, so that what is ported is written down once. These
tests ask dbt what the selector selects and hold it to the names the spec counted; they
also hold the `bq` target to its promises without ever connecting to BigQuery: it must
not break `dev` or `ci` for someone with no Google project, must not carry a credential,
and its adapter must stay out of what CI installs.

dbt is run as a subprocess, on the `ci` target, with its target directory in a temporary
place. `dbt ls` and `dbt parse` open no connection. They need the dbt packages, which CI
installs only after pytest, so the first use installs them if they are missing.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
DBT_ROOT = REPO / "dbt"
DBT = Path(sys.executable).parent / "dbt"
SELECTOR = "bigquery_slice"
ROOTS = (
    "fct_matchup_results",
    "rec_espn__category_result_differences",
    "int_fantasy__category_scales",
)

SLICE_MODELS = {
    "fct_matchup_category_scores",
    "fct_matchup_results",
    "int_fantasy__categories",
    "int_fantasy__category_scales",
    "int_fantasy__league_seasons",
    "int_fantasy__matchup_periods",
    "int_fantasy__matchup_side_totals",
    "int_fantasy__matchup_sides",
    "int_fantasy__matchup_stat_values",
    "int_fantasy__player_crosswalk",
    "int_fantasy__reported_matchup_margins",
    "int_fantasy__roster_days",
    "int_fantasy__started_player_days",
    "int_fantasy__stat_components",
    "int_mlb__game_dates",
    "int_mlb__player_game_days",
    "rec_espn__category_result_differences",
    "rec_espn__matchup_stat_differences",
    "stg_espn__league_settings",
    "stg_espn__matchup_category_results",
    "stg_espn__matchup_periods",
    "stg_espn__matchups",
    "stg_espn__pro_games",
    "stg_espn__roster_entries",
    "stg_espn__scoring_categories",
    "stg_espn__scoring_periods",
    "stg_idmap__players",
    "stg_mlb__batting_game_logs",
    "stg_mlb__games",
    "stg_mlb__pitching_game_logs",
    "stg_raw__season_responses",
}
SLICE_SEEDS = {
    "espn_lineup_slots",
    "espn_player_positions",
    "espn_reconciliation_residuals",
    "espn_stat_components",
    "espn_stat_ids",
    "mlb_game_states",
}


def run_dbt(target_path: Path, *args: str, target: str = "ci") -> subprocess.CompletedProcess[str]:
    """One dbt command from dbt/, with FO_BQ_PROJECT unset and no warehouse file made here."""
    env = {k: v for k, v in os.environ.items() if k != "FO_BQ_PROJECT"}
    env["DBT_PROFILES_DIR"] = str(DBT_ROOT)
    env["FO_CI_DUCKDB_PATH"] = str(target_path / "unused_ci.duckdb")
    env["FO_DUCKDB_PATH"] = str(target_path / "unused_dev.duckdb")
    return subprocess.run(
        [str(DBT), *args, "--target", target, "--target-path", str(target_path)],
        cwd=DBT_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.fixture(scope="module")
def target_path(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("dbt_target")
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
    return path


def listed(result: subprocess.CompletedProcess[str]) -> list[dict[str, object]]:
    assert result.returncode == 0, result.stdout + result.stderr
    return [json.loads(line) for line in result.stdout.splitlines() if line.startswith("{")]


@pytest.fixture(scope="module")
def selected(target_path: Path) -> list[dict[str, object]]:
    """Everything the selector selects: name, resource type, materialization, parents."""
    return listed(
        run_dbt(
            target_path,
            "ls",
            "--selector",
            SELECTOR,
            "--output",
            "json",
            "--output-keys",
            "name resource_type config depends_on test_metadata original_file_path",
            "-q",
        )
    )


def names(rows: list[dict[str, object]], resource_type: str) -> set[str]:
    return {str(r["name"]) for r in rows if r["resource_type"] == resource_type}


def test_the_slice_is_the_thirty_one_models_and_six_seeds_of_the_spec(
    selected: list[dict[str, object]],
) -> None:
    """Catches a model or seed joining the slice through a new ref, or leaving it, unnoticed."""
    assert names(selected, "model") == SLICE_MODELS
    assert names(selected, "seed") == SLICE_SEEDS


def test_the_slice_has_no_python_model_and_the_materializations_counted(
    selected: list[dict[str, object]],
) -> None:
    """Catches the lineup solver, or any Python model, being pulled into the slice."""
    models = [r for r in selected if r["resource_type"] == "model"]
    assert all(str(r["original_file_path"]).endswith(".sql") for r in models)
    kinds = sorted(r["config"]["materialized"] for r in models)  # type: ignore[index]
    # Listed on the ci target: three of the 21 tables are incremental (microbatch) on DuckDB
    # and tables on BigQuery (spec 0143, ADR 0060).
    counted = (
        kinds.count("table"),
        kinds.count("incremental"),
        kinds.count("view"),
        kinds.count("ephemeral"),
    )
    assert counted == (18, 3, 9, 1)


def test_the_slice_takes_the_tests_counted(selected: list[dict[str, object]]) -> None:
    """Catches a test added to or lost from the slice: the counts are the spec's."""
    tests = [r for r in selected if r["resource_type"] == "test"]
    generic = [r for r in tests if r.get("test_metadata")]
    assert (len(tests), len(generic), len(tests) - len(generic)) == (208, 182, 26)
    assert len(names(selected, "unit_test")) == 65


def test_no_selected_test_reads_a_relation_outside_the_slice(
    selected: list[dict[str, object]],
) -> None:
    """Catches a test that would look, on BigQuery, for a model that was never built there."""
    inside = {
        f"{kind}.front_office.{name}"
        for kind, known in (("model", SLICE_MODELS), ("seed", SLICE_SEEDS))
        for name in known
    }
    for row in selected:
        if row["resource_type"] not in ("test", "unit_test"):
            continue
        parents = {
            node
            for node in row["depends_on"]["nodes"]  # type: ignore[index]
            if node.startswith(("model.", "seed."))
        }
        assert parents <= inside, f"{row['name']} reads {sorted(parents - inside)}"


def test_the_selector_takes_every_test_wholly_inside_the_slice(
    target_path: Path, selected: list[dict[str, object]]
) -> None:
    """Catches a test left out because its parents lie in two members of the union:
    `cautious` is applied to each member alone, so such a test has to be named."""
    whole = listed(
        run_dbt(
            target_path,
            "ls",
            "--select",
            " ".join(f"+{root}" for root in ROOTS),
            "--indirect-selection",
            "cautious",
            "--resource-type",
            "test",
            "--output",
            "json",
            "--output-keys",
            "name resource_type",
            "-q",
        )
    )
    assert names(selected, "test") == names(whole, "test")


@pytest.mark.parametrize("target", ["dev", "ci"])
def test_dev_and_ci_parse_with_no_bigquery_project_set(target_path: Path, target: str) -> None:
    """Catches the new target breaking every build for someone with no Google project."""
    result = run_dbt(target_path, "parse", target=target)
    assert result.returncode == 0, result.stdout + result.stderr


def profile() -> dict[str, object]:
    outputs = yaml.safe_load((DBT_ROOT / "profiles.yml").read_text())["front_office"]
    return outputs  # type: ignore[no-any-return]


def test_dev_stays_the_default_target() -> None:
    """Catches the default target moving to BigQuery."""
    assert profile()["target"] == "dev"


def test_the_bq_target_uses_application_default_credentials_and_a_byte_cap() -> None:
    """Catches the target switched to a key file, a project id written into the repository,
    a query allowed to bill without limit, or another location."""
    bq = profile()["outputs"]["bq"]  # type: ignore[index]
    assert bq["type"] == "bigquery"
    assert bq["method"] == "oauth"
    assert not {"keyfile", "keyfile_json", "token", "refresh_token", "client_secret"} & set(bq)
    assert bq["project"] == "{{ env_var('FO_BQ_PROJECT') }}"
    assert bq["location"] == "US"
    assert bq["maximum_bytes_billed"] == 10_000_000_000


def test_the_bq_target_fails_naming_the_variable_when_it_is_unset(target_path: Path) -> None:
    """Catches a default that would let the bq target run against a placeholder project."""
    result = run_dbt(target_path, "parse", target="bq")
    assert result.returncode != 0
    assert "FO_BQ_PROJECT" in result.stdout + result.stderr


def test_dbt_bigquery_is_only_in_its_own_group_and_not_installed_by_default() -> None:
    """Catches CI, which runs `uv sync --locked`, starting to install Google's client
    libraries."""
    project = tomllib.loads((REPO / "pyproject.toml").read_text())
    groups = project["dependency-groups"]
    assert any(d.startswith("dbt-bigquery") for d in groups["bigquery"])
    for name, deps in groups.items():
        if name != "bigquery":
            assert not any(str(d).startswith(("dbt-bigquery", "google-")) for d in deps), name
    assert not any(
        d.startswith(("dbt-bigquery", "google-")) for d in project["project"]["dependencies"]
    )
    assert "bigquery" not in project["tool"]["uv"]["default-groups"]
    lock = tomllib.loads((REPO / "uv.lock").read_text())
    assert any(p["name"] == "dbt-bigquery" for p in lock["package"]), "not locked"


def test_no_tracked_file_holds_a_service_account_key() -> None:
    """Catches a key file committed: every one has a `private_key` field."""
    tracked = subprocess.run(
        ["git", "ls-files", "-z"], cwd=REPO, capture_output=True, text=True, check=True
    ).stdout.split("\0")
    this_file = Path(__file__).resolve()
    for name in filter(None, tracked):
        path = REPO / name
        if path == this_file or not path.is_file() or path.stat().st_size > 5_000_000:
            continue
        try:
            text = path.read_text()
        except UnicodeDecodeError:
            continue
        assert '"private_key"' not in text, name


# -- the schema suffix of a second BigQuery build (R5.5) ---------------------------------


def schema_name(target_type: str, custom: str | None, variables: dict[str, str]) -> str:
    """generate_schema_name rendered by Jinja alone, with dbt's `target` and `var` stood in."""
    import jinja2

    source = (DBT_ROOT / "macros" / "generate_schema_name.sql").read_text()
    template = jinja2.Environment(autoescape=False).from_string(source)
    module = template.make_module(
        {
            "target": {"type": target_type, "schema": "main"},
            "var": lambda name, default=None: variables.get(name, default),
        }
    )
    return str(module.generate_schema_name(custom, None)).strip()


@pytest.mark.parametrize(
    ("target_type", "custom", "variables", "expected"),
    [
        ("duckdb", "staging", {}, "staging"),
        ("duckdb", None, {}, "main"),
        ("duckdb", "staging", {"fo_schema_suffix": "_b"}, "staging"),
        ("duckdb", None, {"fo_schema_suffix": "_b"}, "main"),
        ("bigquery", "staging", {}, "staging"),
        ("bigquery", None, {}, "main"),
        ("bigquery", "marts", {"fo_schema_suffix": "_b"}, "marts_b"),
        ("bigquery", None, {"fo_schema_suffix": "_b"}, "main_b"),
    ],
)
def test_the_schema_suffix_applies_on_bigquery_only(
    target_type: str, custom: str | None, variables: dict[str, str], expected: str
) -> None:
    """Catches the suffix moving a DuckDB schema, or a second BigQuery build landing on
    top of the first, seeds included."""
    assert schema_name(target_type, custom, variables) == expected


def test_the_suffix_variable_leaves_every_ci_schema_where_it_was(target_path: Path) -> None:
    """Catches the variable reaching DuckDB through dbt itself, not only through the macro."""

    def schemas(*extra: str) -> set[tuple[str, str]]:
        rows = listed(
            run_dbt(
                target_path, "ls", "--output", "json", "--output-keys", "name schema", "-q", *extra
            )
        )
        return {(str(r["name"]), str(r.get("schema"))) for r in rows}

    assert schemas("--vars", "{fo_schema_suffix: _b}") == schemas()


# A contract's `data_type` is sent to the warehouse in the `create table`, so it has to be
# a type both accept, or say which to use by target. dbt does not make project macros
# available in a properties file, so the one type with no shared name is switched on
# `target.type` there (the owner's decision on #130, 2026-10-11).
SHARED_CONTRACT_TYPES = {"bigint", "integer", "boolean", "date", "timestamp", "string"}
FLOAT_CONTRACT_TYPE = "{{ 'float64' if target.type == 'bigquery' else 'double' }}"


def contract_types(models: set[str]) -> list[tuple[str, str, str]]:
    """(model, column, data_type) for every typed column of the named models."""
    import yaml

    found = []
    for path in sorted((DBT_ROOT / "models").rglob("*.yml")):
        for model in (yaml.safe_load(path.read_text()) or {}).get("models") or []:
            if model["name"] not in models:
                continue
            for column in model.get("columns") or []:
                if "data_type" in column:
                    found.append((model["name"], column["name"], str(column["data_type"])))
    return found


def seed_column_types(seeds: set[str]) -> list[tuple[str, str, str]]:
    """(seed, column, type) for every `column_types` entry of the named seeds."""
    import yaml

    found = []
    for path in sorted((DBT_ROOT / "models").rglob("*.yml")):
        for seed in (yaml.safe_load(path.read_text()) or {}).get("seeds") or []:
            if seed["name"] not in seeds:
                continue
            for column, kind in ((seed.get("config") or {}).get("column_types") or {}).items():
                found.append((seed["name"], column, str(kind)))
    return found


def test_the_slices_contracts_name_only_types_both_warehouses_accept() -> None:
    typed = contract_types(SLICE_MODELS)
    assert typed, "no contract found on the slice: the scan is broken"
    refused = [
        row
        for row in typed
        if row[2] not in SHARED_CONTRACT_TYPES and row[2] != FLOAT_CONTRACT_TYPE
    ]
    assert not refused, f"contract types BigQuery or DuckDB would refuse: {refused}"


# A seed is loaded by a load job, whose schema takes fewer names than a `create table`
# does: BigQuery's load API refuses `bigint` ("BIGINT is not a valid value"), which its
# DDL accepts. `int64` is read by both (DuckDB as BIGINT).
SHARED_SEED_TYPES = {"int64", "string", "boolean"}


def test_the_slices_seeds_name_only_types_both_warehouses_load() -> None:
    typed = seed_column_types(SLICE_SEEDS)
    assert typed, "no seed column type found: the scan is broken"
    refused = [
        row for row in typed if row[2] not in SHARED_SEED_TYPES and row[2] != FLOAT_CONTRACT_TYPE
    ]
    assert not refused, f"seed column types BigQuery or DuckDB would refuse: {refused}"
