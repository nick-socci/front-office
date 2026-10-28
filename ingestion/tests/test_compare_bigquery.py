"""The comparison of a BigQuery build with DuckDB's (spec 0130, R5.2 to R5.5; ADR 0053).

Tested on two small DuckDB databases. The one standing in for BigQuery holds what its
tables look like once read back: BIGINT for INT64, TIMESTAMP WITH TIME ZONE for TIMESTAMP.
Nothing here talks to BigQuery.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import duckdb
import pytest

import compare_bigquery as cmp

RELATION = "marts.fct_thing"


@pytest.fixture
def con(tmp_path: Path) -> duckdb.DuckDBPyConnection:
    """One connection with an empty `local` and an empty `bq`, each with a marts schema."""
    connection = duckdb.connect()
    for name in ("local", "bq"):
        connection.execute(f"attach '{tmp_path / name}.duckdb' as {name}")
        connection.execute(f"create schema {name}.marts")
    return connection


LOCAL_DDL = (
    "(id bigint, total hugeint, small integer, name varchar, day date, ok boolean, "
    "seen_at timestamp, scale double)"
)
BQ_DDL = (
    "(id bigint, total bigint, small bigint, name varchar, day date, ok boolean, "
    "seen_at timestamptz, scale double)"
)
ROWS = (
    "(1, 10, 1, 'a', date '2026-04-01', true, timestamp '2026-04-01 12:00:00', 0.1), "
    "(2, 20, 2, 'b', date '2026-04-02', false, timestamp '2026-04-02 00:30:00', 2.5), "
    "(3, 30, 3, null, null, null, null, null)"
)
BQ_ROWS = ROWS.replace("timestamp '", "timestamptz '").replace("00'", "00+00'")


def fill(con: duckdb.DuckDBPyConnection, local_rows: str = ROWS, bq_rows: str = BQ_ROWS) -> None:
    con.execute(f"create table local.{RELATION} {LOCAL_DDL}")
    con.execute(f"create table bq.{RELATION} {BQ_DDL}")
    con.execute(f"insert into local.{RELATION} values {local_rows}")
    con.execute(f"insert into bq.{RELATION} values {bq_rows}")


def compare(con: duckdb.DuckDBPyConnection, **kwargs: object) -> cmp.Result:
    return cmp.compare_relation(con, "local", "bq", RELATION, ["id"], **kwargs)  # type: ignore[arg-type]


def test_an_equal_pair_passes_across_the_two_warehouses_types(
    con: duckdb.DuckDBPyConnection,
) -> None:
    """Catches the type mapping failing a build that is the same: HUGEINT and INTEGER
    against INT64, a naive timestamp against an instant in UTC."""
    fill(con)
    result = compare(con)
    assert result.problems == []
    assert (result.left_rows, result.right_rows, result.only_left, result.only_right) == (
        3,
        3,
        0,
        0,
    )
    assert result.floats == {
        "scale": cmp.FloatColumn(compared=3, exactly_equal=3, beyond_tolerance=0)
    }
    assert result.passed


def test_a_timestamp_is_compared_as_an_instant_not_as_text(
    con: duckdb.DuckDBPyConnection,
) -> None:
    """Catches the same instant written in another zone read as a difference, and a
    different instant read as the same."""
    fill(con, bq_rows=BQ_ROWS.replace("2026-04-01 12:00:00+00", "2026-04-01 08:00:00-04"))
    assert compare(con).passed
    con.execute(f"update bq.{RELATION} set seen_at = seen_at + interval 1 second where id = 2")
    result = compare(con)
    assert (result.only_left, result.only_right) == (1, 1) and not result.passed


def test_a_differing_integer_text_date_or_boolean_fails(con: duckdb.DuckDBPyConnection) -> None:
    """Catches a wrong value in a column that is held exactly."""
    for change in ("total = 21", "name = 'B'", "day = date '2026-04-03'", "ok = true"):
        con.execute(f"drop table if exists local.{RELATION}")
        con.execute(f"drop table if exists bq.{RELATION}")
        fill(con)
        con.execute(f"update bq.{RELATION} set {change} where id = 2")
        result = compare(con)
        assert (result.only_left, result.only_right) == (1, 1), change
        assert not result.passed


def test_a_float_inside_the_tolerance_passes_and_is_reported(
    con: duckdb.DuckDBPyConnection,
) -> None:
    """Catches the last digits of a float sum failing the comparison, and the difference
    going unreported."""
    fill(con)
    con.execute(f"update bq.{RELATION} set scale = 2.5 * (1 + 1e-12) where id = 2")
    result = compare(con)
    column = result.floats["scale"]
    assert (column.compared, column.exactly_equal, column.beyond_tolerance) == (3, 2, 0)
    assert column.largest_relative == pytest.approx(1e-12, rel=1e-3)
    assert column.largest_absolute == pytest.approx(2.5e-12, rel=1e-3)
    assert result.passed


def test_a_float_outside_the_tolerance_fails(con: duckdb.DuckDBPyConnection) -> None:
    """Catches a wrong number hiding behind the tolerance: a relative 1e-8 is too far."""
    fill(con)
    con.execute(f"update bq.{RELATION} set scale = 2.5 * (1 + 1e-8) where id = 2")
    result = compare(con)
    assert result.floats["scale"].beyond_tolerance == 1
    assert not result.passed


def test_values_near_zero_are_held_to_an_absolute_difference(
    con: duckdb.DuckDBPyConnection,
) -> None:
    """Catches zero against 1e-15 failing on relative difference, which is 1 there, and the
    absolute rule reaching values that are not near zero."""
    fill(con)
    con.execute(f"update local.{RELATION} set scale = 0 where id = 1")
    con.execute(f"update bq.{RELATION} set scale = 1e-15 where id = 1")
    assert compare(con).passed
    con.execute(f"update bq.{RELATION} set scale = 1e-9 where id = 1")
    assert compare(con).floats["scale"].beyond_tolerance == 1
    # 5e-13 apart is inside the absolute bound, but these are not below 1e-3
    con.execute(f"update local.{RELATION} set scale = 0.002 where id = 1")
    con.execute(f"update bq.{RELATION} set scale = 0.002 + 5e-11 where id = 1")
    assert compare(con).floats["scale"].beyond_tolerance == 1


def test_a_null_on_one_side_only_is_a_difference(con: duckdb.DuckDBPyConnection) -> None:
    """Catches a float that is null on one warehouse and a number on the other passing
    because a comparison with null is null."""
    fill(con)
    con.execute(f"update bq.{RELATION} set scale = null where id = 1")
    result = compare(con)
    assert result.floats["scale"].beyond_tolerance == 1 and not result.passed
    con.execute(f"update bq.{RELATION} set scale = 0.1 where id = 1")
    con.execute(f"update bq.{RELATION} set scale = 7 where id = 3")
    assert compare(con).floats["scale"].beyond_tolerance == 1


def test_a_key_that_does_not_join_fails(con: duckdb.DuckDBPyConnection) -> None:
    """Catches float values going uncompared because their rows found no partner."""
    fill(con)
    con.execute(f"update bq.{RELATION} set id = 4 where id = 3")
    result = compare(con)
    assert result.floats["scale"].compared == 2
    assert result.unjoined == 2
    assert not result.passed


def test_a_missing_row_or_a_duplicated_one_fails(con: duckdb.DuckDBPyConnection) -> None:
    """Catches a relation short a row, and one row twice: compared as multisets."""
    fill(con)
    con.execute(f"delete from bq.{RELATION} where id = 3")
    result = compare(con)
    assert (result.left_rows, result.right_rows, result.only_left) == (3, 2, 1)
    assert not result.passed
    con.execute(f"insert into bq.{RELATION} select * from bq.{RELATION} where id = 2")
    assert not compare(con).passed


def test_a_column_on_one_side_or_of_another_kind_is_a_problem(
    con: duckdb.DuckDBPyConnection,
) -> None:
    """Catches a column BigQuery lacks, one it adds, and a number that came back as text."""
    fill(con)
    con.execute(f"alter table bq.{RELATION} drop column ok")
    con.execute(f"alter table bq.{RELATION} add column extra bigint")
    con.execute(f"alter table bq.{RELATION} alter column small type varchar")
    result = compare(con)
    assert result.problems == [
        "small: integer in DuckDB, text in BigQuery",
        "ok: only in DuckDB",
        "extra: only in BigQuery",
    ]
    assert not result.passed


def test_a_relation_with_floats_and_no_key_is_a_problem(con: duckdb.DuckDBPyConnection) -> None:
    """Catches float columns passing uncompared because nothing says how to pair the rows."""
    fill(con)
    result = cmp.compare_relation(con, "local", "bq", RELATION, None)
    assert result.problems == ["float columns and no declared unique key"]
    assert not result.passed


def test_exact_mode_holds_floats_to_equality(con: duckdb.DuckDBPyConnection) -> None:
    """Catches the BigQuery-against-BigQuery comparison (R5.5) using the tolerance: it asks
    whether BigQuery reproduces itself, exactly."""
    fill(con)
    con.execute(f"update bq.{RELATION} set scale = 2.5 * (1 + 1e-12) where id = 2")
    assert compare(con).passed
    exact = compare(con, exact_floats=True)
    assert (exact.only_left, exact.only_right) == (1, 1) and not exact.passed


def test_the_unique_key_is_read_from_the_models_tests() -> None:
    """Catches the key being taken from the wrong model, or a combination being missed."""
    manifest = {
        "nodes": {
            "test.a": {
                "resource_type": "test",
                "test_metadata": {"name": "unique", "kwargs": {"column_name": "id"}},
                "attached_node": "model.front_office.one",
            },
            "test.b": {
                "resource_type": "test",
                "test_metadata": {
                    "name": "unique_combination_of_columns",
                    "kwargs": {"combination_of_columns": ["league_id", "season"]},
                },
                "attached_node": "model.front_office.two",
            },
            "test.c": {
                "resource_type": "test",
                "test_metadata": {"name": "not_null", "kwargs": {"column_name": "x"}},
                "attached_node": "model.front_office.three",
            },
        }
    }
    assert cmp.unique_key(manifest, "model.front_office.one") == ["id"]
    assert cmp.unique_key(manifest, "model.front_office.two") == ["league_id", "season"]
    assert cmp.unique_key(manifest, "model.front_office.three") is None


def test_the_selected_seeds_are_listed_with_the_models(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Catches the comparison leaving the seeds out (spec 0135): dbt is asked for seeds as
    well as models, a seed is listed with its key from its tests, and an ephemeral model,
    which is never built, is not."""
    rows = [
        {
            "unique_id": "model.front_office.one",
            "name": "one",
            "schema": "marts",
            "config": {"materialized": "table"},
        },
        {
            "unique_id": "model.front_office.inline",
            "name": "inline",
            "schema": "marts",
            "config": {"materialized": "ephemeral"},
        },
        {
            "unique_id": "seed.front_office.espn_stat_ids",
            "name": "espn_stat_ids",
            "schema": "seeds",
            "config": {"materialized": "seed"},
        },
    ]
    manifest = {
        "nodes": {
            "test.a": {
                "resource_type": "test",
                "test_metadata": {"name": "unique", "kwargs": {"column_name": "stat_id"}},
                "attached_node": "seed.front_office.espn_stat_ids",
            }
        }
    }
    target = tmp_path / "dbt_target"
    target.mkdir()
    (target / "manifest.json").write_text(json.dumps(manifest))
    commands: list[list[str]] = []

    def fake_run(command: list[str], **_: Any) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        return subprocess.CompletedProcess(
            command, 0, stdout="\n".join(json.dumps(r) for r in rows) + "\n"
        )

    monkeypatch.setattr(cmp.subprocess, "run", fake_run)
    assert cmp.selected_relations(target) == [
        ("marts", "one", None),
        ("seeds", "espn_stat_ids", ["stat_id"]),
    ]
    assert "seed" in commands[0] and "model" in commands[0]


# -- JSON columns are not read back or compared (spec 0143, amendment of 2026-10-12) ---------


def test_a_json_column_is_not_compared_and_is_named(con: duckdb.DuckDBPyConnection) -> None:
    """Catches the raw payloads being compared: stg_raw__season_responses carries them, and
    a JSON column is billed whole and BigQuery rewrites its text. The column is not read
    back, so it is on DuckDB's side only; that must not be the problem a missing column is,
    and the rest of the relation is still compared."""
    con.execute(f"create table local.{RELATION} (id bigint, name varchar, payload json)")
    con.execute(f"create table bq.{RELATION} (id bigint, name varchar)")
    con.execute(f"""insert into local.{RELATION} values (1, 'a', '{{"x": 1}}')""")
    con.execute(f"insert into bq.{RELATION} values (1, 'a')")
    result = compare(con, right_unread={"payload"})
    assert result.problems == [] and result.passed
    assert result.uncompared == ["payload"]
    assert any(
        "JSON or nested columns not compared: payload" in line
        for line in cmp.describe(result, "DuckDB", "BigQuery")
    )

    con.execute(f"update bq.{RELATION} set name = 'b'")
    assert not compare(con, right_unread={"payload"}).passed


def test_a_json_column_bigquery_does_not_have_is_a_problem(
    con: duckdb.DuckDBPyConnection,
) -> None:
    """Catches the view losing `payload` on BigQuery unnoticed: a JSON column is not read
    back, so its absence from what was read proves nothing. It must be among the columns
    BigQuery's own schema listed as JSON (review of #145, F2). The same the other way: a
    JSON column only BigQuery has."""
    con.execute(f"create table local.{RELATION} (id bigint, payload json)")
    con.execute(f"create table bq.{RELATION} (id bigint)")
    con.execute(f"""insert into local.{RELATION} values (1, '{{"x": 1}}')""")
    con.execute(f"insert into bq.{RELATION} values (1)")
    missing = compare(con, right_unread=set())
    assert missing.problems == ["payload: only in DuckDB"] and not missing.passed

    extra = compare(con, right_unread={"payload", "extra"})
    assert extra.problems == ["extra: only in BigQuery"] and not extra.passed

    both_unread = cmp.compare_relation(
        con, "bq", "bq", RELATION, ["id"], left_unread={"payload"}, right_unread=set()
    )
    assert both_unread.problems == ["payload: only in DuckDB"]


def test_the_json_fields_left_unread_are_reported_by_name() -> None:
    """Catches the list of unread fields drifting from the fields that are read."""
    from types import SimpleNamespace

    schema = [
        SimpleNamespace(name="source", field_type="STRING"),
        SimpleNamespace(name="payload", field_type="json"),
        SimpleNamespace(name="teams", field_type="RECORD", mode="REPEATED"),
        SimpleNamespace(name="eligible", field_type="INT64", mode="REPEATED"),
        SimpleNamespace(name="season", field_type="INT64", mode="NULLABLE"),
    ]
    assert cmp.fields_left_unread(schema) == {"payload", "teams", "eligible"}
    assert [f.name for f in cmp.fields_read_back(schema)] == ["source", "season"]


def test_a_json_column_that_bigquery_holds_as_text_is_a_problem(
    con: duckdb.DuckDBPyConnection,
) -> None:
    """Catches the view's `payload` becoming a STRING on BigQuery unnoticed: a JSON field is
    never read back, so a column of that name that was read is not JSON there (review of
    #145, round 2). Its values are still not compared."""
    con.execute(f"create table local.{RELATION} (id bigint, payload json)")
    con.execute(f"create table bq.{RELATION} (id bigint, payload varchar)")
    con.execute(f"""insert into local.{RELATION} values (1, '{{"x": 1}}')""")
    con.execute(f"""insert into bq.{RELATION} values (1, '{{"x":1}}')""")
    result = compare(con, right_unread=set())
    assert result.problems == ["payload: JSON in DuckDB, text in BigQuery"]
    assert not result.passed and (result.only_left, result.only_right) == (0, 0)


def test_only_the_fields_that_are_not_json_are_read_back() -> None:
    """Catches the payloads being downloaded and, for a view, billed."""
    from types import SimpleNamespace

    schema = [
        SimpleNamespace(name="source", field_type="STRING"),
        SimpleNamespace(name="payload", field_type="JSON"),
        SimpleNamespace(name="season_start", field_type="DATE"),
    ]
    assert [f.name for f in cmp.fields_read_back(schema)] == ["source", "season_start"]


# -- nested columns are left out like JSON; the rest of a capture view is compared ---------


def test_a_nested_column_is_not_compared_and_the_scalar_columns_are(
    con: duckdb.DuckDBPyConnection,
) -> None:
    """Catches a capture view's nested field (spelled differently by the two warehouses)
    failing the comparison, and catches its scalar columns, the capture's identity, not
    being compared (spec 0150, PR #157 review)."""
    con.execute(
        f"create table local.{RELATION} (file_path varchar, id varchar, teams struct(id bigint)[])"
    )
    con.execute(f"create table bq.{RELATION} (file_path varchar, id varchar)")
    con.execute(f"insert into local.{RELATION} values ('a', '7', [{{'id': 3}}])")
    con.execute(f"insert into bq.{RELATION} values ('a', '7')")
    result = compare(con, right_unread={"teams"})
    assert result.passed and result.uncompared == ["teams"]

    con.execute(f"update bq.{RELATION} set id = '8'")
    assert not compare(con, right_unread={"teams"}).passed


def test_nested_duckdb_types_are_recognised() -> None:
    """Catches a nested type being compared by value, or a scalar one being skipped."""
    for nested in (
        "STRUCT(id BIGINT)[]",
        "MAP(VARCHAR, JSON)",
        "STRUCT(a JSON)",
        "BIGINT[]",
        "JSON",
    ):
        assert cmp.is_uncompared(nested), nested
    for scalar in ("VARCHAR", "BIGINT", "DOUBLE", "DATE", "TIMESTAMP"):
        assert not cmp.is_uncompared(scalar), scalar


def test_json_columns_are_held_to_the_same_schema_whichever_side_has_them(
    con: duckdb.DuckDBPyConnection,
) -> None:
    """Catches a JSON column on one side that the other holds as another type, or lacks,
    in every arrangement: the JSON side read back or not, left or right. Rounds 1 to 3 of
    #145's review each found one arrangement the case-by-case check let through; the last
    was two BigQuery builds, the first with the column as JSON (so not read back) and the
    second with it as text."""
    con.execute(f"create table local.{RELATION} (id bigint)")
    con.execute(f"create table bq.{RELATION} (id bigint, payload varchar)")
    con.execute(f"insert into local.{RELATION} values (1)")
    con.execute(f"""insert into bq.{RELATION} values (1, '{{"x":1}}')""")

    def problems(**unread: set[str]) -> list[str]:
        return cmp.compare_relation(
            con, "local", "bq", RELATION, ["id"], left_name="A", right_name="B", **unread
        ).problems

    # JSON in A and not read back; text in B.
    assert problems(left_unread={"payload"}, right_unread=set()) == [
        "payload: JSON in A, text in B"
    ]
    # Neither side lists it as JSON: an ordinary column only B has.
    assert problems(left_unread=set(), right_unread=set()) == ["payload: only in B"]

    con.execute(f"alter table bq.{RELATION} drop column payload")
    # JSON in both and read back from neither: present on both, not compared, no problem.
    both = cmp.compare_relation(
        con, "local", "bq", RELATION, ["id"], left_unread={"payload"}, right_unread={"payload"}
    )
    assert both.problems == [] and both.uncompared == ["payload"] and both.passed
    # JSON in one only, absent from the other.
    assert problems(left_unread={"payload"}, right_unread=set()) == ["payload: only in A"]
    assert problems(left_unread=set(), right_unread={"payload"}) == ["payload: only in B"]

    con.execute(f"alter table local.{RELATION} add column payload varchar")
    # Text in A; JSON in B and not read back.
    assert problems(left_unread=set(), right_unread={"payload"}) == [
        "payload: text in A, JSON in B"
    ]


LINEUPS = "intermediate.int_fantasy__optimal_lineups"
LINEUP_DDL = (
    "(platform varchar, league_id varchar, season bigint, scoring_date date, "
    "fantasy_team_id bigint, platform_player_id bigint, lineup_slot_id bigint)"
)


def lineup(day: int, team: int, player: int, slot: int = 1) -> str:
    return f"('espn', '1', 2026, date '2026-06-{day:02d}', {team}, {player}, {slot})"


def lineups_pair(
    con: duckdb.DuckDBPyConnection, local_rows: list[str], bq_rows: list[str]
) -> cmp.Result:
    for name, rows in (("local", local_rows), ("bq", bq_rows)):
        con.execute(f"create schema if not exists {name}.intermediate")
        con.execute(f"create table {name}.{LINEUPS} {LINEUP_DDL}")
        if rows:
            con.execute(f"insert into {name}.{LINEUPS} values {', '.join(rows)}")
    return cmp.compare_relation(con, "local", "bq", LINEUPS, None, left_name="A", right_name="B")


def test_a_differing_lineup_is_printed_as_its_team_day_with_the_rows_of_each_side(
    con: duckdb.DuckDBPyConnection,
) -> None:
    """Catches R3.3 unmet: a solver row that differs must come out as the team-day it is in,
    with that team-day's rows on each side, not as a count. A team-day that is the same on
    both sides must not be listed."""
    result = lineups_pair(
        con,
        [lineup(1, 1, 10), lineup(1, 1, 11, 2), lineup(2, 1, 12), lineup(1, 2, 20)],
        [lineup(1, 1, 10), lineup(1, 1, 13, 2), lineup(2, 1, 12), lineup(1, 2, 20)],
    )
    assert not result.passed
    assert [g.group for g in result.differing_groups] == [("espn", "1", 2026, _date(1), 1)]
    difference = result.differing_groups[0]
    assert [row[5] for row in difference.left_rows] == [10, 11]
    assert [row[5] for row in difference.right_rows] == [10, 13]
    printed = "\n".join(cmp.describe(result, "A", "B"))
    assert "differs: platform=espn, league_id=1, season=2026, scoring_date=2026-06-01" in printed
    assert "fantasy_team_id=1" in printed
    assert "A: [" in printed and "B: [" in printed and "13" in printed
    assert "fantasy_team_id=2" not in printed


def test_a_team_day_present_on_one_side_only_is_listed_with_nothing_on_the_other(
    con: duckdb.DuckDBPyConnection,
) -> None:
    """Catches a team-day one warehouse solved and the other left empty (an unvalued
    period on one side) being missed because it has no rows to show on a side."""
    result = lineups_pair(con, [lineup(1, 1, 10)], [])
    difference = result.differing_groups[0]
    assert len(difference.left_rows) == 1 and difference.right_rows == []


def test_every_differing_team_day_is_listed_in_order(con: duckdb.DuckDBPyConnection) -> None:
    """Catches a listing cut short (pre-PR review, F2): R3.3 asks for each team-day that
    differs, so 25 differing team-days print 25, in team order."""
    teams = 25
    result = lineups_pair(con, [lineup(1, team, 10) for team in range(1, teams + 1)], [])
    assert len(result.differing_groups) == teams
    printed = "\n".join(cmp.describe(result, "A", "B"))
    assert printed.count("differs:") == teams
    listed = [
        line.split("fantasy_team_id=")[1] for line in printed.splitlines() if "differs:" in line
    ]
    assert listed == [str(team) for team in range(1, teams + 1)]


def test_an_equal_lineup_relation_lists_nothing(con: duckdb.DuckDBPyConnection) -> None:
    """Catches the listing appearing on a pass."""
    rows = [lineup(1, 1, 10), lineup(2, 1, 11)]
    result = lineups_pair(con, rows, rows)
    assert result.passed and result.differing_groups == []


def test_other_relations_are_not_listed_by_group(con: duckdb.DuckDBPyConnection) -> None:
    """Catches the group listing reaching a relation it was not asked for."""
    fill(con)
    con.execute(f"update bq.{RELATION} set total = 21 where id = 2")
    result = compare(con)
    assert not result.passed and result.differing_groups == []


def _date(day: int) -> object:
    from datetime import date

    return date(2026, 6, day)
