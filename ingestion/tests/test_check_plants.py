"""Tests for the planted-failures harness (spec 0174 R1, R2.3-R2.5, R3, R5.3).

The pure checks take dicts, strings and counts, so they need no dbt; the changed-row check
and the materialize step run against a tiny temporary DuckDB file. The dbt runs themselves
are exercised by the gate.
"""

from pathlib import Path

import duckdb
import pytest

import check_plants as cp


def plant(**overrides):
    base = {
        "name": "p",
        "why": "a reason",
        "sql": "update t set a = 1",
        "expect": {"status": "fail", "failures": 1},
    }
    base.update(overrides)
    return base


def problems_of(*plants):
    return cp.validate_plant_file("some_test", {"plants": list(plants)})


# --- register validation (R1.1, R1.4) ---------------------------------------------------


def test_a_well_formed_file_has_no_problems():
    """Catches a false positive on the ordinary, correct case."""
    assert problems_of(plant()) == []


def test_a_plant_missing_expect_is_reported():
    """Catches a plant with nothing to compare dbt's result against."""
    p = plant()
    del p["expect"]
    problems = problems_of(p)
    assert any("expect" in x and "some_test" in x and "'p'" in x for x in problems)


@pytest.mark.parametrize("key", ["name", "why", "sql"])
def test_a_plant_missing_any_required_key_is_reported(key):
    """Catches each required key being optional by accident."""
    p = plant()
    del p[key]
    assert any(key in x for x in problems_of(p))


def test_an_unknown_key_is_reported():
    """Catches a typo (`expects`) being silently ignored."""
    assert any("surprise" in x for x in problems_of(plant(surprise=1)))


def test_an_unknown_top_level_key_is_reported():
    """Catches a misspelled `plants:` leaving the file empty and green."""
    problems = cp.validate_plant_file("t", {"plants": [plant()], "extra": 1})
    assert any("extra" in x for x in problems)


def test_a_file_without_plants_is_reported():
    """Catches an empty file standing as a plant for its test."""
    assert cp.validate_plant_file("t", {"plants": []}) != []
    assert cp.validate_plant_file("t", None) != []


def test_a_duplicate_plant_name_in_a_file_is_reported():
    """Catches two plants sharing a name, so a failure line could name either."""
    assert any("duplicate" in x for x in problems_of(plant(), plant()))


def test_a_create_table_statement_is_refused():
    """Catches a plant that builds an object instead of changing a row."""
    problems = problems_of(plant(sql="create table x as select 1"))
    assert any("INSERT, UPDATE or DELETE" in x for x in problems)


def test_two_statements_in_one_entry_are_refused():
    """Catches a second statement escaping the type check (`update ...; create table ...`)."""
    problems = problems_of(plant(sql="update t set a = 1; create table x as select 1"))
    assert any("exactly one" in x for x in problems)


def test_attach_after_an_update_is_refused():
    """Catches a plant reaching outside the copy through ATTACH."""
    assert problems_of(plant(sql="update t set a = 1; attach 'other.duckdb' as o")) != []


def test_a_statement_after_a_leading_comment_is_classified_by_its_parsed_type():
    """Catches a prefix check: a comment must neither hide a bad type nor refuse a good one."""
    assert problems_of(plant(sql="-- note\nupdate t set a = 1")) == []
    assert problems_of(plant(sql="/* update */ create table x as select 1")) != []


def test_an_empty_sql_entry_is_refused():
    """Catches an entry that parses to no statement at all."""
    assert problems_of(plant(sql="")) != []
    assert problems_of(plant(sql=[])) != []


def test_sql_may_be_a_string_or_a_list():
    """Catches either documented form being refused."""
    assert problems_of(plant(sql="delete from t where a = 1")) == []
    assert problems_of(plant(sql=["delete from t where a = 1", "insert into t values (1)"])) == []


def test_expect_pass_is_accepted():
    """Catches the `pass` form being refused (beside a plant that fails, as a file needs)."""
    assert problems_of(plant(), plant(name="q", expect="pass")) == []


def test_a_file_of_only_pass_plants_is_reported():
    """Catches a vacuous test being accounted for without ever being shown to fail (F1)."""
    problems = problems_of(plant(expect="pass"), plant(name="q", expect="pass"))
    assert any("no plant expects the test to fail or warn" in x for x in problems)


def test_a_file_with_one_fail_and_one_pass_is_not_reported():
    """Catches the rule being too strict: one fail plant is enough (F1)."""
    assert problems_of(plant(), plant(name="q", expect="pass")) == []
    assert problems_of(plant(expect={"status": "warn", "failures": 2})) == []


@pytest.mark.parametrize("value", [[], {}, "", "  ", None, 3])
@pytest.mark.parametrize("key", ["name", "why"])
def test_name_and_why_must_be_non_empty_strings(key, value):
    """Catches `name: []` crashing validation and empty text standing as a reason (F3)."""
    problems = problems_of(plant(**{key: value}))
    assert any(f"'{key}' must be a non-empty string" in x for x in problems)


def test_expect_fail_without_failures_is_refused():
    """Catches an expectation that does not pin the count."""
    assert problems_of(plant(expect={"status": "fail"})) != []


@pytest.mark.parametrize("count", [0, -1, "1", 1.5, True])
def test_a_failure_count_below_one_or_not_an_integer_is_refused(count):
    """Catches `failures: 0` (which is `pass`) and non-integers."""
    assert problems_of(plant(expect={"status": "fail", "failures": count})) != []


@pytest.mark.parametrize("expect", ["fail", {"status": "error", "failures": 1}, {"failures": 1}])
def test_other_expect_forms_are_refused(expect):
    """Catches a bare `fail`, or a status dbt reports only when the test itself broke."""
    assert problems_of(plant(expect=expect)) != []


def test_expect_warn_with_a_count_is_accepted():
    """Catches the `warn` form being refused."""
    assert problems_of(plant(expect={"status": "warn", "failures": 4})) == []


def test_materialize_must_be_a_list_of_schema_dot_name():
    """Catches a bare relation name that cannot be located."""
    assert problems_of(plant(materialize=["staging.stg_a"])) == []
    assert problems_of(plant(materialize=["stg_a"])) != []
    assert problems_of(plant(materialize="staging.stg_a")) != []


# --- _empty_in_ci.yml (R1.2, R1.4) -------------------------------------------------------


def exemption(**overrides):
    base = {"relation": "staging.stg_a", "reason": "no fixture", "link": "#178"}
    base.update(overrides)
    return base


def test_a_well_formed_exemption_file_has_no_problems():
    """Catches a false positive on the ordinary, correct case."""
    assert cp.validate_empty_file({"relations": [exemption()]}) == []


@pytest.mark.parametrize("key", ["relation", "reason", "link"])
def test_an_exemption_missing_a_key_is_reported(key):
    """Catches an exemption with no reason or no link to rest it on."""
    e = exemption()
    del e[key]
    assert any(key in x for x in cp.validate_empty_file({"relations": [e]}))


def test_an_exemption_with_an_unknown_key_or_duplicate_relation_is_reported():
    """Catches a typo and a relation exempted twice."""
    assert cp.validate_empty_file({"relations": [exemption(extra=1)]}) != []
    assert cp.validate_empty_file({"relations": [exemption(), exemption()]}) != []


def test_an_exemption_with_a_blank_reason_is_reported():
    """Catches a reason that says nothing."""
    assert cp.validate_empty_file({"relations": [exemption(reason=" ")]}) != []


# --- stale names (R1.3) ------------------------------------------------------------------


def test_a_plant_file_for_a_test_the_manifest_lacks_is_reported():
    """Catches a plant left behind after its test was renamed or removed."""
    problems = cp.stale_problems(["gone", "kept"], {"kept"}, [], {})
    assert any("gone" in x for x in problems) and not any("kept" in x for x in problems)


def test_a_singular_test_may_have_a_plant_file():
    """Catches the stale check knowing only generic tests, so a singular test's plants read
    as left behind."""
    manifest = {
        "nodes": {
            "test.p.singular": {"resource_type": "test", "name": "singular"},
            "test.p.generic": {
                "resource_type": "test",
                "name": "generic",
                "test_metadata": {"name": "not_null"},
            },
            "model.p.m": {"resource_type": "model", "name": "m"},
        }
    }
    names = cp.test_names(manifest)
    assert names == {"singular", "generic"}
    assert cp.stale_problems(["singular", "generic"], names, [], {}) == []


def test_an_exemption_for_a_relation_with_rows_is_reported():
    """Catches an exemption left behind after its relation filled."""
    problems = cp.stale_problems(
        [], set(), ["staging.a", "staging.b"], {"staging.a": 0, "staging.b": 3}
    )
    assert any("staging.b" in x for x in problems) and not any("staging.a" in x for x in problems)


def test_an_exemption_for_a_relation_no_test_reads_is_reported():
    """Catches an exemption for a relation the manifest does not test at all."""
    assert any("staging.z" in x for x in cp.stale_problems([], set(), ["staging.z"], {}))


# --- the classifier (R3.2, R3.3) ---------------------------------------------------------


@pytest.mark.parametrize(
    ("relation_rows", "admitted_rows", "expected"),
    [
        (0, 0, "needs_exemption"),
        (5, 0, "needs_plant"),
        (5, 5, "ok"),
        (5, 2, "ok"),
    ],
)
def test_the_classifier_reads_the_two_counts(relation_rows, admitted_rows, expected):
    """Catches an empty relation or a vacuous `where` passing as ordinary."""
    assert cp.classify(relation_rows, admitted_rows) == expected


def test_a_test_without_a_where_on_a_non_empty_relation_is_fine():
    """Catches a where-less test being demanded a plant (admitted rows = relation rows)."""
    assert cp.classify(7, 7) == "ok"


# --- the result judge (R2.4, R2.5) -------------------------------------------------------


@pytest.mark.parametrize(
    ("expect", "results", "ok"),
    [
        ("pass", [("pass", 0)], True),
        ("pass", [("fail", 1)], False),
        ("pass", [("warn", 2)], False),
        ({"status": "fail", "failures": 1}, [("fail", 1)], True),
        ({"status": "fail", "failures": 1}, [("fail", 2)], False),
        ({"status": "fail", "failures": 1}, [("pass", 0)], False),
        ({"status": "fail", "failures": 1}, [("warn", 1)], False),
        ({"status": "warn", "failures": 4}, [("warn", 4)], True),
        ({"status": "warn", "failures": 4}, [("fail", 4)], False),
        ({"status": "warn", "failures": 4}, [("warn", 3)], False),
    ],
)
def test_the_judge_compares_status_and_count(expect, results, ok):
    """Catches a different count, or a different status, read as success."""
    assert cp.judge(expect, results)[0] is ok


@pytest.mark.parametrize(
    "expect", ["pass", {"status": "fail", "failures": 1}, {"status": "warn", "failures": 1}]
)
def test_an_error_result_always_fails(expect):
    """Catches a broken test (error) being read as the failure the plant wanted."""
    assert cp.judge(expect, [("error", None)])[0] is False
    assert cp.judge(expect, [("error", 1)])[0] is False


@pytest.mark.parametrize("expect", ["pass", {"status": "fail", "failures": 1}])
def test_no_result_or_several_results_fail(expect):
    """Catches a --select that matched nothing, or more than the one test."""
    assert cp.judge(expect, [])[0] is False
    assert cp.judge(expect, [("pass", 0), ("pass", 0)])[0] is False


def test_the_judge_says_what_dbt_gave():
    """Catches an uninformative failure line (R2.5 prints expected and got)."""
    ok, got = cp.judge({"status": "fail", "failures": 1}, [("fail", 2)])
    assert not ok and "fail" in got and "2" in got


# --- the changed-row check (R2.3) --------------------------------------------------------


@pytest.fixture
def con(tmp_path: Path):
    connection = duckdb.connect(str(tmp_path / "tiny.duckdb"))
    connection.execute("create table t (a integer, b integer)")
    connection.execute("insert into t values (1, null), (2, 3)")
    yield connection
    connection.close()


def test_an_update_that_matches_nothing_fails(con):
    """Catches C6's silent plant: a filter no fixture row meets."""
    assert cp.run_statement(con, "update t set b = 9 where a = 99") is not None


def test_an_update_that_sets_the_values_a_row_already_has_fails(con):
    """Catches a stale `pass` plant: DuckDB counts the matched row, EXCEPT ALL does not."""
    sql = "update t set b = null where a = 1"
    assert con.execute(sql).fetchone() == (1,)  # the row count alone would say it changed
    assert cp.run_statement(con, sql) is not None


def test_an_update_that_changes_a_row_passes(con):
    """Catches a real change being refused."""
    assert cp.run_statement(con, "update t set b = 7 where a = 1") is None
    assert con.execute("select b from t where a = 1").fetchone() == (7,)


def test_an_update_leaves_no_before_image_behind(con):
    """Catches the helper table leaking into the copy dbt then reads."""
    cp.run_statement(con, "update t set b = 7 where a = 1")
    assert con.execute("select count(*) from duckdb_tables() where not internal").fetchone() == (1,)


def test_a_delete_that_matches_nothing_fails(con):
    """Catches a DELETE aimed at a row the fixtures no longer hold."""
    assert cp.run_statement(con, "delete from t where a = 99") is not None


def test_a_delete_and_an_insert_pass(con):
    """Catches a real DELETE or INSERT being refused."""
    assert cp.run_statement(con, "delete from t where a = 1") is None
    assert cp.run_statement(con, "insert into t values (5, 5)") is None
    assert con.execute("select count(*) from t").fetchone() == (2,)


def test_an_insert_returning_a_row_passes_the_check(con):
    """Catches a RETURNING row being read as a count (F2)."""
    assert cp.run_statement(con, "insert into t values (5, 5) returning a") is None
    assert con.execute("select count(*) from t").fetchone() == (3,)


def test_a_returned_zero_or_null_is_not_a_row_count(con):
    """Catches the first returned value standing in for the count (F2)."""
    assert cp.run_statement(con, "insert into t values (0, null) returning b") is None
    assert cp.run_statement(con, "delete from t where a = 0 returning a") is None


def test_a_delete_returning_that_matches_nothing_fails_without_raising(con):
    """Catches a RETURNING clause crashing the run instead of failing the plant (F2)."""
    message = cp.run_statement(con, "delete from t where a = 99 returning a, b")
    assert message is not None and "changed no row" in message


def test_a_delete_returning_that_matches_a_row_passes(con):
    """Catches a real DELETE ... RETURNING being refused (F2)."""
    assert cp.run_statement(con, "delete from t where a = 1 returning a") is None


@pytest.mark.parametrize("target", ["t(a, b)", "t (a, b)", "main.t(a, b)", "main.t (a, b)"])
def test_an_insert_with_a_column_list_finds_its_table(con, target):
    """Catches the column list being read into the table name, in either spacing (F2)."""
    assert cp.run_statement(con, f"insert into {target} values (7, 8)") is None


def test_an_insert_or_replace_finds_its_table(con):
    """Catches the `or <word>` form losing its table (F2)."""
    con.execute("create table u (a integer primary key, b integer)")
    con.execute("insert into u values (1, 1)")
    assert cp.run_statement(con, "insert or replace into u values (1, 2)") is None


def test_a_delete_leaves_no_before_image_behind(con):
    """Catches the helper table leaking after a DELETE (F2)."""
    cp.run_statement(con, "delete from t where a = 1")
    assert con.execute("select count(*) from duckdb_tables() where not internal").fetchone() == (1,)


def test_an_insert_that_inserts_nothing_fails(con):
    """Catches an INSERT ... SELECT over no rows."""
    assert cp.run_statement(con, "insert into t select * from t where a = 99") is not None


def test_a_statement_that_errors_is_a_problem_not_a_crash(con):
    """Catches one bad plant stopping the run before the others are reported."""
    assert cp.run_statement(con, "update missing set a = 1") is not None


def test_a_problem_names_the_statement(con):
    """Catches a failure that does not say which statement changed nothing (R2.3)."""
    assert "a = 99" in cp.run_statement(con, "update t set b = 9 where a = 99")


# --- materialize (R2.2) ------------------------------------------------------------------


def test_a_view_is_replaced_by_a_table_of_the_same_name_and_rows(con):
    """Catches a view that cannot take the plant, or one that loses rows on the way."""
    con.execute("create schema s")
    con.execute("create view s.v as select a, b from t")
    assert cp.materialize(con, "s.v") is None
    kind = con.execute(
        "select table_type from information_schema.tables "
        "where table_schema = 's' and table_name = 'v'"
    ).fetchall()
    assert kind == [("BASE TABLE",)]
    assert con.execute("select a, b from s.v order by a").fetchall() == [(1, None), (2, 3)]
    assert cp.run_statement(con, "update s.v set b = 5 where a = 1") is None


def test_materializing_something_that_is_not_a_view_fails(con):
    """Catches a stale `materialize` entry, now naming a table, passing quietly."""
    assert "view" in cp.materialize(con, "main.t")


def test_materializing_a_missing_relation_fails(con):
    """Catches a typo in a `materialize` entry."""
    assert cp.materialize(con, "main.nope") is not None
