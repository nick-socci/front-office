"""Tests for the dbt Python model int_fantasy__optimal_lineups (spec 0012, R3.5-R3.7).

dbt cannot unit-test a Python model, so this loads the model file and calls
model(dbt, session) against an in-memory DuckDB holding small tables shaped like
int_fantasy__lineup_options and int_fantasy__lineup_slots (only the columns it reads).
"""

import importlib.util
from datetime import date
from pathlib import Path

import duckdb
import pytest

MODEL_PATH = (
    Path(__file__).resolve().parents[2]
    / "dbt/models/intermediate/fantasy/int_fantasy__optimal_lineups.py"
)
COLUMNS = [
    "platform",
    "league_id",
    "season",
    "scoring_date",
    "fantasy_team_id",
    "platform_player_id",
    "lineup_slot_id",
]
TYPES = ["VARCHAR", "VARCHAR", "BIGINT", "DATE", "BIGINT", "BIGINT", "BIGINT"]
DAY1, DAY2 = date(2026, 6, 1), date(2026, 6, 2)


def load_model():
    spec = importlib.util.spec_from_file_location("optimal_lineups_model", MODEL_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.model


class FakeDbt:
    def __init__(self, session):
        self.session = session

    def config(self, **kwargs):
        pass

    def ref(self, name):
        return self.session.table(name)


def option(league="1", day=DAY1, team=1, player=1, slot=1, value=1.0, actual=False):
    return ("espn", league, 2026, day, team, player, slot, "hitter", value, actual)


def slot(league="1", slot_id=1, count=1):
    return ("espn", league, 2026, slot_id, "hitter", count)


def run(options, slots):
    session = duckdb.connect()
    session.execute(
        "create table int_fantasy__lineup_options (platform varchar, league_id varchar, "
        "season bigint, scoring_date date, fantasy_team_id bigint, platform_player_id bigint, "
        "lineup_slot_id bigint, slot_role varchar, option_value double, is_actual boolean)"
    )
    session.execute(
        "create table int_fantasy__lineup_slots (platform varchar, league_id varchar, "
        "season bigint, lineup_slot_id bigint, slot_role varchar, slot_count bigint)"
    )
    if options:
        session.executemany(
            "insert into int_fantasy__lineup_options values (?,?,?,?,?,?,?,?,?,?)", options
        )
    if slots:
        session.executemany("insert into int_fantasy__lineup_slots values (?,?,?,?,?,?)", slots)
    return load_model()(FakeDbt(session), session)


def rows_of(relation):
    return sorted(relation.fetchall())


def test_a_null_option_does_not_hide_an_out_of_bound_one_on_the_same_team_day():
    """Catches (R3.7) the unvalued skip running before the bound check, so a 1001 passes."""
    options = [option(player=1, value=None), option(player=2, value=1001.0)]
    named = r"league_id=1.*scoring_date=2026-06-01.*fantasy_team_id=1"
    with pytest.raises(ValueError, match=named):
        run(options, [slot()])


def test_an_out_of_bound_value_raises_naming_the_team_day():
    """Catches the re-raise path failing to name the team-day (untested until now)."""
    options = [option(team=3, day=DAY2, player=2, value=-1001.0)]
    with pytest.raises(ValueError, match=r"scoring_date=2026-06-02, fantasy_team_id=3.*player 2"):
        run(options, [slot()])


def test_an_unvalued_team_day_has_no_rows_while_another_is_solved():
    """Catches (R3.5) an unvalued team-day returning rows, or poisoning its neighbours."""
    options = [
        option(team=1, player=1, value=None),
        option(team=1, player=2, value=2.0),
        option(team=2, player=3, value=4.0),
    ]
    assert rows_of(run(options, [slot()])) == [("espn", "1", 2026, DAY1, 2, 3, 1)]


def test_the_result_has_the_seven_columns_with_their_types_and_the_expected_rows():
    """Catches a renamed, reordered or retyped column, and a wrong assignment."""
    options = [
        option(player=1, slot=1, value=1.0, actual=True),
        option(player=2, slot=1, value=3.0),
    ]
    relation = run(options, [slot()])
    assert relation.columns == COLUMNS
    assert [str(t) for t in relation.types] == TYPES
    assert rows_of(relation) == [("espn", "1", 2026, DAY1, 1, 2, 1)]


def test_no_option_rows_gives_an_empty_relation_with_the_same_columns_and_types():
    """Catches an empty input producing a relation with no or differently typed columns."""
    relation = run([], [slot()])
    assert relation.columns == COLUMNS
    assert [str(t) for t in relation.types] == TYPES
    assert relation.fetchall() == []


def test_the_rows_do_not_depend_on_input_order_and_each_league_uses_its_own_slots():
    """Catches (R3.6) order dependence, and one league-season's slot counts leaking into
    another's: league A has one slot, league B two, and each is filled to its own count."""
    options = [
        option(league="A", player=1, value=5.0),
        option(league="A", player=2, value=6.0),
        option(league="B", player=3, value=5.0),
        option(league="B", player=4, value=6.0),
    ]
    slots = [slot(league="A", count=1), slot(league="B", count=2)]
    expected = [
        ("espn", "A", 2026, DAY1, 1, 2, 1),
        ("espn", "B", 2026, DAY1, 1, 3, 1),
        ("espn", "B", 2026, DAY1, 1, 4, 1),
    ]
    assert rows_of(run(options, slots)) == expected
    assert rows_of(run(list(reversed(options)), list(reversed(slots)))) == expected
