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
depends on it. When dbt exits non-zero the step raises a `Failure` with fixed text and, as its
`failed_nodes` metadata, the unique id and status of each node that ended `error` or `fail` in
that invocation's `run_results.json`, never dbt's own message (R3.4). dbt gets the one landing
root in its environment (R3.6).
"""

import functools
import importlib.util
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

from dagster import AssetExecutionContext, AssetKey, AssetsDefinition, Failure, MetadataValue
from dagster_dbt import (
    DagsterDbtCliRuntimeError,
    DagsterDbtTranslator,
    DagsterDbtTranslatorSettings,
    DbtCliInvocation,
    DbtCliResource,
    dbt_assets,
)

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


def require_adapter(target: str) -> None:
    """Stop with the group to install if the target's dbt adapter is missing.

    `dbt-bigquery` is in the `bigquery` group, not `orchestration`, so a host that runs
    `FO_WAREHOUSE=bigquery` installs both (`uv sync --locked --group orchestration --group
    bigquery`); without it dbt's own error names a missing adapter only after a parse.
    """
    if target == "bq" and importlib.util.find_spec("dbt.adapters.bigquery") is None:
        raise RuntimeError(
            "FO_WAREHOUSE=bigquery needs the dbt-bigquery adapter: install it with "
            "`uv sync --locked --group orchestration --group bigquery` (--group bigquery)"
        )


@functools.cache
def load_manifest(target: str) -> dict[str, Any]:
    """Run `dbt parse --target <target>` into a temporary directory and read its manifest."""
    require_adapter(target)
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


def without_function_parents(manifest: Mapping[str, Any]) -> dict[str, Any]:
    """A copy of `manifest` whose tests no longer name a dbt function as a parent.

    Why: `dagster-dbt` 0.29.30 looks every parent of a singular test up in `nodes` or
    `sources`; a function is in neither, the lookup gives `None`, and the step dies with
    `'NoneType' object has no attribute 'get'` mid-build. On the BigQuery target two lineup
    tests read `sum_in_order`, so the real build stopped at node 539 of 579 (task 7). The copy is
    only Dagster's description of the project: dbt reads its own project, and every test still
    runs. Only the edges of tests that name a function are rewritten.
    """
    nodes = dict(manifest["nodes"])
    parent_map = dict(manifest.get("parent_map", {}))
    for unique_id, node in manifest["nodes"].items():
        if node["resource_type"] != "test":
            continue
        parents = node["depends_on"].get("nodes", [])
        if not any(parent.startswith("function.") for parent in parents):
            continue
        kept = [parent for parent in parents if not parent.startswith("function.")]
        nodes[unique_id] = {**node, "depends_on": {**node["depends_on"], "nodes": kept}}
        if unique_id in parent_map:
            parent_map[unique_id] = [
                p for p in parent_map[unique_id] if not p.startswith("function.")
            ]
    return {**manifest, "nodes": nodes, "parent_map": parent_map}


def failed_nodes(run_results: Mapping[str, Any]) -> str:
    """One `<unique_id>: <status>` line per node that ended `error` or `fail`, in file order.

    Only the id and the status: a node's `message` can carry SQL or data, and the report goes to
    an outside service.
    """
    return "\n".join(
        f"{result['unique_id']}: {result['status']}"
        for result in run_results.get("results", [])
        if result.get("status") in ("error", "fail")
    )


def stream_build(invocation: DbtCliInvocation) -> Iterator[Any]:
    """Stream the invocation's events; if dbt exits non-zero, raise a `Failure` naming the nodes.

    The failure's description is fixed text and its metadata the failed nodes (R3.4); dagster-dbt's
    own error carries dbt's output, which is not for the report. A missing `run_results.json`
    (dbt died before writing it) leaves the list empty.
    """
    try:
        yield from invocation.stream()
    except DagsterDbtCliRuntimeError as error:
        try:
            run_results: Mapping[str, Any] = invocation.get_artifact("run_results.json")
        except Exception:  # noqa: BLE001 - any trouble reading it means no list, not a new error
            run_results = {}
        raise Failure(
            description="dbt build failed",
            metadata={"failed_nodes": MetadataValue.text(failed_nodes(run_results))},
        ) from error


def build_dbt_assets(manifest: Mapping[str, Any]) -> AssetsDefinition:
    """One asset per model and seed of `manifest`, built by one streamed `dbt build`."""
    manifest = without_function_parents(manifest)

    @dbt_assets(
        manifest=manifest,
        dagster_dbt_translator=SourceToRawInWarehouse(
            # Many sources, one key: on BigQuery the models read the `raw.*` sources, and
            # dagster-dbt refuses two dbt resources with one asset key unless told this.
            settings=DagsterDbtTranslatorSettings(enable_duplicate_source_asset_keys=True)
        ),
        name="front_office_dbt",
    )
    def front_office_dbt(context: AssetExecutionContext, dbt: DbtCliResource) -> Iterator[Any]:
        settings.check_ready()
        args: Sequence[str] = build_args()
        with dbt_environment():
            yield from stream_build(dbt.cli(args, context=context))

    return front_office_dbt
