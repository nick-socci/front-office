"""int_fantasy__optimal_lineups: the builds that must fail, and the table it builds (spec 0137).

The model's behaviours that give rows are dbt unit tests (`optimal_lineups_*` in
_intermediate__models.yml). A unit test cannot expect an error, so the failures are run here:
each case writes a small DuckDB holding the model's four parents in the `intermediate`
schema, where dbt's `ci` target resolves them, runs `dbt run --select
int_fantasy__optimal_lineups` against it in a subprocess, and reads dbt's output. Four
invocations in all. dbt needs its packages, which CI installs only after pytest, so the first
use installs them if they are missing.

What each case catches:

- the success case: a renamed, reordered or retyped output column (R2.1), and a model that is
  not built as a table;
- a null option beside an out-of-bound one: the unvalued skip running before the bound check
  (R3.7), so a value of 1001 passes;
- an out-of-bound value: the message not naming the team-day (R2.3);
- a date in no matchup period: the rows being dropped or solved alone silently, or the
  message not naming the team-day (R2.4).
"""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import date
from pathlib import Path

import duckdb
import pytest

DBT_ROOT = Path(__file__).resolve().parents[2] / "dbt"
DBT = Path(sys.executable).parent / "dbt"
MODEL = "int_fantasy__optimal_lineups"
DAY1, DAY2 = date(2026, 6, 1), date(2026, 6, 2)
COLUMNS = [
    ("platform", "VARCHAR"),
    ("league_id", "VARCHAR"),
    ("season", "BIGINT"),
    ("scoring_date", "DATE"),
    ("fantasy_team_id", "BIGINT"),
    ("platform_player_id", "BIGINT"),
    ("lineup_slot_id", "BIGINT"),
]


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


def option(day, team, player, value, *, slot_id=1, actual=False):
    return ("espn", "1", 2026, day, team, player, slot_id, "hitter", value, actual, "batting")


def build_parents(path: Path, options: list[tuple], periods: list[tuple[int, date]]) -> None:
    """The four parents, in the schema and with the column types the real models give."""
    conn = duckdb.connect(str(path))
    conn.execute("create schema intermediate")
    conn.execute(
        "create table intermediate.int_fantasy__lineup_options (platform varchar, "
        "league_id varchar, season bigint, scoring_date date, fantasy_team_id bigint, "
        "platform_player_id bigint, lineup_slot_id bigint, slot_role varchar, "
        "option_value double, is_actual boolean, day_kind varchar)"
    )
    conn.execute(
        "create table intermediate.int_fantasy__lineup_slots (platform varchar, "
        "league_id varchar, season bigint, lineup_slot_id bigint, slot_role varchar, "
        "slot_count bigint)"
    )
    conn.execute(
        "create table intermediate.int_fantasy__matchup_periods (platform varchar, "
        "league_id varchar, season bigint, matchup_period bigint, scoring_date date)"
    )
    conn.execute(
        "create table intermediate.int_fantasy__start_limits (platform varchar, "
        "league_id varchar, season bigint, matchup_period bigint, start_limit double)"
    )
    conn.executemany(
        "insert into intermediate.int_fantasy__lineup_options values (?,?,?,?,?,?,?,?,?,?,?)",
        options,
    )
    conn.execute(
        "insert into intermediate.int_fantasy__lineup_slots "
        "values ('espn', '1', 2026, 1, 'hitter', 1)"
    )
    conn.executemany(
        "insert into intermediate.int_fantasy__matchup_periods values ('espn', '1', 2026, ?, ?)",
        periods,
    )
    conn.close()


def run_model(tmp_path: Path) -> subprocess.CompletedProcess[str]:
    env = {k: v for k, v in os.environ.items() if k != "FO_BQ_PROJECT"}
    env["DBT_PROFILES_DIR"] = str(DBT_ROOT)
    env["FO_CI_DUCKDB_PATH"] = str(tmp_path / "parents.duckdb")
    return subprocess.run(
        [
            str(DBT),
            "run",
            "--target",
            "ci",
            "--target-path",
            str(tmp_path / "target"),
            "--select",
            MODEL,
        ],
        cwd=DBT_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_the_model_builds_a_table_with_the_seven_columns_and_their_types(
    dbt_ready: None, tmp_path: Path
) -> None:
    """Catches a renamed, reordered or retyped column (R2.1), and a model not built as a table
    (a view calling the plugin's function would fail outside dbt, spec 0137 C16)."""
    options = [option(DAY1, 1, 1, 1.0, actual=True), option(DAY1, 1, 2, 3.0)]
    build_parents(tmp_path / "parents.duckdb", options, [(1, DAY1)])
    result = run_model(tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    conn = duckdb.connect(str(tmp_path / "parents.duckdb"), read_only=True)
    described = conn.execute(f"describe intermediate.{MODEL}").fetchall()
    assert [(name, kind) for name, kind, *_ in described] == COLUMNS
    kind = conn.execute(
        "select table_type from information_schema.tables where table_name = ?", [MODEL]
    ).fetchone()
    assert kind == ("BASE TABLE",)
    assert conn.execute(f"select * from intermediate.{MODEL}").fetchall() == [
        ("espn", "1", 2026, DAY1, 1, 2, 1)
    ]
    conn.close()


@pytest.mark.parametrize(
    ("options", "periods", "message"),
    [
        pytest.param(
            [option(DAY1, 1, 1, None), option(DAY1, 1, 2, 1001.0)],
            [(1, DAY1)],
            "optimal lineup failed for team-day platform=espn, league_id=1, season=2026, "
            "fantasy_team_id=1, scoring_date=2026-06-01: option value out of bound",
            id="a null option does not hide an out-of-bound one",
        ),
        pytest.param(
            [option(DAY2, 3, 2, -1001.0)],
            [(1, DAY2)],
            "optimal lineup failed for team-day platform=espn, league_id=1, season=2026, "
            "fantasy_team_id=3, scoring_date=2026-06-02: option value out of bound",
            id="an out-of-bound value names the team-day",
        ),
        pytest.param(
            [option(DAY2, 7, 1, 1.0)],
            [(1, DAY1)],
            "optimal lineup failed for team-day platform=espn, league_id=1, season=2026, "
            "fantasy_team_id=7, scoring_date=2026-06-02: its date is in no matchup period",
            id="a date in no matchup period names the team-day",
        ),
    ],
)
def test_the_build_fails_naming_the_team_day(
    dbt_ready: None,
    tmp_path: Path,
    options: list[tuple],
    periods: list[tuple[int, date]],
    message: str,
) -> None:
    """Catches a failure that does not name the team-day, or no failure: a value beyond the
    solver's bound (R2.3, R3.7) or a date in no matchup period (R2.4) must stop the build."""
    build_parents(tmp_path / "parents.duckdb", options, periods)
    result = run_model(tmp_path)
    assert result.returncode != 0, result.stdout
    assert message in result.stdout + result.stderr, result.stdout + result.stderr
