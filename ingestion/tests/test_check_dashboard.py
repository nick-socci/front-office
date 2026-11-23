"""scripts/check_dashboard.py holds the dashboard's queries to spec 0232 R4 and R7.1.

The queries must read only the marts the exposure names (R4.1, R4.3), compute nothing (R4.2:
no aggregate, window, GROUP BY, HAVING, QUALIFY, or arithmetic across two columns), and run
against an extract of the CI warehouse (R7.1). Each planted query here must be refused for
its own reason, and each query that is plain must pass, so that the rules neither miss a
construct nor refuse the select-join-filter-sort the app is allowed. The R7.1 tests build a
tiny warehouse in tmp_path, because pytest runs before the gates build dbt/ci.duckdb.
"""

from pathlib import Path

import duckdb
import pytest

import check_dashboard as cd

EXPOSURE_YAML = """
exposures:
  - name: front_office_dashboard
    type: dashboard
    depends_on:
      - ref('team_names')
      - ref('standings')
"""


def problems_of(sql: str, name: str = "q.sql") -> list[str]:
    return cd.analyse(name, sql).problems


# Each of these must be refused; the second element is the text the message must contain.
REFUSED = [
    ("select team_id from marts.standings group by team_id", "group by"),
    ("select team_id from marts.standings group by all", "group by"),
    ("select team_id from marts.standings where wins > 1 having wins > 2", "having"),
    ("select sum(wins) from marts.standings", "sum"),
    ("select count(*) from marts.standings", "count"),
    ("select max(wins) from marts.standings", "max"),
    ("select row_number() over (order by wins) from marts.standings", "window"),
    ("select team_id from marts.standings qualify wins > 1", "qualify"),
    ("select a.wins - a.losses from marts.standings a", "arithmetic"),
    ("select team_id from marts.standings order by wins / losses", "arithmetic"),
    ("select team_id from marts.standings where wins + losses > 3", "arithmetic"),
    (
        "select a.wins * b.wins from marts.standings a join marts.standings b using (team_id)",
        "arithmetic",
    ),
    ("select (wins - 1) * losses from marts.standings", "arithmetic"),
    (
        "with c as (select wins + losses as games from marts.standings) select games from c",
        "arithmetic",
    ),
    ("select * from (select wins % losses from marts.standings) s", "arithmetic"),
    ("select team_id from standings", "standings"),
    ("select team_id from staging.stg_espn__teams", "staging.stg_espn__teams"),
    ("select team_id from main.marts.standings", "main.marts.standings"),
    ("select * from read_parquet('x')", "table function"),
    ("select * from read_csv('x.csv')", "table function"),
    ("select * from read_json('x.json')", "table function"),
    ("attach 'other.duckdb' as o", "attach"),
    ("select 1; select 2", "one statement"),
    ("select from from", "parse"),
]


@pytest.mark.parametrize(("sql", "expected"), REFUSED, ids=[r[0][:50] for r in REFUSED])
def test_a_planted_construct_is_refused(sql, expected):
    """Catches a rule that misses its construct: each query breaks exactly one rule, and the
    message must name the file and the construct."""
    problems = problems_of(sql)
    assert problems, f"accepted: {sql}"
    assert all(p.startswith("q.sql: ") for p in problems)
    assert any(expected in p.lower() for p in problems), problems


ACCEPTED = [
    "select team_id, wins from marts.standings where season = 2026 order by wins desc",
    "select a.team_id, n.name from marts.standings a join marts.team_names n"
    " on a.team_id = n.team_id and a.season = n.season where a.season = 2026 order by n.name",
    "select season - 1 from marts.standings",
    "select team_id from marts.standings where season - 1 = 2025",
    "select team_id from marts.standings order by case when wins > 1 then 0 else 1 end, team_id",
    "select distinct season from marts.standings order by season desc",
    "with s as (select team_id, wins from marts.standings) select team_id from s where wins > 1",
    "select team_id from marts.standings where season = $season and team_id = $team_id",
    "select -wins from marts.standings",
    "-- a comment mentioning group by and sum(x)\nselect team_id from marts.standings",
]


@pytest.mark.parametrize("sql", ACCEPTED, ids=[a[:50] for a in ACCEPTED])
def test_a_plain_query_is_accepted(sql):
    """Catches a rule too wide: selecting, joining, filtering and sorting must pass, and
    so must arithmetic between one column and a literal."""
    sql_with_example = '-- example: {"season": 2026, "team_id": 1}\n' + sql if "$" in sql else sql
    assert problems_of(sql_with_example) == []


def test_a_parameter_without_an_example_is_refused():
    problems = problems_of("select team_id from marts.standings where season = $season")
    assert any("season" in p and "example" in p for p in problems), problems


def test_an_example_missing_a_parameter_or_naming_an_extra_one_is_refused():
    sql = "select team_id from marts.standings where season = $season and team_id = $team_id"
    missing = problems_of('-- example: {"season": 2026}\n' + sql)
    assert any("team_id" in p for p in missing), missing
    extra = problems_of('-- example: {"season": 2026, "team_id": 1, "x": 2}\n' + sql)
    assert any("x" in p and "example" in p for p in extra), extra


def test_an_example_that_is_not_a_json_object_is_refused():
    problems = problems_of("-- example: [1, 2]\nselect team_id from marts.standings")
    assert any("example" in p for p in problems), problems


def test_the_header_is_read_and_the_two_parameters_are_returned():
    sql = (
        '-- example: {"season": 2026, "team_id": 1}\n-- may-be-empty: no rows in 2026 yet\n\n'
        "select team_id from marts.standings where season = $season and team_id = $team_id"
    )
    report = cd.analyse("q.sql", sql)
    assert report.problems == []
    assert report.example == {"season": 2026, "team_id": 1}
    assert report.may_be_empty == "no rows in 2026 yet"
    assert report.tables == {"standings"}


def test_a_missing_queries_directory_is_not_a_failure(tmp_path):
    """Catches the gate failing before the first page exists."""
    assert cd.load_queries(tmp_path / "queries") is None


def test_an_empty_queries_directory_is_a_failure(tmp_path):
    """Catches a directory that exists, holds no query, and so checks nothing."""
    (tmp_path / "queries").mkdir()
    loaded = cd.load_queries(tmp_path / "queries")
    assert loaded is not None
    reports, problems = loaded
    assert reports == []
    assert any("no queries" in p for p in problems), problems


def exposures(tmp_path: Path, text: str = EXPOSURE_YAML) -> Path:
    path = tmp_path / "_exposures.yml"
    path.write_text(text)
    return path


def test_the_marts_read_must_equal_the_exposures(tmp_path):
    """Catches a query reading a mart the exposure does not name, and an exposure mart that
    no query reads, each named."""
    reports = [cd.analyse("a.sql", "select team_id from marts.standings")]
    problems = cd.check_exposure(reports, exposures(tmp_path))
    assert any("team_names" in p and "no query reads" in p for p in problems), problems
    reports = [
        cd.analyse("a.sql", "select team_id from marts.standings"),
        cd.analyse("b.sql", "select name from marts.team_names"),
        cd.analyse("c.sql", "select x from marts.rosters"),
    ]
    problems = cd.check_exposure(reports, exposures(tmp_path))
    assert any("rosters" in p and "exposure does not name" in p for p in problems), problems
    assert not any("team_names" in p or "standings" in p for p in problems), problems


def test_matching_marts_pass(tmp_path):
    reports = [
        cd.analyse("a.sql", "select team_id from marts.standings"),
        cd.analyse(
            "b.sql", "select a.name from marts.team_names a join marts.standings s using (team_id)"
        ),
    ]
    assert cd.check_exposure(reports, exposures(tmp_path)) == []


def test_the_extracts_own_table_is_not_a_mart(tmp_path):
    """Catches the freshness banner's query (`marts.extract_info`, R6.1) failing R4.3: the
    table is the extract's, not a mart, so no exposure names it. It still reads only `marts`."""
    reports = [
        cd.analyse("a.sql", "select team_id from marts.standings"),
        cd.analyse("b.sql", "select name from marts.team_names"),
        cd.analyse("freshness.sql", "select extracted_at from marts.extract_info"),
    ]
    assert cd.check_exposure(reports, exposures(tmp_path)) == []


def test_the_freshness_query_runs_on_the_extract(tmp_path, warehouse):
    files = {**GOOD, "freshness.sql": "select extracted_at, git_commit from marts.extract_info"}
    assert run(tmp_path, warehouse, files) == (3, [])


@pytest.fixture
def warehouse(tmp_path):
    path = tmp_path / "wh.duckdb"
    con = duckdb.connect(str(path))
    con.execute("create schema marts")
    con.execute("create table marts.team_names as select 2026 as season, 1 as team_id, 'A' as name")
    con.execute("create table marts.standings as select 2026 as season, 1 as team_id, 3 as wins")
    con.close()
    return path


def write_queries(tmp_path: Path, files: dict[str, str]) -> Path:
    directory = tmp_path / "queries"
    directory.mkdir()
    for name, sql in files.items():
        (directory / name).write_text(sql)
    return directory


def run(tmp_path, warehouse, files):
    directory = write_queries(tmp_path, files)
    return cd.check_all(warehouse, directory, exposures(tmp_path))


GOOD = {
    "names.sql": "select name from marts.team_names where season = $season order by name",
    "standings.sql": "select team_id, wins from marts.standings order by wins desc",
}
GOOD["names.sql"] = '-- example: {"season": 2026}\n' + GOOD["names.sql"]


def test_queries_that_run_pass(tmp_path, warehouse):
    checked, problems = run(tmp_path, warehouse, GOOD)
    assert problems == []
    assert checked == 2


def test_a_query_that_errors_on_the_extract_is_refused(tmp_path, warehouse):
    """Catches a query naming a column the mart lacks: the static rules cannot see that."""
    files = {**GOOD, "bad.sql": "select nope from marts.standings"}
    _, problems = run(tmp_path, warehouse, files)
    assert any(p.startswith("bad.sql: ") for p in problems), problems


def test_a_query_with_no_rows_is_refused_unless_it_says_so(tmp_path, warehouse):
    """Catches a query that runs and returns nothing, which would show an empty page."""
    empty = "select name from marts.team_names where season = 1900"
    _, problems = run(tmp_path, warehouse, {**GOOD, "empty.sql": empty})
    assert any(p.startswith("empty.sql: ") and "0 rows" in p for p in problems), problems


def test_a_query_that_says_it_may_be_empty_passes(tmp_path, warehouse):
    empty = (
        "-- may-be-empty: nothing before the season starts\n"
        "select name from marts.team_names where season = 1900"
    )
    _, problems = run(tmp_path, warehouse, {**GOOD, "empty.sql": empty})
    assert problems == []


def test_a_mart_the_warehouse_lacks_stops_the_extract(tmp_path, warehouse):
    """Catches an exposure naming a table the warehouse does not hold: the extract refuses."""
    text = EXPOSURE_YAML + "      - ref('rosters')\n"
    directory = write_queries(tmp_path, GOOD)
    _, problems = cd.check_all(warehouse, directory, exposures(tmp_path, text))
    assert any("rosters" in p for p in problems), problems


def test_main_reports_no_queries_yet_and_exits_0(tmp_path, capsys):
    code = cd.main(["--db", str(tmp_path / "none.duckdb"), "--queries-dir", str(tmp_path / "q")])
    assert code == 0
    assert capsys.readouterr().out.strip() == "no dashboard queries yet"


def test_main_summarises_and_exits_0(tmp_path, warehouse, capsys):
    directory = write_queries(tmp_path, GOOD)
    code = cd.main(
        [
            "--db",
            str(warehouse),
            "--queries-dir",
            str(directory),
            "--exposures",
            str(exposures(tmp_path)),
        ]
    )
    assert code == 0
    assert capsys.readouterr().out.strip() == "dashboard queries: 2 checked, all pass"


def test_main_lists_every_failure_and_exits_1(tmp_path, warehouse, capsys):
    files = {**GOOD, "a.sql": "select sum(wins) from marts.standings group by 1"}
    directory = write_queries(tmp_path, files)
    code = cd.main(
        [
            "--db",
            str(warehouse),
            "--queries-dir",
            str(directory),
            "--exposures",
            str(exposures(tmp_path)),
        ]
    )
    out = capsys.readouterr().out
    assert code == 1
    assert "a.sql: group by" in out and "a.sql: aggregate" in out
