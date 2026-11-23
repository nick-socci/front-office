"""data.query over a tiny extract (spec 0232 R3, ADR 0147): bound parameters, one connection
per query, and a cache that a republished extract clears. No dbt/ci.duckdb: pytest runs before
the gates build it."""

from pathlib import Path

import duckdb
import pytest
import streamlit as st

from front_office_dashboard import data


def make_extract(path: Path, wins: int) -> None:
    temporary = path.with_name(path.name + ".tmp")
    con = duckdb.connect(str(temporary))
    con.execute("create schema marts")
    con.execute(f"create table marts.standings as select 1 as team_id, {wins} as wins, 'a' as name")
    con.execute("insert into marts.standings values (2, 7, 'b')")
    con.close()
    temporary.replace(path)  # one rename, as the extract publishes


@pytest.fixture
def queries(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    directory = tmp_path / "queries"
    directory.mkdir()
    (directory / "wins.sql").write_text(
        "select team_id, wins from marts.standings where team_id = $team_id"
    )
    (directory / "named.sql").write_text("select team_id from marts.standings where name = $name")
    monkeypatch.setattr(data, "QUERIES", directory)
    monkeypatch.setenv("FO_DASHBOARD_EXTRACT", str(tmp_path / "extract.duckdb"))
    st.cache_data.clear()
    return directory


def test_a_query_binds_its_parameters_by_name(tmp_path: Path, queries: Path) -> None:
    """Catches a parameter that is not bound: team 2's row, not team 1's."""
    make_extract(tmp_path / "extract.duckdb", 3)
    frame = data.query("wins", team_id=2)
    assert frame.to_dict("records") == [{"team_id": 2, "wins": 7}]


def test_a_parameter_is_a_value_never_sql(tmp_path: Path, queries: Path) -> None:
    """Catches a query string built from input: a value shaped like SQL is only a value."""
    make_extract(tmp_path / "extract.duckdb", 3)
    frame = data.query("named", name="a' or '1'='1")
    assert len(frame) == 0
    assert data.query("named", name="a")["team_id"].tolist() == [1]


def test_the_extract_is_opened_read_only_and_closed(tmp_path: Path, queries: Path) -> None:
    """Catches a held connection: after a query the file can be opened for writing."""
    path = tmp_path / "extract.duckdb"
    make_extract(path, 3)
    data.query("wins", team_id=1)
    con = duckdb.connect(str(path))
    con.execute("insert into marts.standings values (3, 0, 'c')")
    con.close()


def test_a_republished_extract_misses_the_cache(tmp_path: Path, queries: Path) -> None:
    """Catches a stale cache after the daily rename: a new file (a new inode) is read anew."""
    path = tmp_path / "extract.duckdb"
    make_extract(path, 3)
    assert data.query("wins", team_id=1)["wins"].tolist() == [3]
    assert data.query("wins", team_id=1)["wins"].tolist() == [3]
    make_extract(path, 4)
    assert data.query("wins", team_id=1)["wins"].tolist() == [4]


def test_the_same_extract_is_served_from_the_cache(
    tmp_path: Path, queries: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Catches a cache that never hits: a second identical call does not open the file."""
    path = tmp_path / "extract.duckdb"
    make_extract(path, 3)
    data.query("wins", team_id=1)
    opened: list[str] = []
    real = duckdb.connect

    def spy(*args: object, **kwargs: object) -> duckdb.DuckDBPyConnection:
        opened.append("connect")
        return real(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(duckdb, "connect", spy)
    data.query("wins", team_id=1)
    assert opened == []
    data.query("wins", team_id=2)
    assert opened == ["connect"]


def test_the_extract_path_defaults_under_the_repository(monkeypatch: pytest.MonkeyPatch) -> None:
    """Catches the default found from the working directory instead of the module file."""
    monkeypatch.delenv("FO_DASHBOARD_EXTRACT", raising=False)
    monkeypatch.chdir("/")
    path = data.extract_path()
    assert path.parts[-3:] == ("data", "dashboard", "extract.duckdb")
    assert (path.parents[2] / "pyproject.toml").exists()


def test_the_env_var_names_the_extract(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FO_DASHBOARD_EXTRACT", "/somewhere/e.duckdb")
    assert data.extract_path() == Path("/somewhere/e.duckdb")
