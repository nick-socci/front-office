"""R3.2 and R3.6: the settings that choose the landing root and the warehouse.

Catches: a relative landing root that would mean two different directories to the CLI and to
dbt; a typo in FO_WAREHOUSE that silently runs the DuckDB path; a BigQuery run without a
project that would get as far as a command.
"""

from pathlib import Path

import pytest

from front_office_pipeline import settings


def test_landing_root_defaults_to_data_raw_in_the_repository() -> None:
    root = settings.landing_root(environ={})
    assert root == settings.REPO_ROOT / "data" / "raw"
    assert root.is_absolute()


def test_landing_root_is_the_named_absolute_path(tmp_path: Path) -> None:
    assert settings.landing_root(environ={"FO_LANDING_ROOT": str(tmp_path)}) == tmp_path


def test_a_relative_landing_root_is_refused() -> None:
    with pytest.raises(ValueError, match="absolute"):
        settings.landing_root(environ={"FO_LANDING_ROOT": "data/raw"})


def test_warehouse_defaults_to_duckdb_and_accepts_bigquery() -> None:
    assert settings.warehouse(environ={}) == "duckdb"
    assert settings.warehouse(environ={"FO_WAREHOUSE": "duckdb"}) == "duckdb"
    assert settings.warehouse(environ={"FO_WAREHOUSE": "bigquery"}) == "bigquery"


@pytest.mark.parametrize("value", ["BigQuery", "postgres", "bq", " "])
def test_any_other_warehouse_raises(value: str) -> None:
    with pytest.raises(ValueError, match="FO_WAREHOUSE"):
        settings.warehouse(environ={"FO_WAREHOUSE": value})


def test_bq_project_is_required_for_bigquery_only() -> None:
    assert settings.bq_project(environ={"FO_WAREHOUSE": "bigquery", "FO_BQ_PROJECT": "p"}) == "p"
    with pytest.raises(ValueError, match="FO_BQ_PROJECT"):
        settings.bq_project(environ={"FO_WAREHOUSE": "bigquery"})
    with pytest.raises(ValueError, match="FO_BQ_PROJECT"):
        settings.bq_project(environ={"FO_WAREHOUSE": "bigquery", "FO_BQ_PROJECT": ""})
    # DuckDB has no project: asking is a mistake, not an empty answer.
    with pytest.raises(ValueError, match="bigquery"):
        settings.bq_project(environ={})


def test_duckdb_path_defaults_and_is_overridden() -> None:
    assert settings.duckdb_path(environ={}) == settings.REPO_ROOT / "data" / "warehouse.duckdb"
    assert settings.duckdb_path(environ={"FO_DUCKDB_PATH": "/x/w.duckdb"}) == Path("/x/w.duckdb")


def test_dbt_target_follows_the_warehouse() -> None:
    assert settings.dbt_target(environ={}) == "dev"
    assert settings.dbt_target(environ={"FO_WAREHOUSE": "bigquery"}) == "bq"


def test_dbt_environment_names_the_one_landing_root_for_both_targets(tmp_path: Path) -> None:
    env = settings.dbt_environment(environ={"FO_LANDING_ROOT": str(tmp_path)})
    assert env["FO_LANDING_ROOT"] == str(tmp_path)
    assert env["FO_CI_LANDING_ROOT"] == str(tmp_path)
    assert env["DBT_PROFILES_DIR"] == str(settings.REPO_ROOT / "dbt")


def test_check_ready_fails_for_bigquery_without_a_project() -> None:
    settings.check_ready(environ={})
    with pytest.raises(ValueError, match="FO_BQ_PROJECT"):
        settings.check_ready(environ={"FO_WAREHOUSE": "bigquery"})


def test_a_relative_duckdb_path_is_refused() -> None:
    """The CLI runs in the repository root and dbt in `dbt/`: a relative path is two files."""
    with pytest.raises(ValueError, match="FO_DUCKDB_PATH"):
        settings.duckdb_path(environ={"FO_DUCKDB_PATH": "w.duckdb"})


def test_dbt_gets_the_same_duckdb_file_as_load() -> None:
    env = settings.dbt_environment(environ={"FO_DUCKDB_PATH": "/x/w.duckdb"})
    assert env["FO_DUCKDB_PATH"] == "/x/w.duckdb"


def test_dashboard_extract_defaults_and_is_overridden() -> None:
    """R2.1. Catches a default outside the repository's `data/`, or a named path ignored."""
    default = settings.dashboard_extract(environ={})
    assert default == settings.REPO_ROOT / "data" / "dashboard" / "extract.duckdb"
    named = {"FO_DASHBOARD_EXTRACT": "/dashboard/extract.duckdb"}
    assert settings.dashboard_extract(environ=named) == Path("/dashboard/extract.duckdb")


def test_a_relative_dashboard_extract_is_refused() -> None:
    """The CLI runs in the repository root: a relative path would depend on where it ran."""
    with pytest.raises(ValueError, match="FO_DASHBOARD_EXTRACT"):
        settings.dashboard_extract(environ={"FO_DASHBOARD_EXTRACT": "extract.duckdb"})
