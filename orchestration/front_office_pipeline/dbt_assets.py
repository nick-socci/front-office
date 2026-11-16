"""The dbt models and seeds as Dagster assets, from the real manifest (ADR 0128, R1.3, R3.4).

Why a parsed manifest: `@dbt_assets` needs dbt's own description of the project (its
`manifest.json`) to draw one asset per model and seed. This module makes it by running
`dbt parse` for the chosen target when the code location loads, into a temporary directory, so
it is never stale and never written into `dbt/target`. The manifest is the real one,
unfiltered; `dagster-dbt` 0.29.30 reads it where 0.29.28 raised `KeyError`.

Why one translator rule: the capture views and `raw.captures` are dbt *sources*, and the
landed files they read are what the `raw_in_warehouse` asset stands for. Mapping every dbt
source to that one asset key draws the lineage from the landing zone to the staging models
without an asset per endpoint (ADR 0127).

The body runs one `dbt build --exclude-resource-type unit_test` (CI holds the unit tests, and
#221 decides whether BigQuery does, R3.4) and streams its events, so each model and test is
its own materialization or check. A failing node fails its asset and, as dbt does, skips what
depends on it. dbt gets the one landing root in its environment (R3.6).
"""

import functools
import json
import os
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from dagster import AssetExecutionContext, AssetKey, AssetsDefinition
from dagster_dbt import DagsterDbtTranslator, DbtCliResource, dbt_assets

from front_office_pipeline import settings

RAW_IN_WAREHOUSE = AssetKey("raw_in_warehouse")


class SourceToRawInWarehouse(DagsterDbtTranslator):
    """Every dbt source is `raw_in_warehouse`; models and seeds keep dagster-dbt's keys."""

    def get_asset_key(self, dbt_resource_props: Mapping[str, Any]) -> AssetKey:
        if dbt_resource_props.get("resource_type") == "source":
            return RAW_IN_WAREHOUSE
        return super().get_asset_key(dbt_resource_props)


def _dbt_executable() -> str:
    beside_python = Path(sys.executable).parent / "dbt"
    return str(beside_python) if beside_python.exists() else (shutil.which("dbt") or "dbt")


def manifest_target(*, environ: Mapping[str, str] | None = None) -> str:
    """The target the manifest is parsed for: the warehouse's, except with no BigQuery project.

    A BigQuery profile cannot render without `FO_BQ_PROJECT`. The code location must still
    load (the UI, `definitions validate`), so a BigQuery setting without a project parses the
    `dev` target, whose models are the same; the assets then fail before any command runs
    (`settings.check_ready`, R3.2).
    """
    env = os.environ if environ is None else environ
    if settings.warehouse(environ=env) == "bigquery" and not env.get("FO_BQ_PROJECT"):
        return "dev"
    return settings.dbt_target(environ=env)


@functools.cache
def load_manifest(target: str) -> dict[str, Any]:
    """Run `dbt parse --target <target>` into a temporary directory and read its manifest."""
    with tempfile.TemporaryDirectory(prefix="fo-dbt-manifest-") as directory:
        command = [
            _dbt_executable(),
            "parse",
            "--quiet",
            "--project-dir",
            str(settings.DBT_DIR),
            "--profiles-dir",
            str(settings.DBT_DIR),
            "--target",
            target,
            "--target-path",
            directory,
        ]
        completed = subprocess.run(
            command,
            cwd=settings.REPO_ROOT,
            env={**os.environ, **settings.dbt_environment()},
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode != 0:
            tail = "\n".join((completed.stdout + completed.stderr).splitlines()[-20:])
            raise RuntimeError(
                f"`dbt parse --target {target}` exited {completed.returncode}:\n{tail}"
            )
        manifest: dict[str, Any] = json.loads((Path(directory) / "manifest.json").read_text())
        return manifest


def build_args(*, environ: Mapping[str, str] | None = None) -> list[str]:
    """The arguments of the one `dbt build` (R3.2, R3.4)."""
    args = ["build", "--exclude-resource-type", "unit_test"]
    if settings.warehouse(environ=environ) == "bigquery":
        return [*args, "--target", "bq", "--selector", "bigquery"]
    return [*args, "--target", settings.dbt_target(environ=environ)]


@contextmanager
def dbt_environment() -> Iterator[None]:
    """Set the environment dbt needs for the length of one invocation, then restore it.

    `DbtCliResource.cli` passes the current process environment to the dbt subprocess; this
    adds the one landing root (R3.6) without leaving it set for the rest of the process.
    """
    added = settings.dbt_environment()
    before = {name: os.environ.get(name) for name in added}
    os.environ.update(added)
    try:
        yield
    finally:
        for name, value in before.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def build_dbt_assets(manifest: Mapping[str, Any]) -> AssetsDefinition:
    """One asset per model and seed of `manifest`, built by one streamed `dbt build`."""

    @dbt_assets(
        manifest=manifest,
        dagster_dbt_translator=SourceToRawInWarehouse(),
        name="front_office_dbt",
    )
    def front_office_dbt(context: AssetExecutionContext, dbt: DbtCliResource) -> Iterator[Any]:
        settings.check_ready()
        args: Sequence[str] = build_args()
        with dbt_environment():
            yield from dbt.cli(args, context=context).stream()

    return front_office_dbt
