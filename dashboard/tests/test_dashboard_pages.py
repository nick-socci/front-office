"""Pages over a tiny extract made here (spec 0232 R3.1, R3.5): the Players page's team filter and
player history, and every page over an extract whose tables exist but hold no rows. No
dbt/ci.duckdb: pytest runs before the gates build it."""

import datetime as dt
from pathlib import Path

import duckdb
import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

import front_office_dashboard

PACKAGE = Path(front_office_dashboard.__file__).parent
PAGES = sorted((PACKAGE / "pages").glob("*.py"))
KEY = "platform varchar, league_id varchar, season bigint"


def make_extract(path: Path, *, populated: bool) -> None:
    """The marts the Players page and the league-season picker read, with or without rows."""
    con = duckdb.connect(str(path))
    con.execute("create schema marts")
    con.execute(
        "create table marts.extract_info (table_name varchar, row_count bigint,"
        " warehouse_modified_at timestamptz, extracted_at timestamptz, git_commit varchar)"
    )
    now = dt.datetime.now(dt.UTC).isoformat()
    con.execute(f"insert into marts.extract_info values ('t', 1, '{now}', '{now}', 'abc')")
    con.execute(
        f"create table marts.dim_fantasy_teams ({KEY}, fantasy_team_id bigint,"
        " team_name varchar, team_abbrev varchar)"
    )
    con.execute(
        f"create table marts.dim_player_league_seasons ({KEY}, platform_player_id bigint,"
        " mlbam_player_id bigint, player_name varchar, default_position varchar,"
        " replacement_group varchar, first_rostered_date date, last_rostered_date date,"
        " is_transaction_only boolean)"
    )
    con.execute(
        f"create table marts.fct_player_season_value ({KEY}, platform_player_id bigint,"
        " mlbam_player_id bigint, fantasy_team_id bigint, started_days bigint,"
        " played_started_days bigint, started_days_outside_matchups bigint,"
        " unverified_started_days bigint, first_started_date date, last_started_date date,"
        " total_value double)"
    )
    con.execute(
        f"create table marts.fct_player_category_value ({KEY}, platform_player_id bigint,"
        " fantasy_team_id bigint, category_key varchar, category_label varchar,"
        " is_lower_better boolean, played_days bigint, numerator double, denominator double,"
        " contribution double, value_over_replacement double, scaled_value double)"
    )
    con.execute(
        "create table marts.dim_players (mlbam_player_id bigint, player_name varchar,"
        " primary_position varchar, bats varchar, throws varchar, birth_date date,"
        " mlb_debut_date date)"
    )
    if populated:
        # Two teams with one name in one league-season; player 10 (mlbam 100) started for team 1
        # in 2026 and was only rostered in 2025; player 11 started for team 2.
        con.execute(
            "insert into marts.dim_fantasy_teams values"
            " ('espn', 'L', 2026, 1, 'Twins', 'TW1'), ('espn', 'L', 2026, 2, 'Twins', 'TW2'),"
            " ('espn', 'L', 2025, 1, 'Twins', 'TW1')"
        )
        con.execute(
            "insert into marts.dim_player_league_seasons values"
            " ('espn', 'L', 2026, 10, 100, 'Ann', 'SS', 'hitter',"
            " '2026-04-01', '2026-09-01', false),"
            " ('espn', 'L', 2025, 10, 100, 'Ann', 'SS', 'hitter',"
            " '2025-04-01', '2025-04-09', false),"
            " ('espn', 'L', 2026, 11, 110, 'Bob', 'SS', 'hitter',"
            " '2026-04-01', '2026-09-01', false)"
        )
        con.execute(
            "insert into marts.fct_player_season_value values"
            " ('espn', 'L', 2026, 10, 100, 1, 50, 50, 0, 0, '2026-04-01', '2026-09-01', 3.5),"
            " ('espn', 'L', 2026, 11, 110, 2, 40, 40, 0, 0, '2026-04-01', '2026-09-01', 1.5)"
        )
    con.close()


@pytest.fixture
def extract_at(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "extract.duckdb"
    monkeypatch.setenv("FO_DASHBOARD_EXTRACT", str(path))
    st.cache_data.clear()
    return path


def players_page() -> AppTest:
    return AppTest.from_file(str(PACKAGE / "pages" / "players.py"), default_timeout=30).run()


def test_the_team_filter_goes_by_id_so_two_teams_of_one_name_stay_apart(extract_at: Path) -> None:
    """Catches a filter on team_name: choosing the second "Twins" must show only its player."""
    make_extract(extract_at, populated=True)
    at = players_page()
    assert not at.exception
    assert at.selectbox(key="players_team").options == ["All", "Twins", "Twins"]
    assert set(at.dataframe[0].value["platform_player_id"]) == {10, 11}
    at.selectbox(key="players_team").select_index(2).run()
    assert not at.exception
    assert list(at.dataframe[0].value["platform_player_id"]) == [11]


def test_a_players_history_shows_a_season_rostered_and_never_started(extract_at: Path) -> None:
    """Catches a history driven by the value fact, which has no row for a season without a
    start: 2025 must appear, with no value, and the page must say what a blank means."""
    make_extract(extract_at, populated=True)
    at = players_page()
    assert not at.exception
    history = at.dataframe[-1].value
    assert list(history["season"]) == [2026, 2025]
    assert history["total_value"].isna().tolist() == [False, True]
    assert any("blank" in c.value and "never started" in c.value for c in at.caption)


def test_an_extract_with_no_rows_shows_an_empty_state_on_every_page(extract_at: Path) -> None:
    """Catches the league-season picker indexing an empty result."""
    make_extract(extract_at, populated=False)
    for page in PAGES:
        at = AppTest.from_file(str(page), default_timeout=30).run()
        assert not at.exception, page.name
        assert [i.value for i in at.info] == ["The extract holds no league-season yet."], page.name
        assert len(at.dataframe) == 0, page.name
