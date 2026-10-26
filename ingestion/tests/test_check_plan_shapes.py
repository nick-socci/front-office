"""Tests for the plan-shape check (spec 0156 R4, ADR 0102).

The pure parts take hand-written manifest nodes and plan JSON, so they need no dbt and no
real data. The explain of the compiled SQL against the fixture warehouse is the gate's.
"""

import datetime

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
