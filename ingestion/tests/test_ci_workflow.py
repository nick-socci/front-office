"""The CI workflow must be parseable, because a broken one fails silently.

A YAML error here does not produce a red test: GitHub cannot start the workflow at all,
so the run fails in 0 seconds with "this run likely failed because of a workflow file
issue" and no job output. It went unnoticed across three milestones once, caused by an
unquoted colon inside --vars '{anonymize: true}'.

CI cannot check whether CI can start, so this runs locally with the rest of the suite.
"""

import re
from pathlib import Path

import pytest
import yaml

WORKFLOW_DIR = Path(__file__).resolve().parents[2] / ".github/workflows"
WORKFLOWS = sorted(WORKFLOW_DIR.glob("*.yml"))


def test_workflows_exist():
    assert WORKFLOWS, f"no workflows found in {WORKFLOW_DIR}"


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: p.name)
def test_workflow_is_valid_yaml(path):
    yaml.safe_load(path.read_text())


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: p.name)
def test_every_job_step_has_a_name_and_an_action(path):
    workflow = yaml.safe_load(path.read_text())
    for job_name, job in workflow["jobs"].items():
        for index, step in enumerate(job["steps"]):
            assert "uses" in step or "run" in step, f"{job_name} step {index} does nothing"


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: p.name)
def test_no_job_runs_on_a_latest_image(path):
    """Catches a workflow whose runner image moves under it when GitHub repoints the label."""
    workflow = yaml.safe_load(path.read_text())
    for job_name, job in workflow["jobs"].items():
        runs_on = job.get("runs-on", [])
        images = [runs_on] if isinstance(runs_on, str) else list(runs_on)
        for image in images:
            if isinstance(image, str):
                assert not image.endswith("-latest"), (
                    f"job {job_name!r} runs on {image!r}; name an exact image"
                )


def _setup_uv_steps(workflow):
    return [
        step
        for job in workflow["jobs"].values()
        for step in job["steps"]
        if str(step.get("uses", "")).startswith("astral-sh/setup-uv@")
    ]


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: p.name)
def test_every_setup_uv_step_names_an_exact_uv_version(path):
    """Catches uv being installed at whatever is latest, so that `uv sync --locked` and
    every `uv run` step change with a uv release."""
    workflow = yaml.safe_load(path.read_text())
    for step in _setup_uv_steps(workflow):
        version = (step.get("with") or {}).get("version")
        assert version is not None and re.fullmatch(r"\d+\.\d+\.\d+", str(version)), (
            f"setup-uv step {step.get('name')!r} has version {version!r}; name an exact x.y.z"
        )


def test_ci_installs_uv_through_setup_uv():
    """Guards the test above against vacuity: if ci.yml stopped using setup-uv, that test
    would pass with nothing to check."""
    workflow = yaml.safe_load((WORKFLOW_DIR / "ci.yml").read_text())
    assert _setup_uv_steps(workflow), "ci.yml has no astral-sh/setup-uv step"


def test_ci_runs_the_full_gate():
    """The gates this project claims to enforce must actually be in the workflow."""
    workflow = yaml.safe_load((WORKFLOW_DIR / "ci.yml").read_text())
    commands = " ".join(
        step.get("run", "") for job in workflow["jobs"].values() for step in job["steps"]
    )
    for expected in ("ruff check", "ruff format --check", "mypy", "pytest", "dbt build"):
        assert expected in commands, f"CI does not run {expected!r}"
