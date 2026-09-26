"""The CI workflow must be parseable, because a broken one fails silently.

A YAML error here does not produce a red test: GitHub cannot start the workflow at all,
so the run fails in 0 seconds with "this run likely failed because of a workflow file
issue" and no job output. It went unnoticed across three milestones once, caused by an
unquoted colon inside --vars '{anonymize: true}'.

CI cannot check whether CI can start, so this runs locally with the rest of the suite.
"""

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


def test_ci_runs_the_full_gate():
    """The gates this project claims to enforce must actually be in the workflow."""
    workflow = yaml.safe_load((WORKFLOW_DIR / "ci.yml").read_text())
    commands = " ".join(
        step.get("run", "") for job in workflow["jobs"].values() for step in job["steps"]
    )
    for expected in ("ruff check", "ruff format --check", "mypy", "pytest", "dbt build"):
        assert expected in commands, f"CI does not run {expected!r}"
