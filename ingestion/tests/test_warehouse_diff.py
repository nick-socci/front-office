"""Tests for the warehouse comparison shared by compare_warehouses and the isolation check.

A comparison that passes on anything is worse than none, so each test below is a way a
lazy comparison would be wrong.
"""

from pathlib import Path

import duckdb
import pytest

from warehouse_diff import (
    attach,
    compare_relation,
    list_relations,
    rows_missing_from,
)


def build(path: Path, statements: list[str]) -> None:
    with duckdb.connect(str(path)) as con:
        con.execute("create schema if not exists marts")
        for statement in statements:
            con.execute(statement)


@pytest.fixture
def pair(tmp_path):
    """Return a function that builds two warehouses and a connection with both attached."""

    def make(left: list[str], right: list[str]):
        build(tmp_path / "left_wh.duckdb", left)
        build(tmp_path / "right_wh.duckdb", right)
        con = duckdb.connect()
        return (
            con,
            attach(con, tmp_path / "left_wh.duckdb"),
            attach(con, tmp_path / "right_wh.duckdb"),
        )

    return make


def rel(rows: str, cols: str = "k varchar, v integer") -> list[str]:
    return [f"create table marts.t ({cols})", f"insert into marts.t values {rows}"]


def test_attach_uses_the_file_stem_as_the_catalog(pair):
    """Catches an attach under another name: views store their catalog and then fail."""
    _, left, right = pair(rel("('a', 1)"), rel("('a', 1)"))
    assert (left, right) == ("left_wh", "right_wh")


def test_identical_relations_do_not_differ(pair):
    """Catches a comparison that reports noise on equal data."""
    con, left, right = pair(rel("('a', 1), ('b', 2)"), rel("('b', 2), ('a', 1)"))
    diff = compare_relation(con, left, right, "marts.t")
    assert not diff.differs and diff.left_rows == diff.right_rows == 2


def test_changed_value_is_reported(pair):
    """Catches a comparison on keys or counts only: same rows, one value changed."""
    con, left, right = pair(rel("('a', 1), ('b', 2)"), rel("('a', 1), ('b', 3)"))
    diff = compare_relation(con, left, right, "marts.t")
    assert diff.differs and (diff.only_left, diff.only_right) == (1, 1)


def test_missing_row_is_reported(pair):
    """Catches a comparison that ignores rows one side lacks."""
    con, left, right = pair(rel("('a', 1), ('b', 2)"), rel("('a', 1)"))
    diff = compare_relation(con, left, right, "marts.t")
    assert diff.differs and (diff.only_left, diff.only_right) == (1, 0)
    assert (diff.left_rows, diff.right_rows) == (2, 1)


def test_equal_count_but_different_duplicates_is_reported(pair):
    """Catches plain EXCEPT: A,A,B,C against A,B,B,C has equal counts and equal sets."""
    con, left, right = pair(
        rel("('A', 1), ('A', 1), ('B', 1), ('C', 1)"),
        rel("('A', 1), ('B', 1), ('B', 1), ('C', 1)"),
    )
    diff = compare_relation(con, left, right, "marts.t")
    assert diff.left_rows == diff.right_rows == 4
    assert diff.differs and (diff.only_left, diff.only_right) == (1, 1)


def test_added_column_is_a_column_difference_not_a_row_difference(pair):
    """Catches a column added on one side failing every row, or going unreported."""
    con, left, right = pair(
        rel("('a', 1)"),
        rel("('a', 1, 'x')", "k varchar, v integer, extra varchar"),
    )
    diff = compare_relation(con, left, right, "marts.t")
    assert not diff.differs
    assert diff.right_only_columns == ["extra"] and diff.left_only_columns == []


def test_relation_missing_from_one_side_is_reported(pair):
    """Catches name sets that are not compared: a view or table present on one side only."""
    con, left, right = pair(
        rel("('a', 1)"), rel("('a', 1)") + ["create view marts.v as select 1 x"]
    )
    assert list_relations(con, left) == {"marts.t"}
    assert list_relations(con, right) == {"marts.t", "marts.v"}


def test_relations_list_ignores_other_schemas(pair):
    """Catches raw tables or dbt internals being compared as models."""
    con, left, _ = pair(rel("('a', 1)") + ["create schema raw", "create table raw.x (a int)"], [])
    assert list_relations(con, left) == {"marts.t"}


def test_where_compares_only_that_slice(pair):
    """Catches a league-season filter that is ignored: other slices differ but this one not."""
    cols = "league_id varchar, season integer, v integer"
    con, left, right = pair(
        rel("('1', 2026, 1), ('2', 2026, 5)", cols),
        rel("('1', 2026, 1), ('2', 2026, 9)", cols),
    )
    whole = compare_relation(con, left, right, "marts.t")
    assert whole.differs
    sliced = compare_relation(
        con,
        left,
        right,
        "marts.t",
        left_where="league_id = '1' and season = 2026",
        right_where="league_id = '1' and season = 2026",
    )
    assert not sliced.differs and sliced.left_rows == 1


def test_one_way_reports_rows_the_left_has_and_the_right_lacks(pair):
    """Catches a superset check that fails when the right has extra rows, or passes
    when it lacks some."""
    con, left, right = pair(rel("('a', 1), ('b', 2)"), rel("('a', 1), ('c', 3), ('b', 2)"))
    assert rows_missing_from(con, left, right, "marts.t") == 0
    assert rows_missing_from(con, right, left, "marts.t") == 1


def test_one_way_counts_duplicates(pair):
    """Catches EXCEPT in the one-way check: the right holds one copy where the left has two."""
    con, left, right = pair(rel("('a', 1), ('a', 1)"), rel("('a', 1)"))
    assert rows_missing_from(con, left, right, "marts.t") == 1


def test_round_doubles_forgives_a_last_bit(pair):
    """Catches exact comparison being the only mode: a last-bit double difference is
    reported exactly, and equal once rounded."""
    cols = "k varchar, x double"
    con, left, right = pair(rel("('a', 0.1)", cols), rel("('a', 0.30000000000000004 - 0.2)", cols))
    assert compare_relation(con, left, right, "marts.t").differs
    assert not compare_relation(con, left, right, "marts.t", round_doubles=6).differs


def test_round_doubles_still_reports_a_real_difference(pair):
    """Catches rounding that hides a real difference along with the noise."""
    cols = "k varchar, x double"
    con, left, right = pair(
        rel("('a', 0.1), ('b', 1.0)", cols),
        rel("('a', 0.30000000000000004 - 0.2), ('b', 1.5)", cols),
    )
    rounded = compare_relation(con, left, right, "marts.t", round_doubles=6)
    assert rounded.differs and (rounded.only_left, rounded.only_right) == (1, 1)
