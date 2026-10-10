"""Tests for the examples-against-exposures gate (spec 0013 R3.2-R3.6).

The pure checks take strings and dicts, so they need no database; one end-to-end test runs
the examples against a real temporary DuckDB file.
"""

import duckdb

import check_examples as ce


def analysis(name, *refs):
    return {
        "name": name,
        "type": "analysis",
        "owner": {"name": "N"},
        "depends_on": [f"ref('{r}')" for r in refs],
    }


def test_a_clean_pair_has_no_problems():
    """Catches a false positive on the ordinary, correct case."""
    sql = "select * from staging.stg_a join marts.fct_b using (x)"
    assert ce.check_example_exposures({"q": sql}, [analysis("q", "stg_a", "fct_b")]) == []


def test_a_relation_the_exposure_omits_is_reported():
    """Catches an example reading a model its exposure does not declare."""
    problems = ce.check_example_exposures(
        {"q": "select * from marts.fct_b, marts.fct_c"}, [analysis("q", "fct_b")]
    )
    assert any("fct_c" in p for p in problems)


def test_a_relation_the_file_does_not_read_is_reported():
    """Catches an exposure naming a model its example never reads."""
    problems = ce.check_example_exposures(
        {"q": "select * from marts.fct_b"}, [analysis("q", "fct_b", "fct_z")]
    )
    assert any("fct_z" in p for p in problems)


def test_an_example_without_an_exposure_is_reported():
    """Catches a new example file nobody declared."""
    problems = ce.check_example_exposures({"q": "select * from marts.fct_b"}, [])
    assert any("q" in p for p in problems)


def test_an_analysis_exposure_without_a_file_is_reported():
    """Catches an exposure left behind after its example was deleted."""
    problems = ce.check_example_exposures({}, [analysis("gone", "fct_b")])
    assert any("gone" in p for p in problems)


def test_a_non_ref_depends_on_is_reported_for_an_analysis():
    """Catches a source(...) entry, which the check cannot compare to the SQL."""
    exposure = analysis("q", "fct_b")
    exposure["depends_on"].append("source('mlb', 'x')")
    problems = ce.check_example_exposures({"q": "select * from marts.fct_b"}, [exposure])
    assert any("source(" in p for p in problems)


def test_a_name_in_a_string_literal_is_not_read():
    """Catches prose in a literal being taken for a relation."""
    assert ce.relations_read("select 'from marts.fct_b' as t") == set()


def test_a_name_in_a_line_comment_is_not_read():
    """Catches a commented-out relation being counted."""
    assert ce.relations_read("select 1 -- marts.fct_b\n") == set()


def test_a_name_in_a_block_comment_is_not_read():
    """Catches a multi-line block comment being counted."""
    assert ce.relations_read("/* see\n marts.fct_b */ select 1") == set()


def test_a_relation_before_a_trailing_comment_is_read():
    """Catches the comment stripper eating the real code on its line."""
    assert ce.relations_read("select * from marts.fct_b -- the mart") == {"fct_b"}


def test_dashes_in_a_literal_do_not_start_a_comment():
    """Catches `--` inside a string swallowing the rest of the line."""
    assert ce.relations_read("select '--' as dash, x from marts.fct_b") == {"fct_b"}


def test_an_apostrophe_in_a_comment_does_not_open_a_string():
    """Catches a quote inside a comment hiding the code after it."""
    assert ce.relations_read("-- it's here\nselect * from marts.fct_b") == {"fct_b"}


def test_a_doubled_quote_stays_inside_the_literal():
    """Catches an escaped quote closing the literal early."""
    assert ce.relations_read("select 'it''s marts.fct_b' from marts.fct_c") == {"fct_c"}


def test_an_example_with_no_relation_is_reported():
    """Catches an example that reads nothing the lineage could show."""
    problems = ce.check_example_exposures({"q": "select 1"}, [analysis("q")])
    assert any("no relation" in p for p in problems)


def dashboard(*refs, type_="dashboard"):
    return {
        "name": "front_office_dashboard",
        "type": type_,
        "owner": {"name": "N"},
        "depends_on": [f'ref("{r}")' for r in refs],
    }


def test_a_mart_missing_from_the_dashboard_is_reported():
    """Catches a new mart the dashboard exposure does not name."""
    problems = ce.check_dashboard({"a", "b"}, [dashboard("a")])
    assert any("b" in p for p in problems)


def test_a_dashboard_ref_that_is_not_a_mart_is_reported():
    """Catches a ref to a model that is not (or no longer) a mart."""
    problems = ce.check_dashboard({"a"}, [dashboard("a", "stg_x")])
    assert any("stg_x" in p for p in problems)


def test_no_dashboard_exposure_is_reported():
    """Catches the dashboard exposure being deleted."""
    assert ce.check_dashboard({"a"}, [analysis("q", "a")])


def test_a_dashboard_of_the_wrong_type_is_reported():
    """Catches the exposure being changed to a different type."""
    assert ce.check_dashboard({"a"}, [dashboard("a", type_="analysis")])


def test_a_complete_dashboard_has_no_problems():
    """Catches a false positive on the correct dashboard."""
    assert ce.check_dashboard({"a", "b"}, [dashboard("a", "b")]) == []


def test_an_owner_email_is_reported():
    """Catches an email address being committed in a public repo."""
    exposure = analysis("q", "a")
    exposure["owner"]["email"] = "x@example.com"
    assert any("email" in p for p in ce.check_owners([exposure]))


def test_an_owner_without_a_name_is_reported():
    """Catches an exposure dbt would accept but whose owner is blank or absent."""
    exposure = analysis("q", "a")
    exposure["owner"] = {"name": ""}
    assert ce.check_owners([exposure])
    del exposure["owner"]
    assert ce.check_owners([exposure])


def test_clean_owners_pass():
    """Catches a false positive on a name-only owner."""
    assert ce.check_owners([analysis("q", "a")]) == []


def test_exposures_load_from_nested_yaml_files(tmp_path):
    """Catches yml files without an exposures key, or in subfolders, being mishandled."""
    (tmp_path / "marts").mkdir()
    (tmp_path / "marts" / "_e.yml").write_text(
        "version: 2\nexposures:\n  - name: q\n    type: analysis\n"
    )
    (tmp_path / "_s.yml").write_text("version: 2\nmodels: []\n")
    assert [e["name"] for e in ce.load_exposures(tmp_path)] == ["q"]


def test_examples_run_against_a_real_database(tmp_path, capsys):
    """Catches a directive line breaking the run, and a bad column going unreported."""
    db = tmp_path / "t.duckdb"
    con = duckdb.connect(str(db))
    con.execute("create schema marts; create table marts.fct_b as select 1 as x")
    con.close()
    examples = tmp_path / "examples"
    examples.mkdir()
    (examples / "good.sql").write_text(".mode box\nselect x from marts.fct_b;\n")
    (examples / "bad.sql").write_text("select nope from marts.fct_b;\n")
    problems = ce.run_examples(
        db, sorted(examples.glob("*.sql")), {"good": {"rows": 1}, "bad": {"rows": 1}}
    )
    assert len(problems) == 1
    assert "bad.sql" in problems[0]
    assert "good.sql: ok, 1 rows" in capsys.readouterr().out


def test_a_missing_database_is_a_problem(tmp_path):
    """Catches a typo in --db passing silently."""
    assert ce.run_examples(tmp_path / "none.duckdb", [], {})


# Row-count expectations (spec 0117): what an example returns on the fixture warehouse.


def run_stated(tmp_path, examples, expectations):
    """Write each example (stem -> SQL) and run them in name order against an empty database."""
    db = tmp_path / "t.duckdb"
    duckdb.connect(str(db)).close()
    folder = tmp_path / "examples"
    folder.mkdir()
    for stem, sql in examples.items():
        (folder / f"{stem}.sql").write_text(sql)
    return ce.run_examples(db, sorted(folder.glob("*.sql")), expectations)


def test_an_example_returning_more_rows_than_stated_is_reported(tmp_path):
    """Catches the gate passing a filter that stopped filtering."""
    problems = run_stated(tmp_path, {"q": "select * from range(7)"}, {"q": {"rows": 5}})
    assert len(problems) == 1
    assert "q.sql" in problems[0]
    assert "5" in problems[0] and "7" in problems[0]


def test_an_example_returning_no_rows_is_reported(tmp_path):
    """Catches no rows passing as success, which is the finding behind the spec."""
    problems = run_stated(tmp_path, {"q": "select * from range(0)"}, {"q": {"rows": 1}})
    assert len(problems) == 1
    assert "q.sql" in problems[0]
    assert "1" in problems[0] and "0" in problems[0]


def test_an_example_without_an_expectation_is_reported():
    """Catches a new example added without saying what it returns."""
    problems = ce.check_expectations({"q": "select 1"}, {})
    assert any("q" in p for p in problems)


def test_an_expectation_without_an_example_is_reported():
    """Catches a stale entry left behind after its example was deleted."""
    problems = ce.check_expectations({}, {"gone": {"rows": 1}})
    assert any("gone" in p for p in problems)


def test_rows_of_zero_is_reported():
    """Catches an expectation that holds the example to returning nothing."""
    assert ce.check_expectations({"q": "select 1"}, {"q": {"rows": 0}})


def test_rows_missing_is_reported():
    """Catches an entry that states variables or columns but no row count."""
    assert ce.check_expectations({"q": "select 1"}, {"q": {"variables": {}}})


def test_rows_that_is_not_a_whole_number_is_reported():
    """Catches a quoted or text count that would never compare equal."""
    assert ce.check_expectations({"q": "select 1"}, {"q": {"rows": "many"}})


def test_an_unknown_key_is_reported():
    """Catches a misspelt key (such as `colums`) silently holding the example to nothing."""
    problems = ce.check_expectations({"q": "select 1"}, {"q": {"rows": 1, "colums": {}}})
    assert any("colums" in p for p in problems)


def test_a_failing_query_is_reported_once_with_no_count_problem(tmp_path):
    """Catches counts being compared, or the error lost, after a query fails."""
    problems = run_stated(tmp_path, {"q": "select nope from range(2)"}, {"q": {"rows": 1}})
    assert len(problems) == 1
    assert "q.sql" in problems[0]
    assert "nope" in problems[0]


def test_a_variable_does_not_leak_into_the_next_example(tmp_path):
    """Catches a variable set for one example still in force for the next."""
    reads_n = "select * from range(coalesce(getvariable('n'), 1))"
    problems = run_stated(
        tmp_path,
        {"a_first": reads_n, "b_second": reads_n},
        {"a_first": {"rows": 3, "variables": {"n": 3}}, "b_second": {"rows": 1}},
    )
    assert problems == []


def test_a_variable_does_not_leak_after_a_failed_query(tmp_path):
    """Catches variables left set when the example fails, on the failure path."""
    problems = run_stated(
        tmp_path,
        {
            "a_first": "select cast('x' as integer) from range(coalesce(getvariable('n'), 1))",
            "b_second": "select * from range(coalesce(getvariable('n'), 1))",
        },
        {"a_first": {"rows": 3, "variables": {"n": 3}}, "b_second": {"rows": 1}},
    )
    assert len(problems) == 1
    assert "a_first.sql" in problems[0]


def test_a_variable_the_file_does_not_read_is_reported():
    """Catches a misspelt variable silently leaving the default in force."""
    problems = ce.check_expectations(
        {"q": "select coalesce(getvariable('n'), 1)"},
        {"q": {"rows": 1, "variables": {"zzz": 2}}},
    )
    assert any("zzz" in p for p in problems)


def test_a_variable_read_only_in_a_comment_is_reported():
    """Catches a commented-out getvariable counting as the example reading it."""
    problems = ce.check_expectations(
        {"q": "select 1 -- getvariable('zzz')\n"},
        {"q": {"rows": 1, "variables": {"zzz": 2}}},
    )
    assert any("zzz" in p for p in problems)


def test_a_column_with_more_values_than_stated_is_reported(tmp_path):
    """Catches a join that stopped matching or over-matching with the row count unchanged."""
    sql = "select * from (values (1, 'a'), (2, null), (3, 'b')) t(id, vcol)"
    problems = run_stated(
        tmp_path, {"q": sql}, {"q": {"rows": 3, "rows_with_a_value": {"vcol": 1}}}
    )
    assert len(problems) == 1
    assert "q.sql" in problems[0]
    assert "vcol" in problems[0] and "1" in problems[0] and "2" in problems[0]


def test_a_column_the_example_does_not_return_is_reported(tmp_path):
    """Catches a renamed output column leaving its count unchecked."""
    problems = run_stated(
        tmp_path,
        {"q": "select 1 as id"},
        {"q": {"rows": 1, "rows_with_a_value": {"nope": 1}}},
    )
    assert len(problems) == 1
    assert "nope" in problems[0]


def test_an_example_as_stated_has_no_problems(tmp_path):
    """Catches a false positive on variables, rows and value counts that are all right."""
    sql = (
        "select range as at_bats, case when range = 0 then 1 end as innings_pitched "
        "from range(coalesce(getvariable('n'), 1))"
    )
    expectations = {
        "q": {
            "rows": 2,
            "variables": {"n": 2},
            "rows_with_a_value": {"at_bats": 2, "innings_pitched": 1},
        }
    }
    assert ce.check_expectations({"q": sql}, expectations) == []
    assert run_stated(tmp_path, {"q": sql}, expectations) == []
