"""`front-office upload` as the CLI runs it (spec 0140, R6.5, R6.6, R7.1): the options and the
exits. The run itself is `test_upload_run.py`'s.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from front_office import bigquery
from front_office.cli import app
from front_office.landing import LandingZone
from test_upload_run import land, payloads

runner = CliRunner()


@pytest.fixture
def root(tmp_path: Path) -> Path:
    zone = LandingZone(tmp_path / "raw")
    land(zone, payloads())
    return zone.root


def invoke(root: Path, tmp_path: Path, *options: str):  # type: ignore[no-untyped-def]
    return runner.invoke(
        app,
        ["upload", "--raw-root", str(root), "--work-dir", str(tmp_path / "work"), *options],
    )


def test_a_dry_run_without_a_project_runs_the_local_checks_and_says_so(
    root: Path, tmp_path: Path
) -> None:
    """Catches a dry run that needs a project, or one that hides that the remote checks did
    not run (R7.1)."""
    result = invoke(root, tmp_path, "--dry-run")
    assert result.exit_code == 0, result.output
    assert "the remote checks (schemas, stored keys) did not run" in result.output
    assert "dry run: nothing sent" in result.output


def test_no_project_and_no_dry_run_is_refused(root: Path, tmp_path: Path) -> None:
    """Catches a real run that picks a project for itself (R6.5): the message is the run's,
    printed without a traceback."""
    result = invoke(root, tmp_path)
    assert result.exit_code == 1
    assert "--project is required" in result.output
    assert "Traceback" not in result.output


@pytest.mark.parametrize("malformed", ["boxscore", "mlb/", "/boxscore", "mlb/box/score"])
def test_a_malformed_rebuild_exits_1(root: Path, tmp_path: Path, malformed: str) -> None:
    """Catches a rebuild naming no table, or the wrong one by a bad split."""
    result = invoke(root, tmp_path, "--dry-run", "--rebuild", malformed)
    assert result.exit_code == 1
    assert "SOURCE/ENDPOINT" in result.output


@pytest.mark.parametrize("malformed", ["abc", "Has-Capitals-1", "1starts-with-digit", "ends-"])
def test_a_malformed_project_exits_1_before_anything_is_built(
    root: Path, tmp_path: Path, malformed: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Catches a typo reaching the client as a project (R6.5)."""

    def built(*args: object) -> None:
        raise AssertionError("a warehouse was built")

    monkeypatch.setattr(bigquery, "BigQueryWarehouse", built)
    result = invoke(root, tmp_path, "--project", malformed)
    assert result.exit_code == 1
    assert "is not a project id" in result.output


def test_a_project_without_the_bigquery_group_names_the_group(
    root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Catches a traceback where the owner needs to be told to run the command with the
    bigquery group (R7.1)."""

    def missing(*args: object) -> None:
        raise ModuleNotFoundError("google")

    monkeypatch.setattr(bigquery, "BigQueryWarehouse", missing)
    result = invoke(root, tmp_path, "--project", "my-project-123")
    assert result.exit_code == 1
    assert "uv run --group bigquery front-office upload" in result.output
    assert "Traceback" not in result.output
