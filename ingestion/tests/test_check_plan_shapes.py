"""Tests for the plan-shape check (spec 0156 R4, ADR 0102; spec 0134, ADR 0106).

The pure parts take hand-written manifest nodes and plan JSON, so they need no dbt and no
real data. The explain of the compiled SQL against the fixture warehouse is the gate's.
The payload check is also tested on plans DuckDB makes of SQL over an in-memory table with
a JSON `payload` column: the same plans as over a capture view (spec 0134, C7).
"""

import datetime
import json

import duckdb
import pytest

import check_plan_shapes as cps


def model(raw_code="select 1", parents=(), materialized="view"):
    return {
        "resource_type": "model",
        "name": "m",
        "raw_code": raw_code,
        "depends_on": {"nodes": list(parents)},
        "config": {"materialized": materialized},
    }


def dbt_test(parents=()):
    return {
        "resource_type": "test",
        "name": "t",
        "raw_code": "select 1",
        "depends_on": {"nodes": list(parents)},
        "config": {"materialized": "test"},
    }


STRUCTURED = "{{ fo_captures('mlb', 'boxscore', structure) }}"
PLAIN = "{{ fo_captures('mlb', 'players') }}"


# --- heavy views (R4.1) ------------------------------------------------------------------


def test_three_argument_fo_captures_is_heavy():
    """Catches a structured capture view being missed."""
    nodes = {"model.p.v": model(STRUCTURED)}
    assert cps.heavy_views(nodes) == {"model.p.v": "boxscore"}


def test_two_argument_fo_captures_is_not_heavy():
    """Catches a small endpoint's view being treated as heavy."""
    assert cps.heavy_views({"model.p.v": model(PLAIN)}) == {}


def test_a_multiline_call_with_double_quotes_is_heavy():
    """Catches the match depending on one line or on single quotes."""
    code = '{{ fo_captures(\n  "espn",\n  "roster",\n  structure\n) }}'
    assert cps.heavy_views({"model.p.v": model(code)}) == {"model.p.v": "roster"}


def test_a_model_without_fo_captures_is_not_heavy():
    """Catches an ordinary model, or one with no raw_code, being read as heavy."""
    nodes = {"model.p.a": model("select 1"), "model.p.b": {"resource_type": "model"}}
    assert cps.heavy_views(nodes) == {}


# --- readers (R4.1) ----------------------------------------------------------------------


def chain(middle_materialized):
    return {
        "model.p.heavy": model(STRUCTURED),
        "model.p.mid": model(parents=["model.p.heavy"], materialized=middle_materialized),
        "model.p.top": model(parents=["model.p.mid"], materialized="table"),
        "test.p.t": dbt_test(["model.p.mid"]),
    }


def test_a_reader_through_a_view_is_found():
    """Catches a model reaching a heavy view through a view being missed."""
    nodes = chain("view")
    found = cps.readers(nodes, cps.heavy_views(nodes))
    assert found == {
        "model.p.mid": frozenset({"boxscore"}),
        "model.p.top": frozenset({"boxscore"}),
        "test.p.t": frozenset({"boxscore"}),
    }


def test_a_reader_through_an_ephemeral_is_found():
    """Catches an ephemeral model stopping the walk."""
    nodes = chain("ephemeral")
    assert "model.p.top" in cps.readers(nodes, cps.heavy_views(nodes))


def test_a_model_behind_a_table_is_not_a_reader():
    """Catches a table in between being walked through: it was parsed when it was built."""
    nodes = chain("table")
    found = cps.readers(nodes, cps.heavy_views(nodes))
    assert set(found) == {"model.p.mid"}  # the table parses; its child and test only read it


def test_the_heavy_view_itself_is_not_a_reader():
    """Catches a capture view being checked as its own reader."""
    nodes = chain("view")
    assert "model.p.heavy" not in cps.readers(nodes, cps.heavy_views(nodes))


def test_readers_collect_every_endpoint_reached():
    """Catches a node reading two heavy views being credited with one."""
    nodes = {
        "model.p.a": model(STRUCTURED),
        "model.p.b": model("{{ fo_captures('espn', 'roster', structure) }}"),
        "model.p.c": model(parents=["model.p.a", "model.p.b", "model.p.small"]),
        "model.p.small": model(PLAIN),
    }
    found = cps.readers(nodes, cps.heavy_views(nodes))
    assert found == {"model.p.c": frozenset({"boxscore", "roster"})}


# --- reading a plan (R4.2) ---------------------------------------------------------------


def scan(endpoint, filters=None):
    text = f"endpoint='{endpoint}'"
    return {
        "name": "SEQ_SCAN",
        "children": [],
        "extra_info": {"Table": "captures", "Filters": text if filters is None else filters},
    }


def read_json():
    return {"name": "READ_JSON", "children": [], "extra_info": {}}


def join_of(operator, *endpoints, reads=True):
    below = [scan(e) for e in endpoints] + ([read_json()] if reads else [])
    return {
        "name": operator,
        "children": [{"name": "HASH_JOIN", "children": below, "extra_info": {}}],
        "extra_info": {},
    }


def plan_of(*operators):
    return [{"name": "PROJECTION", "children": list(operators), "extra_info": {}}]


HEAVY = {"boxscore", "roster", "matchup_days"}


def test_a_delim_join_over_a_heavy_read_is_found():
    """Catches a non-streamed cross join unnest over a heavy parse passing."""
    plan = plan_of(join_of("LEFT_DELIM_JOIN", "roster"))
    assert cps.gathering(plan, HEAVY) == [("delim_join", ("roster",))]


def test_a_cte_over_a_heavy_read_is_found():
    """Catches a materialized CTE over a heavy parse passing."""
    plan = plan_of(join_of("CTE", "boxscore"))
    assert cps.gathering(plan, HEAVY) == [("cte", ("boxscore",))]


def test_a_gathering_operator_over_a_small_endpoint_is_not_found():
    """Catches a delim join over `settings` being held against the model."""
    plan = plan_of(join_of("DELIM_JOIN", "settings"))
    assert cps.gathering(plan, HEAVY) == []


def test_a_captures_scan_without_a_file_read_is_not_found():
    """Catches the manifest-only scan of raw.captures counting as a parse."""
    plan = plan_of(join_of("CTE", "boxscore", reads=False))
    assert cps.gathering(plan, HEAVY) == []


def test_a_cte_of_manifest_rows_beside_a_parse_is_not_found():
    """Catches a CTE judged by the query that reads it, not by what it holds.

    A CTE's first child is its definition, the second the rest of the query. Here the CTE
    holds manifest rows only, and the parse is in the query that reads it.
    """
    definition = {"name": "HASH_JOIN", "children": [scan("matchup_days")], "extra_info": {}}
    rest = {"name": "HASH_JOIN", "children": [scan("matchup_days"), read_json()], "extra_info": {}}
    plan = plan_of({"name": "CTE", "children": [definition, rest], "extra_info": {}})
    assert cps.gathering(plan, HEAVY) == []


def test_a_cte_holding_a_parse_is_found_whatever_reads_it():
    """Catches the CTE rule above letting a materialized parse through."""
    definition = {
        "name": "HASH_JOIN",
        "children": [scan("boxscore"), read_json()],
        "extra_info": {},
    }
    rest = {"name": "PROJECTION", "children": [], "extra_info": {}}
    plan = plan_of({"name": "CTE", "children": [definition, rest], "extra_info": {}})
    assert cps.gathering(plan, HEAVY) == [("cte", ("boxscore",))]


def test_filters_as_a_list_are_read():
    """Catches the list form of Filters being ignored."""
    plan = plan_of(
        {
            "name": "LEFT_DELIM_JOIN",
            "children": [
                read_json(),
                scan("matchup_days", ["source='espn'", "endpoint='matchup_days'"]),
            ],
            "extra_info": {},
        }
    )
    assert cps.gathering(plan, HEAVY) == [("delim_join", ("matchup_days",))]


def test_filters_as_a_string_are_read():
    """Catches the string form of Filters being ignored."""
    plan = plan_of(
        {
            "name": "LEFT_DELIM_JOIN",
            "children": [read_json(), scan("x", "endpoint='boxscore'")],
            "extra_info": {},
        }
    )
    assert cps.gathering(plan, HEAVY) == [("delim_join", ("boxscore",))]


def test_a_scan_of_another_table_is_not_an_endpoint():
    """Catches an endpoint filter on some other table being read as a capture."""
    other = scan("boxscore")
    other["extra_info"]["Table"] = "games"
    plan = plan_of({"name": "CTE", "children": [read_json(), other], "extra_info": {}})
    assert cps.gathering(plan, HEAVY) == []


def test_only_the_heavy_endpoints_of_an_operator_are_returned_sorted():
    """Catches a small endpoint sharing an operator with a heavy one being listed."""
    plan = plan_of(join_of("DELIM_JOIN", "settings", "roster", "boxscore"))
    assert cps.gathering(plan, HEAVY) == [("delim_join", ("boxscore", "roster"))]


def test_a_plan_without_a_gathering_operator_finds_nothing():
    """Catches an ordinary hash join being counted."""
    plan = plan_of({"name": "HASH_JOIN", "children": [read_json(), scan("roster")]})
    assert cps.gathering(plan, HEAVY) == []


# --- the register (R4.3) -----------------------------------------------------------------


def entry(**overrides):
    base = {
        "node": "stg_a",
        "operator": "cte",
        "endpoint": "boxscore",
        "reason": "one read for both sides",
        "link": "ADR 0102",
        "measured": {
            "threads": 4,
            "gb_2026": 0.5,
            "gb_all_seasons": 0.75,
            "on": datetime.date(2026, 10, 25),
        },
    }
    base.update(overrides)
    return base


def register_problems(*entries):
    return cps.validate_register({"entries": list(entries)})


def test_a_well_formed_register_has_no_problems():
    """Catches a false positive on the ordinary, correct case."""
    assert register_problems(entry(), entry(node="stg_b")) == []


def test_a_date_written_as_a_string_is_accepted():
    """Catches a quoted date being refused."""
    assert register_problems(entry(measured={**entry()["measured"], "on": "2026-10-25"})) == []


@pytest.mark.parametrize("key", ["node", "operator", "endpoint", "reason", "link", "measured"])
def test_an_entry_missing_a_key_is_reported(key):
    """Catches a required key being optional by accident."""
    e = entry()
    del e[key]
    assert any(key in x for x in register_problems(e))


@pytest.mark.parametrize("key", ["threads", "gb_2026", "gb_all_seasons", "on"])
def test_a_measured_block_missing_a_key_is_reported(key):
    """Catches a register entry with no measurement to rest on."""
    measured = dict(entry()["measured"])
    del measured[key]
    assert any(key in x for x in register_problems(entry(measured=measured)))


def test_an_unknown_key_is_reported():
    """Catches a typo being silently ignored."""
    assert any("surprise" in x for x in register_problems(entry(surprise=1)))


def test_an_unknown_operator_is_reported():
    """Catches an operator the check never reports being registered."""
    assert any("operator" in x for x in register_problems(entry(operator="hash_join")))


@pytest.mark.parametrize("link", ["#178", "see the ADR", "ADR 102", ""])
def test_a_link_that_is_not_an_adr_is_reported(link):
    """Catches a reason with no decision record behind it."""
    assert any("link" in x for x in register_problems(entry(link=link)))


@pytest.mark.parametrize(
    "measured",
    [
        {"threads": 0, "gb_2026": 0.5, "gb_all_seasons": 0.75, "on": "2026-10-25"},
        {"threads": True, "gb_2026": 0.5, "gb_all_seasons": 0.75, "on": "2026-10-25"},
        {"threads": 4, "gb_2026": "0.5", "gb_all_seasons": 0.75, "on": "2026-10-25"},
        {"threads": 4, "gb_2026": 0.5, "gb_all_seasons": -1, "on": "2026-10-25"},
        {"threads": 4, "gb_2026": 0.5, "gb_all_seasons": 0.75, "on": "last week"},
        {"threads": 4, "gb_2026": 0.5, "gb_all_seasons": 0.75, "on": "2026-13-45"},
        "0.5 GB",
    ],
)
def test_invalid_measurements_are_reported(measured):
    """Catches a measurement that is not a thread count, sizes and a date."""
    assert register_problems(entry(measured=measured)) != []


def test_a_blank_reason_is_reported():
    """Catches a reason that says nothing."""
    assert any("reason" in x for x in register_problems(entry(reason=" ")))


def test_a_duplicate_entry_is_reported():
    """Catches one node, operator and endpoint registered twice."""
    assert any("duplicate" in x for x in register_problems(entry(), entry()))


def test_the_same_node_with_another_endpoint_is_not_a_duplicate():
    """Catches the duplicate check keying on the node alone."""
    assert register_problems(entry(), entry(endpoint="roster")) == []


@pytest.mark.parametrize("content", [None, [], {"entries": {}}, {"rows": []}, {"entries": [3]}])
def test_a_malformed_file_is_reported_not_a_crash(content):
    """Catches a wrong top-level shape raising instead of reporting."""
    assert cps.validate_register(content) != []


# --- judging (R4.2, R4.4, R4.6) ----------------------------------------------------------


def test_an_unregistered_operator_is_a_problem_naming_all_three():
    """Catches a new gathering operator passing the gate (R4.2)."""
    out = cps.problems({"stg_a": [("cte", "boxscore")]}, [], {"stg_a"})
    assert len(out) == 1 and all(w in out[0] for w in ("stg_a", "cte", "boxscore"))


def test_a_registered_operator_is_no_problem():
    """Catches a registered, exempt shape failing the gate."""
    assert cps.problems({"stg_a": [("cte", "boxscore")]}, [entry()], {"stg_a"}) == []


def test_a_registration_does_not_cover_another_operator_or_endpoint():
    """Catches the register matching on the node alone."""
    found = {"stg_a": [("delim_join", "boxscore"), ("cte", "roster")]}
    assert len(cps.problems(found, [entry()], {"stg_a"})) == 3  # two new, one stale


def test_a_stale_entry_is_a_problem():
    """Catches an entry outliving the operator it exempted (R4.4)."""
    out = cps.problems({}, [entry()], {"stg_a"})
    assert len(out) == 1 and "stg_a" in out[0] and "cte" in out[0] and "boxscore" in out[0]


def test_an_entry_for_a_node_that_is_not_a_reader_is_a_problem():
    """Catches an entry naming a renamed or removed node (R4.4)."""
    out = cps.problems({}, [entry(node="gone")], {"stg_a"})
    assert len(out) == 1 and "gone" in out[0] and "no model or test" in out[0]


def test_every_problem_is_returned():
    """Catches the check stopping at the first problem (R4.6)."""
    found = {"stg_a": [("cte", "boxscore")], "stg_b": [("delim_join", "roster")]}
    register = [entry(node="stg_c"), entry(node="gone")]
    out = cps.problems(found, register, {"stg_a", "stg_b", "stg_c"})
    assert len(out) == 4
    assert [n for n in ("stg_a", "stg_b", "stg_c", "gone") if any(n in x for x in out)] == [
        "stg_a",
        "stg_b",
        "stg_c",
        "gone",
    ]


def test_a_repeated_operator_in_one_plan_is_one_problem():
    """Catches the same shape twice in a plan reporting twice."""
    found = {"stg_a": [("cte", "boxscore"), ("cte", "boxscore")]}
    assert len(cps.problems(found, [], {"stg_a"})) == 1


# --- every heavy endpoint has CI captures (pre-PR review F1) -------------------------------


def test_a_heavy_endpoint_without_ci_captures_is_a_problem():
    """Catches the readers of an endpoint CI holds nothing of passing unchecked."""
    found = cps.uncovered({"boxscore", "schedule"}, {"boxscore", "settings"})
    assert len(found) == 1
    assert found[0].startswith("schedule:")


def test_every_heavy_endpoint_with_ci_captures_is_no_problem():
    """Catches a false positive when every heavy endpoint has a capture."""
    assert cps.uncovered({"boxscore", "roster"}, {"boxscore", "roster", "settings"}) == []


# --- payload views (spec 0134 R1.1, R1.2) ------------------------------------------------


def test_two_argument_fo_captures_is_a_payload_view():
    """Catches a small endpoint's view, the one with a payload column, being missed."""
    nodes = {"model.p.v": model(PLAIN)}
    assert cps.payload_views(nodes) == {"model.p.v": ("mlb", "players")}


def test_three_argument_fo_captures_is_not_a_payload_view():
    """Catches a heavy view being counted as a payload view too."""
    nodes = {"model.p.v": model(STRUCTURED)}
    assert cps.payload_views(nodes) == {}
    assert cps.heavy_views(nodes) == {"model.p.v": "boxscore"}


def test_a_multiline_double_quoted_two_argument_call_is_a_payload_view():
    """Catches the payload match depending on one line or on single quotes."""
    code = '{{ fo_captures(\n  "espn",\n  "teams"\n) }}'
    assert cps.payload_views({"model.p.v": model(code)}) == {"model.p.v": ("espn", "teams")}


def test_an_explicit_none_structure_is_a_payload_view_not_a_heavy_one():
    """Catches `fo_captures(..., none)`, which keeps its payload column, being read as heavy."""
    nodes = {"model.p.v": model("{{ fo_captures('espn', 'teams', none) }}")}
    assert cps.payload_views(nodes) == {"model.p.v": ("espn", "teams")}
    assert cps.heavy_views(nodes) == {}


def test_a_multiline_none_structure_with_spaces_is_a_payload_view():
    """Catches the none exemption depending on one line or on tight spacing."""
    code = "{{ fo_captures(\n  'espn',\n  'teams',\n  none  \n) }}"
    nodes = {"model.p.v": model(code)}
    assert cps.payload_views(nodes) == {"model.p.v": ("espn", "teams")}
    assert cps.heavy_views(nodes) == {}


def test_a_keyword_none_structure_is_a_payload_view_not_a_heavy_one():
    """Catches `structure=none`, spaced or across lines, being read as a heavy declaration."""
    for code in (
        "{{ fo_captures('espn', 'teams', structure=none) }}",
        "{{ fo_captures(\n  'espn',\n  'teams',\n  structure = none\n) }}",
    ):
        nodes = {"model.p.v": model(code)}
        assert cps.payload_views(nodes) == {"model.p.v": ("espn", "teams")}
        assert cps.heavy_views(nodes) == {}


def test_a_keyword_real_structure_is_heavy_not_a_payload_view():
    """Catches the keyword form hiding a real declaration from the heavy check."""
    nodes = {"model.p.v": model("{{ fo_captures('espn', 'teams', structure=my_structure) }}")}
    assert cps.heavy_views(nodes) == {"model.p.v": "teams"}
    assert cps.payload_views(nodes) == {}


def test_no_payload_view_is_a_problem_naming_the_adr():
    """Catches the payload check going quiet when no view is found to check."""
    problems = cps.no_payload_views_problem({})
    assert len(problems) == 1
    assert "ADR 0106" in problems[0]


def test_one_payload_view_is_no_missing_view_problem():
    """Catches the missing-view problem being raised when a payload view exists."""
    assert cps.no_payload_views_problem({"model.p.v": ("espn", "teams")}) == []


def test_a_structure_named_like_none_is_still_heavy():
    """Catches the none exemption matching a variable that merely starts with none."""
    nodes = {"model.p.v": model("{{ fo_captures('espn', 'teams', none_structure) }}")}
    assert cps.heavy_views(nodes) == {"model.p.v": "teams"}
    assert cps.payload_views(nodes) == {}


def _probe_nodes():
    return {
        "model.p.a": {"name": "a", "alias": "stg_a", "relation_name": '"ci"."raw"."stg_a"'},
        "model.p.b": {"name": "b", "relation_name": '"ci"."raw"."b"'},
    }


def test_probe_relation_is_the_first_view_with_a_payload_column():
    """Catches the probe relation being any view but the first one that has a payload."""
    payload = {"model.p.a": ("s", "x"), "model.p.b": ("s", "y")}
    columns = {"stg_a": ["payload"], "b": ["payload"]}
    assert cps.probe_relation(payload, _probe_nodes(), columns) == '"ci"."raw"."stg_a"'


def test_probe_relation_skips_a_first_view_without_a_payload_column():
    """Catches the probe running over a view with no payload column, which cannot be explained."""
    payload = {"model.p.a": ("s", "x"), "model.p.b": ("s", "y")}
    columns = {"stg_a": ["file_path"], "b": ["payload"]}
    assert cps.probe_relation(payload, _probe_nodes(), columns) == '"ci"."raw"."b"'


def test_probe_relation_is_none_when_no_view_has_a_payload_column():
    """Catches a probe being chosen when there is nothing it can run over."""
    payload = {"model.p.a": ("s", "x"), "model.p.b": ("s", "y")}
    columns = {"stg_a": ["file_path"], "b": []}
    assert cps.probe_relation(payload, _probe_nodes(), columns) is None


def test_a_model_without_fo_captures_is_not_a_payload_view():
    """Catches an ordinary model, or one with no raw_code, being read as a payload view."""
    nodes = {"model.p.a": model("select 1"), "model.p.b": {"resource_type": "model"}}
    assert cps.payload_views(nodes) == {}


def payload_endpoints(nodes):
    return {u: e for u, (_, e) in cps.payload_views(nodes).items()}


def test_a_reader_through_a_view_of_a_payload_view_is_found():
    """Catches readers of a payload view being found differently from the heavy ones."""
    nodes = {
        "model.p.small": model(PLAIN),
        "model.p.mid": model(parents=["model.p.small"], materialized="view"),
        "model.p.top": model(parents=["model.p.mid"], materialized="table"),
    }
    found = cps.readers(nodes, payload_endpoints(nodes))
    assert found == {
        "model.p.mid": frozenset({"players"}),
        "model.p.top": frozenset({"players"}),
    }


def test_a_model_behind_a_table_is_not_a_reader_of_a_payload_view():
    """Catches a table in between being walked through for a payload view."""
    nodes = {
        "model.p.small": model(PLAIN),
        "model.p.mid": model(parents=["model.p.small"], materialized="table"),
        "model.p.top": model(parents=["model.p.mid"], materialized="view"),
    }
    assert set(cps.readers(nodes, payload_endpoints(nodes))) == {"model.p.mid"}


# --- coverage and the payload column (R1.3, R1.4) ------------------------------------------


def test_a_payload_pair_without_captures_is_a_problem_naming_it():
    """Catches the check silently judging nothing for an endpoint CI holds no capture of."""
    found = cps.uncovered_pairs({("mlb", "players"), ("espn", "teams")}, {("mlb", "players")})
    assert len(found) == 1 and "espn/teams" in found[0]


def test_another_sources_capture_does_not_cover_an_endpoint_of_the_same_name():
    """Catches mlb/players covering a future espn/players."""
    found = cps.uncovered_pairs({("espn", "players")}, {("mlb", "players")})
    assert len(found) == 1 and "espn/players" in found[0]


def test_every_payload_pair_with_captures_is_no_problem():
    """Catches a false positive when every payload endpoint has a capture."""
    pairs = {("mlb", "players"), ("espn", "teams")}
    assert cps.uncovered_pairs(pairs, pairs | {("mlb", "schedule")}) == []


def test_a_payload_view_without_a_payload_column_is_a_problem_naming_it():
    """Catches the name the check keys on going stale without the check noticing."""
    columns = {"stg_raw__a": ["fetched_at", "payload"], "stg_raw__b": ["fetched_at", "body"]}
    found = cps.missing_payload_column(columns)
    assert len(found) == 1 and "stg_raw__b" in found[0]


def test_payload_views_with_the_column_are_no_problem():
    """Catches a false positive on a view that has its payload column."""
    assert cps.missing_payload_column({"stg_raw__a": ["payload"]}) == []


# --- reading a plan: projections, unnests, joins, emits (R2.2, R2.3) -----------------------


def op(name, *children, **info):
    return {"name": name, "children": list(children), "extra_info": info}


def test_projections_as_a_string_are_a_list():
    """Catches the one-column case, which the plan gives as a string, going unseen."""
    assert cps._projections(op("PROJECTION", Projections="payload")) == ["payload"]


def test_projections_as_a_list_are_read():
    """Catches the list form of Projections being ignored."""
    projections = ["id", "payload"]
    assert cps._projections(op("PROJECTION", Projections=projections)) == projections


def test_no_projections_is_an_empty_list():
    """Catches an operator without Projections raising or returning None."""
    assert cps._projections(op("FILTER")) == []
    assert cps._projections({"name": "FILTER"}) == []


def test_unnest_and_the_inout_unnest_function_are_unnests():
    """Catches either way DuckDB plans an unnest being missed."""
    assert cps._is_unnest(op("UNNEST"))
    assert cps._is_unnest(op("INOUT_FUNCTION", Name="unnest"))


def test_another_inout_function_is_not_an_unnest():
    """Catches every INOUT_FUNCTION being read as an unnest."""
    assert not cps._is_unnest(op("INOUT_FUNCTION", Name="generate_series"))
    assert not cps._is_unnest(op("PROJECTION"))


@pytest.mark.parametrize("name", ["CROSS_PRODUCT", "HASH_JOIN", "BLOCKWISE_NL_JOIN"])
def test_a_cross_product_or_join_is_a_join(name):
    """Catches a join shape that repeats its input being missed."""
    assert cps._is_join(op(name))


@pytest.mark.parametrize("name", ["LEFT_DELIM_JOIN", "RIGHT_DELIM_JOIN", "DELIM_JOIN", "FILTER"])
def test_a_delim_join_or_a_filter_is_not_a_join(name):
    """Catches a delim join, which ADR 0102's check judges, being read as a join here."""
    assert not cps._is_join(op(name))


def test_an_operator_with_projections_emits_them():
    """Catches an operator's own Projections being replaced by its children's."""
    below = op("PROJECTION", Projections=["payload"])
    assert cps._emits(op("PROJECTION", below, Projections=["id"])) == ["id"]


def test_an_operator_without_projections_emits_what_its_child_emits():
    """Catches a carried column hidden behind a FILTER."""
    plan = op("FILTER", op("PROJECTION", Projections=["id", "payload"]))
    assert cps._emits(plan) == ["id", "payload"]


def test_a_join_emits_both_sides():
    """Catches a join emitting only its first child."""
    plan = op(
        "CROSS_PRODUCT",
        op("PROJECTION", Projections="payload"),
        op("UNNEST", Projections="e"),
    )
    assert cps._emits(plan) == ["payload", "e"]


@pytest.mark.parametrize("join_type", ["SEMI", "ANTI", "MARK", "RIGHT_SEMI", "RIGHT_ANTI", "semi"])
def test_a_semi_anti_or_mark_join_emits_its_first_child_only(join_type):
    """Catches the filtering side of a semi join being counted as carried."""
    plan = op(
        "HASH_JOIN",
        op("PROJECTION", Projections="id"),
        op("PROJECTION", Projections="payload"),
        **{"Join Type": join_type},
    )
    assert cps._emits(plan) == ["id"]


def test_an_inner_join_type_emits_both_sides():
    """Catches the Join Type check treating every typed join as a semi join."""
    plan = op(
        "HASH_JOIN",
        op("PROJECTION", Projections="id"),
        op("PROJECTION", Projections="payload"),
        **{"Join Type": "INNER"},
    )
    assert cps._emits(plan) == ["id", "payload"]


# --- payload_carries on hand-written plans (R2.1) ------------------------------------------


def test_an_unnest_fed_a_payload_is_flagged():
    """Catches the select-list unnest beside a payload field passing."""
    plan = [op("UNNEST", op("PROJECTION", Projections="payload"))]
    assert cps.payload_carries(plan) == ["UNNEST"]


def test_an_unnest_fed_a_payload_among_other_columns_is_flagged():
    """Catches a payload in a list of projections being missed."""
    plan = [op("UNNEST", op("PROJECTION", Projections=["id", "payload", "fetched_at"]))]
    assert cps.payload_carries(plan) == ["UNNEST"]


def test_an_inout_unnest_fed_a_payload_is_flagged_by_its_name():
    """Catches the INOUT_FUNCTION form being reported as something else."""
    plan = [op("INOUT_FUNCTION", op("PROJECTION", Projections="payload"), Name="unnest")]
    assert cps.payload_carries(plan) == ["INOUT_FUNCTION"]


def test_a_column_named_payload_size_is_not_a_payload():
    """Catches the word boundary matching payload_size, a small column, as the payload."""
    plan = [op("UNNEST", op("PROJECTION", Projections=["payload_size", "my_payload"]))]
    assert cps.payload_carries(plan) == []


def test_an_expression_over_payload_is_a_payload():
    """Catches json_extract(payload, ...) being missed: the whole value is read."""
    plan = [op("UNNEST", op("PROJECTION", Projections="json_extract(payload, '$.teams[*]')"))]
    assert cps.payload_carries(plan) == ["UNNEST"]


def test_an_unnest_fed_no_payload_is_not_flagged():
    """Catches the header form, whose unnest sees small columns, being flagged."""
    plan = [op("UNNEST", op("PROJECTION", Projections=["id", "tl"]))]
    assert cps.payload_carries(plan) == []


def test_a_payload_nowhere_near_an_unnest_is_not_flagged():
    """Catches a payload read by an ordinary projection being flagged."""
    plan = [op("PROJECTION", op("SEQ_SCAN", Projections="payload"), Projections="payload")]
    assert cps.payload_carries(plan) == []


def test_a_join_repeats_the_side_without_the_unnest():
    """Catches a cross product carrying a payload past the unnest it sits over."""
    plan = [
        op(
            "CROSS_PRODUCT",
            op("PROJECTION", Projections="payload"),
            op("UNNEST", op("PROJECTION", Projections="l")),
        )
    ]
    assert cps.payload_carries(plan) == ["CROSS_PRODUCT"]


def test_a_filter_between_a_join_and_its_unnest_is_followed():
    """Catches `where e > 1` hiding the unnest from the join (C12)."""
    plan = [
        op(
            "CROSS_PRODUCT",
            op("PROJECTION", Projections="payload"),
            op("FILTER", op("UNNEST", op("PROJECTION", Projections="l"))),
        )
    ]
    assert cps.payload_carries(plan) == ["CROSS_PRODUCT"]


def test_a_join_whose_other_side_has_no_payload_is_not_flagged():
    """Catches a constant list beside small columns being flagged."""
    plan = [
        op(
            "CROSS_PRODUCT",
            op("PROJECTION", Projections="id"),
            op("UNNEST", op("PROJECTION", Projections="l")),
        )
    ]
    assert cps.payload_carries(plan) == []


def test_a_join_with_an_unnest_under_every_child_has_no_inputs():
    """Catches a payload under an unnest being charged to the join above it."""
    plan = [
        op(
            "CROSS_PRODUCT",
            op("FILTER", op("UNNEST", op("PROJECTION", Projections="l")), Projections="payload"),
            op("UNNEST", op("PROJECTION", Projections="m")),
        )
    ]
    assert cps.payload_carries(plan) == []


def test_a_join_with_no_unnest_beneath_is_not_flagged():
    """Catches an ordinary join that carries a payload being flagged."""
    plan = [
        op(
            "HASH_JOIN",
            op("PROJECTION", Projections="payload"),
            op("PROJECTION", Projections="id"),
        )
    ]
    assert cps.payload_carries(plan) == []


def test_a_semi_join_is_not_a_multiplying_operator():
    """Catches `where x in (select unnest(...))` being flagged: a semi join repeats nothing."""
    plan = [
        op(
            "HASH_JOIN",
            op("PROJECTION", Projections="payload"),
            op("UNNEST", op("PROJECTION", Projections="l")),
            **{"Join Type": "SEMI"},
        )
    ]
    assert cps.payload_carries(plan) == []


def test_a_delim_join_is_not_treated_as_a_join():
    """Catches ADR 0102's operator being judged by this check as well."""
    plan = [
        op(
            "LEFT_DELIM_JOIN",
            op("PROJECTION", Projections="payload"),
            op("UNNEST", op("PROJECTION", Projections="l")),
        )
    ]
    assert cps.payload_carries(plan) == []


def test_an_operator_repeated_in_one_plan_is_named_once_and_sorted():
    """Catches a shape twice in a plan reporting twice, or an unstable order."""
    carrying = op("PROJECTION", Projections="payload")
    plan = [
        op("PROJECTION", op("UNNEST", carrying), op("UNNEST", carrying)),
        op("CROSS_PRODUCT", carrying, op("UNNEST", op("PROJECTION", Projections="l"))),
    ]
    assert cps.payload_carries(plan) == ["CROSS_PRODUCT", "UNNEST"]


# --- judging a payload carry (R2.6, R2.7) ---------------------------------------------------


def test_a_carry_is_a_problem_naming_the_node_operator_and_endpoints():
    """Catches a payload carry passing, or a message that says nothing about where."""
    out = cps.payload_problems({"stg_a": ["UNNEST"]}, {"stg_a": ["settings", "teams"]})
    assert out == [
        "stg_a: UNNEST is fed a payload (settings, teams); compute what it needs in a CTE "
        "before the unnest (AGENTS.md rule 1)"
    ]


def test_every_carry_is_a_problem_sorted_by_node_and_operator():
    """Catches the check stopping at the first problem, or an unstable order."""
    found = {"stg_b": ["UNNEST"], "stg_a": ["UNNEST", "CROSS_PRODUCT"]}
    endpoints = {"stg_a": ["teams"], "stg_b": ["players"]}
    out = cps.payload_problems(found, endpoints)
    assert [line.split(" is fed")[0] for line in out] == [
        "stg_a: CROSS_PRODUCT",
        "stg_a: UNNEST",
        "stg_b: UNNEST",
    ]


def test_no_carries_is_no_problem():
    """Catches a false positive when nothing carries a payload."""
    assert cps.payload_problems({}, {}) == []


def test_a_payload_entry_in_the_register_is_rejected():
    """Catches an exemption for a payload carry creeping in through the register (R2.4)."""
    assert any("operator" in x for x in register_problems(entry(operator="unnest_payload")))


def test_the_solver_is_registered_on_a_fresh_connection():
    """Catches the optimal-lineup node becoming unexplainable after a signature change (R2.5)."""
    con = duckdb.connect()
    try:
        cps.register_functions(con)
        rows = con.execute(
            "select function_name from duckdb_functions() "
            "where function_name = 'solve_lineup_period'"
        ).fetchall()
    finally:
        con.close()
    assert rows


# --- the probes (R3.1) ----------------------------------------------------------------------


def test_there_are_three_probes_each_over_a_relation():
    """Catches a probe being dropped, or one that cannot be pointed at a view."""
    assert len(cps.PROBES) == 3
    assert len({name for name, _ in cps.PROBES}) == 3
    assert all("{relation}" in template for _, template in cps.PROBES)


def test_a_probe_that_finds_nothing_is_a_problem_naming_it():
    """Catches a plan-format change switching the check off quietly."""
    results = {name: ["UNNEST"] for name, _ in cps.PROBES}
    first = cps.PROBES[0][0]
    results[first] = []
    out = cps.probe_problems(results)
    assert len(out) == 1 and first in out[0] and "plan format" in out[0]


def test_every_probe_finding_nothing_is_three_problems():
    """Catches the probes stopping at the first failure."""
    assert len(cps.probe_problems({name: [] for name, _ in cps.PROBES})) == 3


def test_probes_that_all_find_a_carry_are_no_problem():
    """Catches a false alarm when the plan format is as expected."""
    assert cps.probe_problems({name: ["UNNEST"] for name, _ in cps.PROBES}) == []


# --- real plans from DuckDB (R4.1, R4.2) ----------------------------------------------------


@pytest.fixture(scope="module")
def con():
    connection = duckdb.connect()
    connection.execute(
        """create table r as select
           '{"id":1,"teams":[{"a":1},{"a":2}]}'::json as payload, 'x' as fetched_at"""
    )
    yield connection
    connection.close()


def plan(connection, sql):
    return json.loads(connection.execute("explain (format json) " + sql).fetchall()[0][1])


FLAGGED = {
    "select_list_unnest": (
        "select json_extract_string(payload,'$.id') as id, "
        "unnest(json_extract(payload,'$.teams[*]')) as team from r",
        "UNNEST",
    ),
    "expression_in_from": (
        "select json_extract_string(payload,'$.id') as id, team from r "
        "cross join unnest(json_extract(payload,'$.teams[*]')) as _u(team)",
        "INOUT_FUNCTION",
    ),
    "expression_in_from_stamp_only": (
        "select fetched_at, team from r "
        "cross join unnest(json_extract(payload,'$.teams[*]')) as _u(team)",
        "INOUT_FUNCTION",
    ),
    "header_keeps_payload_and_uses_it": (
        "with h as (select payload, json_extract(payload,'$.teams[*]') as tl from r) "
        "select json_extract_string(h.payload,'$.id') as id, team from h "
        "cross join unnest(h.tl) as _u(team)",
        "UNNEST",
    ),
    "constant_list": (
        "select payload, e from r cross join unnest([1, 2]) as _u(e)",
        "CROSS_PRODUCT",
    ),
    "int_series": (
        "select json_extract_string(payload,'$.id') as id, e from r "
        "cross join unnest(generate_series(1, 3)) as _u(e)",
        "CROSS_PRODUCT",
    ),
    "filtered_list": (
        "select r.payload, e from r cross join unnest([1,2]) as u(e) where e > 1",
        "CROSS_PRODUCT",
    ),
    "filter_on_payload_side": (
        "select q.payload, e from (select payload from r where fetched_at > '0') q "
        "cross join unnest([1,2]) as u(e)",
        "CROSS_PRODUCT",
    ),
    "join_on_true": (
        "select r.payload, e from r inner join unnest([1,2]) as u(e) on true",
        "CROSS_PRODUCT",
    ),
    "join_condition": (
        "select r.payload, e from r "
        "inner join (select unnest([1,2]) as e) u on u.e = length(r.fetched_at)",
        "HASH_JOIN",
    ),
}

NOT_FLAGGED = {
    "header": (
        "with h as (select json_extract_string(payload,'$.id') as id, "
        "json_extract(payload,'$.teams[*]') as tl from r) "
        "select h.id, team from h cross join unnest(h.tl) as _u(team)"
    ),
    "kept_unused": (
        "with h as (select payload, json_extract_string(payload,'$.id') as id, "
        "json_extract(payload,'$.teams[*]') as tl from r) "
        "select h.id, team from h cross join unnest(h.tl) as _u(team)"
    ),
    "constant_list_small_columns": (
        "with h as (select json_extract_string(payload,'$.id') as id from r) "
        "select h.id, e from h cross join unnest([1, 2]) as _u(e)"
    ),
    "semi_join": "select payload from r where fetched_at in (select unnest(['a','b']))",
}


@pytest.mark.parametrize("name", sorted(FLAGGED))
def test_a_forbidden_shape_is_flagged_with_its_operator(con, name):
    """Catches a way of carrying a payload into an unnest that DuckDB plans and we miss."""
    sql, operator = FLAGGED[name]
    assert cps.payload_carries(plan(con, sql)) == [operator]


@pytest.mark.parametrize("name", sorted(NOT_FLAGGED))
def test_a_correct_shape_is_not_flagged(con, name):
    """Catches a false positive that would push people to work around the check."""
    assert cps.payload_carries(plan(con, NOT_FLAGGED[name])) == []


@pytest.mark.parametrize("index", [0, 1, 2])
def test_each_probe_is_flagged_on_this_duckdb(con, index):
    """Catches a probe the gate relies on not working on the installed DuckDB."""
    _, template = cps.PROBES[index]
    assert cps.payload_carries(plan(con, template.format(relation="r"))) != []


# --- the fo_captures call is parsed, not matched (reviews of #207) -----------------------


@pytest.mark.parametrize(
    "call",
    [
        "fo_captures('espn', 'new_endpoint', structure=none,)",
        "fo_captures('espn', 'new_endpoint',)",
        "fo_captures('espn', 'new_endpoint', None)",
    ],
)
def test_a_none_third_argument_in_any_text_variant_is_a_payload_view(call):
    """Catches a trailing comma, or a capital `None`, making a payload view look heavy."""
    nodes = {"model.p.v": model("{{ " + call + " }}")}
    assert cps.payload_views(nodes) == {"model.p.v": ("espn", "new_endpoint")}
    assert cps.heavy_views(nodes) == {}


def test_a_structure_followed_by_a_trailing_comma_is_heavy():
    """Catches the trailing-comma handling dropping a real structure."""
    nodes = {"model.p.v": model("{{ fo_captures('espn', 'roster', structure,) }}")}
    assert cps.heavy_views(nodes) == {"model.p.v": "roster"}
    assert cps.payload_views(nodes) == {}


def test_a_dict_literal_structure_with_commas_and_parentheses_in_strings_is_heavy():
    """Catches the argument split or the closing parenthesis being found inside a literal."""
    code = "{{ fo_captures('espn', 'roster', {'teams': '[{\"id\": \"BIGINT\"}], )'}, ) }}"
    nodes = {"model.p.v": model(code)}
    assert cps.heavy_views(nodes) == {"model.p.v": "roster"}
    assert cps.payload_views(nodes) == {}


def test_a_macro_whose_name_ends_in_fo_captures_is_neither():
    """Catches the word boundary before `fo_captures` being lost."""
    nodes = {"model.p.v": model("{{ duckdb__fo_captures('a', 'b') }}")}
    assert cps.heavy_views(nodes) == {}
    assert cps.payload_views(nodes) == {}
