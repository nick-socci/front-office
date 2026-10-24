"""A transaction's date does not depend on the session's time zone (#188, ADR 0097).

DuckDB takes its session TimeZone from the process's `TZ`, and CI runs in UTC. A model
that turns an instant into a wall-clock time in the session's zone is right in UTC and
wrong anywhere else, so the gates' build cannot see it: on the owner's New York machine,
28 of the season's 737 transactions were dated a day early. This runs the unit test
`transactions_are_dated_by_the_eastern_date_of_their_instant` in subprocesses under
zones west and east of UTC. What each case catches:

- America/New_York: the owner's zone; the instant read through the session's clock gives
  the day before for a transaction just after Eastern midnight;
- America/Los_Angeles: the same, with an offset that is not the Eastern one;
- Asia/Tokyo: a zone ahead of UTC, where the same bug gives the day after instead.

The unit test's inputs are all `format: sql`, so dbt needs no built parent and the
warehouse can be an empty file. dbt needs its packages, which CI installs only after
pytest, so the first use installs them if they are missing.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

DBT_ROOT = Path(__file__).resolve().parents[2] / "dbt"
DBT = Path(sys.executable).parent / "dbt"
UNIT_TEST = "transactions_are_dated_by_the_eastern_date_of_their_instant"


@pytest.fixture(scope="module")
def dbt_ready() -> None:
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


@pytest.mark.parametrize("zone", ["America/New_York", "America/Los_Angeles", "Asia/Tokyo"])
def test_transaction_dates_are_the_same_in_any_session_time_zone(
    dbt_ready: None, tmp_path: Path, zone: str
) -> None:
    env = {k: v for k, v in os.environ.items() if k != "FO_BQ_PROJECT"}
    env["TZ"] = zone
    env["DBT_PROFILES_DIR"] = str(DBT_ROOT)
    env["FO_CI_DUCKDB_PATH"] = str(tmp_path / "empty.duckdb")
    result = subprocess.run(
        [
            str(DBT),
            "test",
            "--target",
            "ci",
            "--target-path",
            str(tmp_path / "target"),
            "--select",
            UNIT_TEST,
        ],
        cwd=DBT_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    # A selector that matched nothing would also exit 0.
    assert "PASS=1 " in result.stdout, result.stdout
