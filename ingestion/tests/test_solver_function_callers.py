"""Only int_fantasy__optimal_lineups calls the lineup solver function, and it is a table (R6.4).

The DuckDB function is registered by a dbt-duckdb plugin on dbt's own connections (ADR 0103),
so it does not exist in the warehouse file. A view that called it, or any model other than
the one this was designed for, would work in a dbt build and fail for anyone reading the
warehouse outside dbt, or on a connection the plugin did not configure.
"""

from __future__ import annotations

import re
from pathlib import Path

DBT = Path(__file__).resolve().parents[2] / "dbt"
MODEL = DBT / "models/intermediate/fantasy/int_fantasy__optimal_lineups.sql"
# The macros that name the function, and the function's own file, are where it is defined.
DEFINERS = {DBT / "macros/portable.sql", DBT / "functions/solve_lineup_period.py"}
CALL = re.compile(
    r"fo_solve_lineup_period|\bsolve_lineup_period\s*\(|function\(\s*['\"]solve_lineup_period",
)


def callers() -> set[Path]:
    found = set()
    for folder in ("models", "tests", "macros", "functions"):
        for path in (DBT / folder).rglob("*"):
            if path.suffix not in {".sql", ".py"} or path in DEFINERS:
                continue
            if CALL.search(path.read_text()):
                found.add(path)
    return found


def test_only_the_optimal_lineups_model_calls_the_solver_function() -> None:
    """Catches a second model, a singular test or a macro calling the function: it exists
    only on dbt's connections, and the one model that calls it is held to be a table."""
    assert callers() == {MODEL}


def test_the_calling_model_is_a_table() -> None:
    """Catches the model being made a view, which would fail on any connection that the
    plugin did not configure, such as the warehouse file opened from a notebook."""
    text = MODEL.read_text()
    assert re.search(r"config\(\s*materialized\s*=\s*['\"]table['\"]", text)


def test_the_search_finds_what_it_looks_for() -> None:
    """Catches a pattern that matches nothing, which would make the first test pass for
    every project: each spelling of a call is found."""
    for sql in (
        "{{ fo_solve_lineup_period() }}(a)",
        "select solve_lineup_period (a)",
        "{{ function('solve_lineup_period') }}",
        'select {{ function("solve_lineup_period") }}',
    ):
        assert CALL.search(sql), sql
    assert not CALL.search("select 1 as solve_lineup_period_count")
