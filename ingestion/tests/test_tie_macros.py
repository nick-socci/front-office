"""A tie where a ranking cuts stops the build (#141, ADRs 0107 and 0108).

The CI fixtures hold no tie at any cut, so a build over them cannot show that
`fo_keep_first`, `fo_row_number` and `fo_latest_by_entity` raise when they should. This
runs dbt over literal rows (`select * from (values ...)`) on the `ci` target, against an
empty DuckDB file, and asserts the exact rows returned or the error text. dbt runs
in-process, parsing the project once for the module, so each case costs well under a
second. dbt needs its packages, which CI installs only after pytest, so the first use
installs them if they are missing. What each case catches:

- keep_first, one row, a tie at place 1: a check that misses a tie at the cut;
- keep_first, one row, ties only at places 2 and 3: a check that raises on any tie in a
  partition, not only one across the cut;
- keep_first, two rows, a tie between places 2 and 3: the cut placed at the wrong place;
- keep_first, two rows, places 1 and 2 tied: a tie wholly inside the kept rows, which
  changes nothing and must not raise;
- no partition: a window that drops the partition clause, or a message that names no keys;
- `rows` as a column constant within each partition: a cut that ignores the expression,
  or an expression that loses its parentheses;
- `rows` as a column that differs within a partition (R1.1a): a partition with no single
  cut, where a tie could pass unseen;
- a null partition key: a key that reads as nothing in the message, or a null partition
  that is not checked like any other;
- the message: the node, the place and the key values, so a failed build says where;
- fo_row_number: numbers 1 to n on a total order, and raises on a tie at any place, the
  last two included, which keep_first never looks at;
- fo_latest_by_entity: keeps the rows keep_first keeps with one row, and raises where it
  does.
"""

from __future__ import annotations

import copy
import os
import subprocess
import sys
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from dbt.cli.main import dbtRunner

DBT_ROOT = Path(__file__).resolve().parents[2] / "dbt"
DBT = Path(sys.executable).parent / "dbt"
# What `this.identifier` is under `dbt show --inline`.
NODE = "inline_query"

Run = Callable[[str], list[tuple[Any, ...]]]


class Raised(Exception):
    """dbt failed the statement; the text is dbt's error."""


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


@pytest.fixture(scope="module")
def run(dbt_ready: None, tmp_path_factory: pytest.TempPathFactory) -> Iterator[Run]:
    tmp = tmp_path_factory.mktemp("tie_macros")
    saved = {
        k: os.environ.get(k) for k in ("DBT_PROFILES_DIR", "FO_CI_DUCKDB_PATH", "FO_BQ_PROJECT")
    }
    os.environ["DBT_PROFILES_DIR"] = str(DBT_ROOT)
    os.environ["FO_CI_DUCKDB_PATH"] = str(tmp / "empty.duckdb")
    os.environ.pop("FO_BQ_PROJECT", None)
    common = [
        "--project-dir",
        str(DBT_ROOT),
        "--target",
        "ci",
        "--target-path",
        str(tmp / "target"),
        "--log-path",
        str(tmp / "logs"),
        "--quiet",
    ]
    parsed = dbtRunner().invoke(["parse", *common])
    assert parsed.success, parsed.exception

    def run_sql(sql: str) -> list[tuple[Any, ...]]:
        result = dbtRunner(manifest=copy.deepcopy(parsed.result)).invoke(
            ["show", "--inline", sql, "--limit", "-1", *common]
        )
        if not result.success:
            raise Raised(str(result.exception))
        assert result.result is not None
        table = result.result.results[0].agate_table  # type: ignore[union-attr]
        return [tuple(row.values()) for row in table.rows]

    try:
        yield run_sql
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _keep(rows: str, partition: str, order: str, count: str = "1") -> str:
    return (
        f"select * from (values {rows}) as t(g, o, v, quota) "
        f"{{{{ fo_keep_first({partition}, '{order}', {count}) }}}}"
    )


def _kept(run: Run, rows: str, partition: str = "['g']", count: str = "1") -> list[Any]:
    return sorted(r[2] for r in run(_keep(rows, partition, "o", count)))


def _error(run: Run, sql: str) -> str:
    with pytest.raises(Raised) as caught:
        run(sql)
    return str(caught.value)


TIE_AT_1 = "(1, 1, 'a', 1), (1, 1, 'b', 1), (1, 2, 'c', 1)"
TIE_AT_2_AND_3 = (
    "(1, 1, 'a', 1), (1, 2, 'b', 1), (1, 2, 'c', 1), (2, 1, 'd', 1), (2, 2, 'e', 1), (2, 2, 'f', 1)"
)


def test_keep_one_raises_on_a_tie_at_place_one(run: Run) -> None:
    message = _error(run, _keep(TIE_AT_1, "['g']", "o"))
    assert f"{NODE}: rows tie for place 1 in (1)" in message


def test_keep_one_ignores_a_tie_below_the_cut(run: Run) -> None:
    rows = run(_keep(TIE_AT_2_AND_3, "['g']", "o"))
    assert sorted((r[0], r[2]) for r in rows) == [(1, "a"), (2, "d")]


def test_keep_two_raises_on_a_tie_between_places_two_and_three(run: Run) -> None:
    rows = "(1, 1, 'a', 2), (1, 2, 'b', 2), (1, 2, 'c', 2)"
    message = _error(run, _keep(rows, "['g']", "o", "2"))
    assert f"{NODE}: rows tie for place 2 in (1)" in message


def test_keep_two_ignores_a_tie_inside_the_kept_rows(run: Run) -> None:
    assert _kept(run, TIE_AT_1, count="2") == ["a", "b"]


def test_keep_without_a_partition_raises_naming_the_whole_input(run: Run) -> None:
    message = _error(run, _keep("(1, 1, 'a', 1), (2, 1, 'b', 1)", "[]", "o"))
    assert f"{NODE}: rows tie for place 1 in (whole input)" in message


def test_keep_without_a_partition_keeps_the_first_rows_of_the_whole_input(run: Run) -> None:
    assert _kept(run, "(1, 2, 'a', 1), (2, 1, 'b', 1), (2, 3, 'c', 1)", "[]", "2") == ["a", "b"]


def test_keep_takes_rows_from_a_column_constant_within_each_partition(run: Run) -> None:
    rows = (
        "(1, 1, 'a', 2), (1, 1, 'b', 2), (1, 2, 'c', 2), "
        "(2, 1, 'd', 1), (2, 2, 'e', 1), (2, 2, 'f', 1)"
    )
    assert _kept(run, rows, count="'quota'") == ["a", "b", "d"]


def test_keep_with_a_column_for_rows_raises_on_a_tie_at_that_cut(run: Run) -> None:
    rows = "(1, 1, 'a', 2), (1, 2, 'b', 2), (1, 2, 'c', 2), (2, 1, 'd', 1), (2, 2, 'e', 1)"
    message = _error(run, _keep(rows, "['g']", "o", "'quota'"))
    assert f"{NODE}: rows tie for place 2 in (1)" in message


def test_keep_raises_when_rows_differs_within_a_partition_even_without_a_tie(run: Run) -> None:
    rows = "(1, 1, 'a', 1), (1, 2, 'b', 2), (1, 3, 'c', 2)"
    message = _error(run, _keep(rows, "['g']", "o", "'quota'"))
    assert f"{NODE}: the number of rows to keep differs in (1)" in message


def test_keep_raises_on_a_tie_in_a_partition_whose_key_is_null(run: Run) -> None:
    rows = "(null, 1, 'a', 1), (null, 1, 'b', 1), (1, 1, 'c', 1)"
    message = _error(run, _keep(rows, "['g']", "o"))
    assert f"{NODE}: rows tie for place 1 in (null)" in message


def test_keep_names_every_partition_key_in_order(run: Run) -> None:
    # Both rows are in the partition (1, false) and tie there.
    sql = (
        "select * from (values (1, 1, 'a', 1), (1, 1, 'b', 1)) as t(g, o, v, quota) "
        "{{ fo_keep_first(['g', 'v is null'], 'o') }}"
    )
    assert f"{NODE}: rows tie for place 1 in (1, false)" in _error(run, sql)


def test_keep_keeps_a_null_partition_without_a_tie(run: Run) -> None:
    rows = "(null, 1, 'a', 1), (null, 2, 'b', 1), (1, 1, 'c', 1)"
    assert _kept(run, rows) == ["a", "c"]


def test_row_number_numbers_a_total_order_from_one_in_each_partition(run: Run) -> None:
    rows = "(1, 3, 'c', 1), (1, 1, 'a', 1), (1, 2, 'b', 1), (2, 5, 'd', 1), (2, 4, 'e', 1)"
    sql = (
        "select v, {{ fo_row_number(['g'], 'o') }} as n "
        f"from (values {rows}) as t(g, o, v, quota)"
    )
    assert sorted(run(sql)) == [("a", 1), ("b", 2), ("c", 3), ("d", 2), ("e", 1)]


@pytest.mark.parametrize(
    ("rows", "place"),
    [
        ("(1, 1, 'a', 1), (1, 1, 'b', 1), (1, 2, 'c', 1), (1, 3, 'd', 1)", 1),
        ("(1, 1, 'a', 1), (1, 2, 'b', 1), (1, 2, 'c', 1), (1, 3, 'd', 1)", 2),
        ("(1, 1, 'a', 1), (1, 2, 'b', 1), (1, 3, 'c', 1), (1, 3, 'd', 1)", 3),
    ],
    ids=["first", "middle", "last-two"],
)
def test_row_number_raises_on_a_tie_at_any_place(run: Run, rows: str, place: int) -> None:
    sql = (
        f"select {{{{ fo_row_number(['g'], 'o') }}}} as n from (values {rows}) as t(g, o, v, quota)"
    )
    assert f"{NODE}: rows tie for place {place} in (1)" in _error(run, sql)


def test_latest_by_entity_keeps_what_keep_first_keeps_without_a_tie(run: Run) -> None:
    from_values = f"select * from (values {TIE_AT_2_AND_3}) as t(g, o, v, quota) "
    latest = run(from_values + "{{ fo_latest_by_entity(['g'], 'o') }}")
    first = run(from_values + "{{ fo_keep_first(['g'], 'o', 1) }}")
    assert sorted(latest) == sorted(first) == sorted([(1, 1, "a", 1), (2, 1, "d", 1)])


def test_latest_by_entity_raises_on_a_tie(run: Run) -> None:
    sql = (
        f"select * from (values {TIE_AT_1}) as t(g, o, v, quota) "
        "{{ fo_latest_by_entity(['g'], 'o') }}"
    )
    assert f"{NODE}: rows tie for place 1 in (1)" in _error(run, sql)
