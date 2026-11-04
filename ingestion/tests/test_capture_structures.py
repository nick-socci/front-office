"""The loader's reading of the declared structures (spec 0140, R1.2, R5.1 to R5.4).

A heavy endpoint goes up as the structure its capture view declares, reduced in Python. These
tests hold the reduction to the view's own reading: DuckDB's `read_json` of the same fixture
file with the same structure, which is what a DuckDB build reads.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import duckdb
import pytest

from front_office.capture_structures import (
    MAP,
    Column,
    StructureMismatch,
    StructureUnreadable,
    as_columns,
    columns,
    read_structures,
    reduce,
)
from front_office.landing import LandingZone

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "landing"
HEAVY = {("espn", "roster"), ("espn", "matchup_days"), ("mlb", "boxscore"), ("mlb", "schedule")}
GUID = "{272E019C-48D5-42F3-B289-C48A1B163E19}"


def test_exactly_the_four_heavy_pairs_are_read_from_the_macro_file() -> None:
    """Catches a branch the loader misses or misreads: a heavy endpoint would go up as JSON,
    and its view would read columns that are not there."""
    assert set(read_structures()) == HEAVY


def test_a_schedule_is_a_list_of_days_each_a_list_of_json_games() -> None:
    """Catches a list or a JSON leaf given the wrong column type or mode."""
    assert columns(read_structures()[("mlb", "schedule")]) == [
        Column("dates", "RECORD", "REPEATED", (Column("games", "JSON", "REPEATED"),))
    ]


def test_a_boxscores_players_are_a_map_of_key_value_records() -> None:
    """Catches a map not stored as the REPEATED RECORD of `key` and `value` that
    bigquery__fo_json_parse_value gives today (R1.2, R2.2)."""
    (teams,) = columns(read_structures()[("mlb", "boxscore")])
    home = dict((field.name, field) for field in teams.fields)["home"]
    by_name = {field.name: field for field in home.fields}
    assert by_name["team"] == Column("team", "RECORD", fields=(Column("id", "INT64"),))
    players = by_name["players"]
    assert (players.type, players.mode) == ("RECORD", "REPEATED")
    key, value = players.fields
    assert key == Column("key", "STRING")
    assert (value.name, value.type, value.mode) == ("value", "RECORD", "NULLABLE")
    assert [field.name for field in value.fields] == [
        "person",
        "position",
        "battingOrder",
        "gameStatus",
        "stats",
    ]


def test_a_roster_has_the_league_id_as_text_and_the_season_as_a_number() -> None:
    """Catches the league id typed as a number, which the models read as text (C7)."""
    first_two = columns(read_structures()[("espn", "roster")])[:2]
    assert first_two == [Column("id", "STRING"), Column("seasonId", "INT64")]


def _macro(*branches: tuple[str, str, str]) -> str:
    """A macro file in fo_capture_structure's form, one branch per (source, endpoint, body)."""
    parts = []
    for number, (source, endpoint, body) in enumerate(branches):
        word = "if" if number == 0 else "elif"
        parts.append(
            f"{{%- {word} source_name == '{source}' and endpoint == '{endpoint}' -%}}\n{body}\n"
        )
    return (
        "{% macro fo_capture_structure(source_name, endpoint) %}\n"
        + "".join(parts)
        + ("{%- endif -%}\n{% endmacro %}\n")
    )


def _set(structure: str) -> str:
    return "{% set structure %}\n" + structure + "\n{% endset %}"


@pytest.mark.parametrize(
    ("body", "reason"),
    [
        ("", "sets 0 structures"),
        (_set('{"a": "BIGINT"}') + _set('{"b": "BIGINT"}'), "sets 2 structures"),
        (_set('{"a": "BIGINT",}'), "is not JSON"),
        (_set('{"a": "DOUBLE"}'), "no form for the type DOUBLE"),
        (_set('{"a": [["BIGINT"]]}'), "a list whose element is a list or a map"),
        (_set('{"a": [{"__map__": "JSON"}]}'), "a list whose element is a list or a map"),
        (_set('{"a": ["BIGINT", "VARCHAR"]}'), "not a leaf"),
        (_set('["BIGINT"]'), "not an object of fields"),
    ],
)
def test_a_structure_the_loader_cannot_store_is_refused_when_read(
    tmp_path: Path, body: str, reason: str
) -> None:
    """Catches a macro edit the loader would misread into a wrong table rather than stop on."""
    path = tmp_path / "capture_structures.sql"
    path.write_text(_macro(("espn", "roster", body)))
    with pytest.raises(StructureUnreadable, match=reason):
        read_structures(path)


def test_a_pair_declared_twice_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "capture_structures.sql"
    branch = ("espn", "roster", _set('{"a": "BIGINT"}'))
    path.write_text(_macro(branch, branch))
    with pytest.raises(StructureUnreadable, match="declared twice"):
        read_structures(path)


# -- the reduction against DuckDB's reading -----------------------------------------------


def _duckdb_type(part: Any) -> str:
    """A structure part as DuckDB's type, as duckdb__fo_structure_type writes it."""
    if isinstance(part, dict) and len(part) == 1 and MAP in part:
        return f"MAP(VARCHAR, {_duckdb_type(part[MAP])})"
    if isinstance(part, dict):
        return "STRUCT(" + ", ".join(f'"{f}" {_duckdb_type(p)}' for f, p in part.items()) + ")"
    if isinstance(part, list):
        return f"{_duckdb_type(part[0])}[]"
    return str(part)


def _as_reduced(value: Any, part: Any) -> Any:
    """DuckDB's reading in the reduction's form: a missing list or map is an empty one, as
    BigQuery's view gives it (R5.2), and a JSON leaf is parsed from its text."""
    if isinstance(part, str):
        return json.loads(value) if part == "JSON" and value is not None else value
    if isinstance(part, list):
        return [_as_reduced(item, part[0]) for item in value or []]
    if isinstance(part, dict) and len(part) == 1 and MAP in part:
        return {key: _as_reduced(item, part[MAP]) for key, item in (value or {}).items()}
    if value is None:
        return None
    return {field: _as_reduced(value[field], inner) for field, inner in part.items()}


def _read_by_duckdb(path: Path, structure: dict[str, Any]) -> dict[str, Any]:
    """The file read as fo_captures reads it on DuckDB: read_json with the structure's types."""
    types = ", ".join(f"'{field}': '{_duckdb_type(part)}'" for field, part in structure.items())
    fields = ", ".join(f'"{field}"' for field in structure)
    con = duckdb.connect()
    try:
        cursor = con.execute(
            f"select {fields} from read_json(?, columns = {{{types}}}, format = 'auto', "
            "records = true)",
            [str(path)],
        )
        names = [column[0] for column in cursor.description]
        (row,) = cursor.fetchall()
    finally:
        con.close()
    return dict(zip(names, row, strict=True))


@pytest.mark.parametrize("pair", sorted(HEAVY))
def test_the_reduction_of_each_fixture_capture_is_what_duckdb_reads(pair: tuple[str, str]) -> None:
    """Catches the loader's reading drifting from a real parse of the structure: a field
    dropped or renamed, a map's entries lost, a number in a text field stored differently."""
    structure = read_structures()[pair]
    landed = list(LandingZone(FIXTURES).iter_landed(source=pair[0], endpoint=pair[1]))
    assert landed, f"no fixture captures of {pair}"
    for capture in landed:
        duck = _read_by_duckdb(capture.path, structure)
        expected = {field: _as_reduced(duck[field], part) for field, part in structure.items()}
        assert reduce(capture.payload, structure) == expected, capture.path


def test_a_number_in_a_text_field_and_missing_parts_read_as_duckdb_reads_them(
    tmp_path: Path,
) -> None:
    """Catches what the fixtures cannot: their league id is already text, and the real one is a
    number (C7). Also a team with no roster, an entry with no player and an empty map."""
    structure = read_structures()[("espn", "roster")]
    payload = {
        "id": 81094,
        "seasonId": 2026,
        "teams": [
            {"id": 1},
            {"id": 2, "roster": {"entries": [{"playerId": 7, "lineupSlotId": 16.0}]}},
            {
                "id": 3,
                "roster": {
                    "entries": [
                        {
                            "playerPoolEntry": {
                                "player": {
                                    "stats": [
                                        {"scoringPeriodId": 4, "stats": {}},
                                        {"externalId": 2026, "stats": {"20": 1.5, "21": None}},
                                    ]
                                }
                            }
                        }
                    ]
                },
            },
        ],
    }
    path = tmp_path / "payload.json"
    path.write_text(json.dumps(payload))
    duck = _read_by_duckdb(path, structure)
    expected = {field: _as_reduced(duck[field], part) for field, part in structure.items()}
    assert reduce(payload, structure) == expected
    assert expected["id"] == "81094"


# -- what the reduction keeps, and what it refuses ----------------------------------------

STRUCTURE: dict[str, Any] = {
    "id": "VARCHAR",
    "season": "BIGINT",
    "teams": [{"id": "BIGINT", "stats": {MAP: "JSON"}}],
    "box": {"players": {MAP: {"name": "JSON"}}},
}


def test_only_declared_fields_are_kept_and_a_missing_one_is_what_the_view_gives() -> None:
    """Catches an undeclared field going up, and a missing list or map stored as null, which
    a REPEATED column cannot hold (R5.2)."""
    payload = {"id": "7", "extra": {"members": ["x"]}, "teams": [{"name": "T"}]}
    assert reduce(payload, STRUCTURE) == {
        "id": "7",
        "season": None,
        "teams": [{"id": None, "stats": {}}],
        "box": None,
    }


def test_a_number_in_a_text_field_is_stored_as_its_digits() -> None:
    """Catches the league id, a number in the payload and text in the models, stored as
    anything but what lax_string and DuckDB read (R5.4, C7)."""
    assert reduce({"id": 81094}, STRUCTURE)["id"] == "81094"


def test_a_whole_number_written_with_a_point_is_a_whole_number() -> None:
    assert reduce({"season": 2026.0}, STRUCTURE)["season"] == 2026


@pytest.mark.parametrize(
    ("payload", "path", "problem"),
    [
        ({"season": "2026"}, "$.season", "a whole number was declared, text found"),
        ({"season": 1.5}, "$.season", "a whole number was declared, a number found"),
        ({"season": True}, "$.season", "a whole number was declared, a boolean found"),
        ({"season": 2**63}, "$.season", "a whole number was declared, a number found"),
        ({"id": {"value": "A Member"}}, "$.id", "text was declared, an object found"),
        ({"id": ["A Member"]}, "$.id", "text was declared, a list found"),
        ({"id": 1.25}, "$.id", "text was declared, a number found"),
        ({"id": False}, "$.id", "text was declared, a boolean found"),
        ({"teams": [{"id": 1}, None]}, "$.teams[1]", "a null in a list"),
        ({"teams": {"id": 1}}, "$.teams", "a list was declared, an object found"),
        ({"box": ["A Member"]}, "$.box", "an object was declared, a list found"),
        ({"box": {"players": ["A Member"]}}, "$.box.players", "a map was declared, a list found"),
        ({"teams": [{"stats": "A Member"}]}, "$.teams[0].stats", "a map was declared, text found"),
        ("A Member", "$", "an object was declared, text found"),
    ],
)
def test_a_value_that_does_not_fit_is_refused_naming_the_path_never_the_value(
    payload: Any, path: str, problem: str
) -> None:
    """Catches a silent wrong value, a capture's rows lost to an empty list where an object
    arrived, and a value in a message (R5.3)."""
    with pytest.raises(StructureMismatch) as raised:
        reduce(payload, STRUCTURE)
    assert (raised.value.path, raised.value.problem) == (path, problem)
    assert "Member" not in str(raised.value)


def test_a_guid_among_a_maps_keys_is_masked_in_the_path() -> None:
    """Catches an account id reaching a message through the path, which a map's keys are in."""
    with pytest.raises(StructureMismatch) as raised:
        reduce({"teams": [{"stats": {GUID: 1}}], "box": {"players": {GUID: 3}}}, STRUCTURE)
    assert GUID not in str(raised.value)
    assert raised.value.path == "$.box.players.<guid>"


def test_a_map_becomes_key_value_rows_in_the_documents_order() -> None:
    """Catches a map stored in another shape than the view's key-value structs, or reordered."""
    reduced = reduce(
        {"teams": [{"id": 1, "stats": {"5": 2, "1": {"x": 1}}}], "box": {"players": {}}},
        STRUCTURE,
    )
    assert as_columns(reduced, STRUCTURE) == {
        "id": None,
        "season": None,
        "teams": [{"id": 1, "stats": [{"key": "5", "value": 2}, {"key": "1", "value": {"x": 1}}]}],
        "box": {"players": []},
    }
