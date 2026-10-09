"""Tests for the warehouse comparison shared by compare_warehouses and the isolation check.

A comparison that passes on anything is worse than none, so each test below is a way a
lazy comparison would be wrong.
"""

import hashlib
import shutil
import tempfile
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


def test_keep_refuses_a_directory_that_is_not_empty(tmp_path: Path) -> None:
    """Catches --keep clearing a directory the caller named.

    The first version removed DIR recursively before using it, so pointing it at a
    directory that held anything else would have deleted that (#61 review, F1).
    """
    import check_tenant_isolation

    precious = tmp_path / "keep"
    precious.mkdir()
    (precious / "notes.txt").write_text("do not delete")

    with pytest.raises(SystemExit):
        check_tenant_isolation.main(["--keep", str(precious)])

    assert (precious / "notes.txt").read_text() == "do not delete"


def test_strict_columns_fails_on_a_column_on_one_side_only(tmp_path, capsys):
    """Catches `--strict-columns` passing over a column present on one side only, which is
    right for a change meant to alter columns and wrong for one meant to alter none."""
    import compare_warehouses

    build(tmp_path / "old_wh.duckdb", ["create table marts.t as select 1 as a, 2 as b"])
    build(tmp_path / "new_wh.duckdb", ["create table marts.t as select 1 as a"])
    old, new = str(tmp_path / "old_wh.duckdb"), str(tmp_path / "new_wh.duckdb")
    assert compare_warehouses.main([old, new]) == 0
    capsys.readouterr()
    assert compare_warehouses.main([old, new, "--strict-columns"]) == 1
    out = capsys.readouterr().out
    assert "columns only in OLD: b" in out
    assert "1 with columns on one side only" in out


def test_strict_columns_passes_when_the_columns_match(tmp_path):
    """Catches `--strict-columns` failing a comparison whose columns are the same."""
    import compare_warehouses

    for name in ("old_wh", "new_wh"):
        build(tmp_path / f"{name}.duckdb", ["create table marts.t as select 1 as a"])
    old, new = str(tmp_path / "old_wh.duckdb"), str(tmp_path / "new_wh.duckdb")
    assert compare_warehouses.main([old, new, "--strict-columns"]) == 0


def test_strict_columns_fails_on_a_relation_only_in_new(tmp_path, capsys):
    """Catches `--strict-columns` passing a NEW warehouse with an extra relation, which
    leaves it unable to show that the two hold the same relations. Without the flag an
    extra relation stays a report (#28 relied on that)."""
    import compare_warehouses

    build(tmp_path / "old_wh.duckdb", ["create table marts.t as select 1 as a"])
    build(
        tmp_path / "new_wh.duckdb",
        ["create table marts.t as select 1 as a", "create table marts.extra as select 1 as a"],
    )
    old, new = str(tmp_path / "old_wh.duckdb"), str(tmp_path / "new_wh.duckdb")
    assert compare_warehouses.main([old, new]) == 0
    capsys.readouterr()
    assert compare_warehouses.main([old, new, "--strict-columns"]) == 1
    out = capsys.readouterr().out
    assert "only in NEW" in out
    assert "1 only in NEW" in out


def build_dbt_style(path: Path, rows: str = "('a', 1)") -> Path:
    """Build a warehouse the way dbt does: its view names the file's own catalog, in three
    parts, so the view only reads while the file is attached under that stem."""
    path.parent.mkdir(parents=True, exist_ok=True)
    catalog = path.stem
    build(
        path,
        [
            "create table marts.t (k varchar, v integer)",
            f"insert into marts.t values {rows}",
            f"create view marts.v as select * from {catalog}.marts.t",
        ],
    )
    return path


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_copy_with_a_catalog_qualified_view_is_compared(tmp_path, capsys):
    """Catches the issue as filed: a copy named warehouse_before.duckdb has views that name
    `warehouse`, so attached under its stem every view fails with a Binder Error."""
    import compare_warehouses

    original = build_dbt_style(tmp_path / "a" / "warehouse.duckdb")
    copy = tmp_path / "b" / "warehouse_before.duckdb"
    copy.parent.mkdir()
    shutil.copy(original, copy)
    other = build_dbt_style(tmp_path / "c" / "other_wh.duckdb")

    assert compare_warehouses.main([str(copy), str(other)]) == 0
    assert "compared 2 relations: 2 identical, 0 differ" in capsys.readouterr().out


def test_copy_against_its_original_reads_each_views_own_rows(tmp_path, capsys):
    """Catches a view read from the other file: attached next to its original, the copy's
    view resolves `warehouse.marts.t` to the original's table and is called identical."""
    import compare_warehouses

    original = build_dbt_style(tmp_path / "warehouse.duckdb")
    copy = tmp_path / "warehouse_after.duckdb"
    shutil.copy(original, copy)
    with duckdb.connect(str(copy)) as con:
        con.execute("update marts.t set v = 2")

    code = compare_warehouses.main([str(original), str(copy)])
    out = capsys.readouterr().out
    assert code == 1
    assert "DIFFERS marts.t" in out
    assert "DIFFERS marts.v" in out


def test_files_with_the_same_stem_are_compared(tmp_path, capsys):
    """Catches the removed rule that the two files need different names: two builds of
    warehouse.duckdb in different directories are the ordinary case."""
    import compare_warehouses

    old = build_dbt_style(tmp_path / "old" / "warehouse.duckdb", "('a', 1)")
    new = build_dbt_style(tmp_path / "new" / "warehouse.duckdb", "('a', 1), ('b', 2)")

    assert compare_warehouses.main([str(old), str(new)]) == 1
    out = capsys.readouterr().out
    assert "DIFFERS marts.t" in out and "DIFFERS marts.v" in out


def test_views_naming_two_catalogs_exit_2_and_compare_nothing(tmp_path, capsys):
    """Catches guessing a catalog for a file whose views name several: it cannot be read
    under one name, so the run stops and names the file and the catalogs."""
    import compare_warehouses

    good = build_dbt_style(tmp_path / "good_wh.duckdb")
    bad = tmp_path / "warehouse.duckdb"
    build_dbt_style(tmp_path / "other.duckdb")
    with duckdb.connect(str(bad)) as con:
        con.execute("create schema marts")
        con.execute(f"attach '{tmp_path / 'other.duckdb'}' as other")
        con.execute("create table marts.t as select 'a' k, 1 v")
        con.execute("create view marts.v1 as select * from warehouse.marts.t")
        con.execute("create view marts.v2 as select * from other.marts.t")
    bad_copy = tmp_path / "bad_copy.duckdb"
    shutil.copy(bad, bad_copy)

    with pytest.raises(SystemExit) as raised:
        compare_warehouses.main([str(good), str(bad_copy)])
    captured = capsys.readouterr()
    assert raised.value.code == 2
    assert "bad_copy.duckdb" in captured.err
    assert "other" in captured.err and "warehouse" in captured.err
    assert captured.out == ""


def build_with_view(path: Path, view_sql: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    build(
        path,
        [
            "create table marts.t (k varchar, v integer)",
            "insert into marts.t values ('a', 1)",
            f"create view marts.v as {view_sql}",
        ],
    )
    return path


def test_copy_whose_view_holds_a_catalog_shaped_literal_is_compared(tmp_path, capsys):
    """Catches a string literal read as a view dependency: 'other.marts.t' names a real
    schema, so the copy was seen to need two catalogs and the run exited 2."""
    import compare_warehouses

    original = build_with_view(
        tmp_path / "a" / "warehouse.duckdb",
        "select 'other.marts.t' as note, * from warehouse.marts.t",
    )
    copy = tmp_path / "b" / "warehouse_before.duckdb"
    copy.parent.mkdir()
    shutil.copy(original, copy)
    other = build_with_view(
        tmp_path / "c" / "other_wh.duckdb",
        "select 'other.marts.t' as note, * from other_wh.marts.t",
    )

    assert compare_warehouses.main([str(copy), str(other)]) == 0
    assert "compared 2 relations: 2 identical, 0 differ" in capsys.readouterr().out


def test_view_catalogs_ignores_literals_in_a_stored_view(tmp_path):
    """Catches a literal naming a real schema counted as a catalog, read from the SQL that
    DuckDB stores (which drops comments, so the comment cases are tested below)."""
    from warehouse_diff import view_catalogs

    path = build_with_view(
        tmp_path / "warehouse.duckdb",
        "select 'it''s other.marts.t' as note, * from warehouse.marts.t",
    )
    assert view_catalogs(path) == {"warehouse"}


def test_view_catalogs_reads_quoted_identifiers(tmp_path):
    """Catches stripping that eats double-quoted identifiers: they can be the catalog."""
    from warehouse_diff import view_catalogs

    path = build_with_view(tmp_path / "warehouse.duckdb", 'select * from "warehouse"."marts"."t"')
    assert view_catalogs(path) == {"warehouse"}


def test_strip_removes_literals_and_comments_but_keeps_identifiers():
    """Catches independent replaces and a stripper that mistakes quote kinds: a comment
    marker or `'` inside a quoted identifier is not a comment or literal, a `"` inside a
    literal is not an identifier, and `''` does not end a literal."""
    from warehouse_diff import strip_literals_and_comments

    sql = (
        "select 'a.marts.t', 'it''s \"x.marts.t\"', \"we--ird'\".marts.t "
        "-- other2.marts.t\n from warehouse.marts.t /* other3.marts.t */"
    )
    stripped = strip_literals_and_comments(sql)
    for gone in ("a.marts.t", "x.marts.t", "other2", "other3"):
        assert gone not in stripped
    assert '"we--ird\'".marts.t' in stripped
    assert "from warehouse.marts.t" in stripped


def test_view_catalogs_ignores_catalog_shaped_text_in_literals_and_comments():
    """Catches comment or literal text counted as a catalog, by way of the stripper that
    view_catalogs applies to each view's SQL."""
    from warehouse_diff import THREE_PART, strip_literals_and_comments

    sql = "select 'lit.marts.t' -- other2.marts.t\n, * from warehouse.marts.t /* other3.marts.t */"
    found = {m[0] for m in THREE_PART.findall(strip_literals_and_comments(sql))}
    assert found == {"warehouse"}


def test_inputs_are_untouched_and_the_scratch_is_removed(tmp_path, monkeypatch):
    """Catches a comparison that writes beside the warehouses, or leaves its scratch
    databases behind in the temporary directory."""
    import compare_warehouses

    old = build_dbt_style(tmp_path / "old" / "old_wh.duckdb")
    original = build_dbt_style(tmp_path / "src" / "warehouse.duckdb")
    new = tmp_path / "new" / "warehouse_copy.duckdb"
    new.parent.mkdir()
    shutil.copy(original, new)
    before = {p: digest(p) for p in (old, new)}
    listing = sorted(p.name for d in (old.parent, new.parent) for p in d.iterdir())
    scratch_root = tmp_path / "scratch_root"
    scratch_root.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(scratch_root))

    assert compare_warehouses.main([str(old), str(new)]) == 0

    assert {p: digest(p) for p in (old, new)} == before
    assert sorted(p.name for d in (old.parent, new.parent) for p in d.iterdir()) == listing
    assert list(scratch_root.iterdir()) == []
