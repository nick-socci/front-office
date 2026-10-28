"""Tests for the lineup solver's function declaration and its DuckDB plugin (spec 0137).

dbt/functions/_functions.yml declares the BigQuery UDF; dbt/python_modules/fo_duckdb_functions.py
registers the same Python function on DuckDB with types of its own. Neither warehouse is
needed: the YAML is read as data and the plugin runs on a fresh in-memory connection.
"""

from datetime import date
from pathlib import Path

import duckdb
import pytest
import yaml

import fo_duckdb_functions

DBT = Path(__file__).resolve().parents[2] / "dbt"
FUNCTION = yaml.safe_load((DBT / "functions/_functions.yml").read_text())["functions"][0]

# BigQuery type name -> DuckDB type id.
SCALARS = {
    "string": "varchar",
    "int64": "bigint",
    "float64": "double",
    "bool": "boolean",
    "date": "date",
}


def split_top_level(text):
    """Split on the commas that are not inside angle brackets."""
    parts, depth, start = [], 0, 0
    for i, char in enumerate(text):
        depth += char == "<"
        depth -= char == ">"
        if char == "," and depth == 0:
            parts.append(text[start:i].strip())
            start = i + 1
    parts.append(text[start:].strip())
    return parts


def parse_bigquery(text):
    """A BigQuery type string as ('array', T), ('struct', [(name, T), ...]) or a scalar id."""
    text = text.strip().lower()
    if text.startswith("array<") and text.endswith(">"):
        return ("array", parse_bigquery(text[len("array<") : -1]))
    if text.startswith("struct<") and text.endswith(">"):
        fields = []
        for part in split_top_level(text[len("struct<") : -1]):
            name, field_type = part.split(None, 1)
            fields.append((name, parse_bigquery(field_type)))
        return ("struct", fields)
    return SCALARS[text]


def from_duckdb(duck_type):
    """A DuckDB type in the same normal form as parse_bigquery."""
    kind = str(duck_type.id)
    if kind == "list":
        return ("array", from_duckdb(duck_type.children[0][1]))
    if kind == "struct":
        return ("struct", [(name, from_duckdb(child)) for name, child in duck_type.children])
    return kind


def test_the_parser_reads_nested_types():
    """Catches a parser that mis-splits nested fields, which would make the comparison
    below pass or fail for the wrong reason."""
    parsed = parse_bigquery("array<struct<a date, b array<struct<c int64, d string>>>>")
    assert parsed == (
        "array",
        (
            "struct",
            [("a", "date"), ("b", ("array", ("struct", [("c", "bigint"), ("d", "varchar")])))],
        ),
    )


def test_the_runtime_and_packages_are_pinned_to_what_bigquery_offers():
    """Catches an unpinned package, a numpy 2 or another Python: BigQuery's Python UDFs run
    3.11 and constrain numpy below 2, and refuse a package set it cannot resolve (R5.2)."""
    config = FUNCTION["config"]
    assert config["runtime_version"] == "3.11"
    assert config["packages"] == ["scipy==1.17.1", "numpy==1.26.4"]
    assert config["entry_point"] == "solve_lineup_period"


def test_the_function_is_enabled_on_bigquery_only():
    """Catches a function resource that DuckDB would try to create: DuckDB's copy comes from
    the plugin, and dbt would send BigQuery's DDL to it (ADR 0103)."""
    assert FUNCTION["config"]["enabled"] == "{{ target.type == 'bigquery' }}"


def test_the_plugin_types_match_the_yaml_signature():
    """Catches the two declarations of one signature drifting apart (R6.3): a renamed,
    reordered or retyped argument or struct field, at any depth, on either side."""
    yaml_arguments = [(a["name"], parse_bigquery(a["data_type"])) for a in FUNCTION["arguments"]]
    plugin_arguments = [(name, from_duckdb(t)) for name, t in fo_duckdb_functions.ARGUMENTS]
    assert plugin_arguments == yaml_arguments
    assert from_duckdb(fo_duckdb_functions.RETURNS) == parse_bigquery(
        FUNCTION["returns"]["data_type"]
    )
    assert FUNCTION["name"] == fo_duckdb_functions.NAME


def test_the_comparison_sees_a_field_that_differs():
    """Catches a comparison too weak to fail: a struct field of another type or name in the
    YAML must not equal the plugin's."""
    plugin = from_duckdb(fo_duckdb_functions.RETURNS)
    retyped = parse_bigquery("array<struct<scoring_date date, player_id string, slot_id int64>>")
    renamed = parse_bigquery("array<struct<day date, player_id int64, slot_id int64>>")
    assert plugin != retyped
    assert plugin != renamed


@pytest.fixture
def connection():
    conn = duckdb.connect()
    fo_duckdb_functions.Plugin("fo_duckdb_functions", {}).configure_connection(conn)
    return conn


def test_the_plugin_registers_a_function_that_sql_can_call(connection):
    """Catches a type list DuckDB rejects only at call time, a null start_limit that never
    reaches the function, or a result DuckDB cannot read back: one literal team-period goes
    in through SQL and its lineup comes out."""
    rows = connection.execute(
        """
        select unnest(solve_lineup_period(
            'team',
            1,
            [
                {'scoring_date': date '2026-06-01', 'player_id': 1, 'slot_id': 1,
                 'role': 'hitter', 'value': 2.0, 'is_actual': false, 'is_start': false},
                {'scoring_date': date '2026-06-01', 'player_id': 2, 'slot_id': 1,
                 'role': 'hitter', 'value': 3.0, 'is_actual': false, 'is_start': false}
            ],
            [{'slot_id': 1, 'role': 'hitter', 'count': 1}],
            null::double
        ), recursive := true)
        """
    ).fetchall()
    assert rows == [(date(2026, 6, 1), 2, 1)]


def test_the_function_called_from_sql_names_the_team_on_failure(connection):
    """Catches an error raised in the function being swallowed or losing its message when it
    crosses DuckDB: the build must fail naming the team-day (R2.3, R2.4)."""
    with pytest.raises(duckdb.Error, match="team-day the team, scoring_date=2026-06-01"):
        connection.execute(
            """
            select solve_lineup_period(
                'the team',
                null,
                [{'scoring_date': date '2026-06-01', 'player_id': 1, 'slot_id': 1,
                  'role': 'hitter', 'value': 2.0, 'is_actual': false, 'is_start': false}],
                [{'slot_id': 1, 'role': 'hitter', 'count': 1}],
                null::double
            )
            """
        ).fetchall()
