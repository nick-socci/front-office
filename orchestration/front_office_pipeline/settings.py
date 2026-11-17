"""The settings that choose the landing root and the warehouse (ADR 0131, R3.2, R3.6).

Why one module: the landing root must be one path for the CLI (`--raw-root`), for
`season.is_over` and for dbt (`FO_LANDING_ROOT`), or `load` records captures by one root while
dbt's capture views read the files of another. Every place that needs it asks here. Each
function takes `environ` (default `os.environ`) so a test names its own settings.

Nothing here reads a file or a credential: it reads seven environment variables.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path
from typing import Literal

# orchestration/front_office_pipeline/settings.py -> the repository root.
REPO_ROOT = Path(__file__).resolve().parents[2]
DBT_DIR = REPO_ROOT / "dbt"

Warehouse = Literal["duckdb", "bigquery"]


def _env(environ: Mapping[str, str] | None) -> Mapping[str, str]:
    return os.environ if environ is None else environ


def landing_root(*, environ: Mapping[str, str] | None = None) -> Path:
    """`FO_LANDING_ROOT` (an absolute path), else `data/raw` in the repository (R3.6).

    A relative path is refused: the CLI runs in the repository root and dbt in `dbt/`, so a
    relative root would name two directories.
    """
    named = _env(environ).get("FO_LANDING_ROOT")
    if not named:
        return REPO_ROOT / "data" / "raw"
    path = Path(named)
    if not path.is_absolute():
        raise ValueError(f"FO_LANDING_ROOT must be an absolute path, not {named!r}")
    return path


def warehouse(*, environ: Mapping[str, str] | None = None) -> Warehouse:
    """`FO_WAREHOUSE`: `duckdb` (the default) or `bigquery`; anything else raises."""
    named = _env(environ).get("FO_WAREHOUSE")
    if named is None or named == "":
        return "duckdb"
    if named == "duckdb":
        return "duckdb"
    if named == "bigquery":
        return "bigquery"
    raise ValueError(f"FO_WAREHOUSE must be 'duckdb' or 'bigquery', not {named!r}")


def bq_project(*, environ: Mapping[str, str] | None = None) -> str:
    """`FO_BQ_PROJECT`, which a BigQuery run requires (R3.2). Never defaulted."""
    env = _env(environ)
    if warehouse(environ=env) != "bigquery":
        raise ValueError("FO_BQ_PROJECT is only read when FO_WAREHOUSE is bigquery")
    project = env.get("FO_BQ_PROJECT")
    if not project:
        raise ValueError("FO_WAREHOUSE=bigquery needs FO_BQ_PROJECT (the GCP project id)")
    return project


def duckdb_path(*, environ: Mapping[str, str] | None = None) -> Path:
    """`FO_DUCKDB_PATH`, else `data/warehouse.duckdb` (what `dbt/profiles.yml` names)."""
    named = _env(environ).get("FO_DUCKDB_PATH")
    if not named:
        return REPO_ROOT / "data" / "warehouse.duckdb"
    path = Path(named)
    if not path.is_absolute():
        # `load --db` resolves it in the repository root, dbt's profile in `dbt/`.
        raise ValueError(f"FO_DUCKDB_PATH must be an absolute path, not {named!r}")
    return path


def daily_cron_override(*, environ: Mapping[str, str] | None = None) -> str | None:
    """`FO_DAILY_CRON` for a rehearsal (spec 0218, R1.7); None when unset or empty."""
    return _env(environ).get("FO_DAILY_CRON") or None


def dbt_target(*, environ: Mapping[str, str] | None = None) -> str:
    """The dbt target of the warehouse: `bq` for BigQuery, `dev` for DuckDB (ADR 0131)."""
    return "bq" if warehouse(environ=environ) == "bigquery" else "dev"


def dbt_environment(*, environ: Mapping[str, str] | None = None) -> dict[str, str]:
    """What dbt needs beyond the inherited environment (R3.6).

    `fo_landing_root()` reads `FO_CI_LANDING_ROOT` on the `ci` target and `FO_LANDING_ROOT`
    on the others; both name the one root, so a run on either target reads one landing zone.
    """
    root = str(landing_root(environ=environ))
    return {
        "DBT_PROFILES_DIR": str(DBT_DIR),
        "FO_LANDING_ROOT": root,
        "FO_CI_LANDING_ROOT": root,
        # The profile reads it too; the same absolute file as `load --db` (see duckdb_path).
        "FO_DUCKDB_PATH": str(duckdb_path(environ=environ)),
    }


def check_ready(*, environ: Mapping[str, str] | None = None) -> None:
    """Raise if the settings cannot run a command: called first by every asset (R3.2).

    A BigQuery run without a project fails here, before a fetch lands anything or a build
    is started into no project.
    """
    if warehouse(environ=environ) == "bigquery":
        bq_project(environ=environ)
