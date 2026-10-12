"""The spike's loader: what may leave the machine, and whether it arrived whole (spec 0130,
R3; ADR 0054).

Nothing here talks to BigQuery. The privacy check and the row comparison are pure
functions over rows; the reading of the local warehouse is tested on a small DuckDB file.
"""

from __future__ import annotations

import json
from pathlib import Path

import duckdb
import pytest

import spike_load_bigquery as loader

GUID = "{272E019C-48D5-42F3-B289-C48A1B163E19}"


def row(source: str, endpoint: str, payload: object, **overrides: str) -> loader.RawRow:
    values = {
        "source": source,
        "endpoint": endpoint,
        "request_path": "/a/path",
        "request_key": "k=1",
        "fetched_at": "20260926T162307Z",
        "file_path": f"data/raw/{source}/{endpoint}/payload.json",
        "partitions": "{}",
        "payload": json.dumps(payload),
    }
    values.update(overrides)
    return loader.RawRow(**values)


# -- the privacy check (R3.3) ------------------------------------------------------------


def test_a_guid_in_an_espn_row_stops_the_upload_and_the_value_is_not_reported() -> None:
    """Catches an ESPN account id going up, and the check printing the id it found."""
    hits = loader.privacy_hits(row("espn", "roster", {"teams": [{"note": f"by {GUID}"}]}))
    assert hits == ["espn/roster k=1: GUID at $.teams[0].note"]
    assert GUID not in "".join(hits)


def test_a_guid_as_a_key_or_outside_the_payload_is_found_too() -> None:
    """Catches a GUID that is a key of an object, or in the partitions, slipping through a
    check that reads only values of the payload."""
    as_key = loader.privacy_hits(row("espn", "settings", {"byOwner": {GUID: 1}}))
    assert as_key == ["espn/settings k=1: GUID in a key at $.byOwner"]
    in_partitions = loader.privacy_hits(
        row("espn", "settings", {}, partitions=json.dumps({"owner": GUID}))
    )
    assert in_partitions == ["espn/settings k=1: GUID at partitions $.owner"]


def test_mlbs_game_guid_is_allowed() -> None:
    """Catches the GUID rule reaching MLB rows, where gameGuid is a public game id and every
    schedule row would be refused."""
    schedule = {"dates": [{"games": [{"gameGuid": "272e019c-48d5-42f3-b289-c48a1b163e19"}]}]}
    assert loader.privacy_hits(row("mlb", "schedule", schedule)) == []


def test_a_members_name_stops_the_upload() -> None:
    """Catches a league member's name going up: a forbidden key is a hit in any row."""
    payload = {"members": [{"firstName": "A", "lastName": "B"}]}
    assert loader.privacy_hits(row("espn", "settings", payload)) == [
        "espn/settings k=1: key members at $",
        "espn/settings k=1: key firstName at $.members[0]",
        "espn/settings k=1: key lastName at $.members[0]",
    ]
    assert loader.privacy_hits(row("mlb", "schedule", {"displayName": "x"})) == [
        "mlb/schedule k=1: key displayName at $"
    ]


def test_a_ballplayers_own_name_is_allowed_and_nothing_else_in_that_object() -> None:
    """Catches the one exception widening: firstName and lastName directly in a
    playerPoolEntry.player object name a ballplayer; an owner there, or a name one level
    further in, does not."""
    player = {"firstName": "Shohei", "lastName": "Ohtani", "id": 39832}
    entry = {"teams": [{"roster": {"entries": [{"playerPoolEntry": {"player": player}}]}}]}
    assert loader.privacy_hits(row("espn", "roster", entry)) == []

    player_with_owner = {**player, "owners": ["x"]}
    entry = {"playerPoolEntry": {"player": player_with_owner}}
    assert loader.privacy_hits(row("espn", "roster", entry)) == [
        "espn/roster k=1: key owners at $.playerPoolEntry.player"
    ]
    deeper = {"playerPoolEntry": {"player": {"agent": {"firstName": "A"}}}}
    assert loader.privacy_hits(row("espn", "roster", deeper)) == [
        "espn/roster k=1: key firstName at $.playerPoolEntry.player.agent"
    ]
    elsewhere = {"player": {"firstName": "A"}}
    assert loader.privacy_hits(row("espn", "roster", elsewhere)) == [
        "espn/roster k=1: key firstName at $.player"
    ]


def test_only_the_seven_endpoints_are_read(tmp_path: Path) -> None:
    """Catches teams, transactions or MLB's player list being read for upload, and a row of
    an allowed endpoint being left behind."""
    db = tmp_path / "w.duckdb"
    con = duckdb.connect(str(db))
    con.execute("create schema raw")
    con.execute(
        "create table raw.api_responses (source varchar, endpoint varchar, request_path "
        "varchar, request_key varchar, fetched_at varchar, partitions json, payload json, "
        "file_path varchar)"
    )
    pairs = [*loader.ALLOWLIST, ("espn", "teams"), ("espn", "transactions"), ("mlb", "players")]
    for number, (source, endpoint) in enumerate(pairs):
        con.execute(
            "insert into raw.api_responses values (?, ?, '/p', ?, 't', '{}', '{\"n\": 1}', 'f')",
            [source, endpoint, f"k={number}"],
        )
    con.close()
    rows = list(loader.read_rows(db))
    assert sorted({(r.source, r.endpoint) for r in rows}) == sorted(loader.ALLOWLIST)
    assert len(rows) == 7
    assert set(loader.ALLOWLIST) == {
        ("mlb", "boxscore"),
        ("mlb", "schedule"),
        ("espn", "roster"),
        ("espn", "matchups"),
        ("espn", "settings"),
        ("espn", "pro_schedule"),
        ("idmap", "player_id_map"),
    }


def test_a_row_off_the_allowlist_stops_the_upload_however_clean_it_is() -> None:
    """Catches the second guard going: reading takes only the seven endpoints, and the check
    refuses any other row it is handed, so a caller that builds its own rows cannot upload
    `teams` or `transactions`."""
    with pytest.raises(loader.PrivacyHit) as raised:
        loader.check([row("espn", "teams", {"teams": []})])
    assert any("not on the allowlist" in hit for hit in raised.value.hits)
    assert loader.check([row("espn", "settings", {"teams": []})]) == {("espn", "settings"): 1}


def test_a_hit_anywhere_means_nothing_is_written(tmp_path: Path) -> None:
    """Catches files being exported for the clean endpoints before a hit in another is
    found: on any hit nothing is written at all."""
    clean = row("mlb", "schedule", {"dates": []})
    dirty = row("espn", "settings", {"members": []}, request_key="k=2")
    with pytest.raises(loader.PrivacyHit) as raised:
        loader.export([clean, dirty], tmp_path / "out")
    assert raised.value.hits == ["espn/settings k=2: key members at $"]
    assert not (tmp_path / "out").exists()


def test_the_export_is_one_file_per_endpoint_with_json_as_json(tmp_path: Path) -> None:
    """Catches a payload written as a quoted string, which would load as a JSON string and
    not an object, or two endpoints sharing a file."""
    rows = [
        row("mlb", "schedule", {"dates": [1.5]}),
        row("espn", "settings", {"id": 7}, request_key="k=2", partitions='{"season": 2026}'),
    ]
    files = loader.export(rows, tmp_path / "out")
    assert sorted(p.name for p in files) == ["espn__settings.ndjson", "mlb__schedule.ndjson"]
    line = json.loads((tmp_path / "out" / "espn__settings.ndjson").read_text())
    assert line["payload"] == {"id": 7} and line["partitions"] == {"season": 2026}
    assert line["request_key"] == "k=2" and set(line) == set(loader.COLUMNS)


# -- the comparison after the load (R3.4) ------------------------------------------------


def loaded(source_row: loader.RawRow, **changes: object) -> dict[str, object]:
    """The row as BigQuery would give it back: JSON columns parsed."""
    back: dict[str, object] = {
        **{name: getattr(source_row, name) for name in loader.KEY_COLUMNS},
        "file_path": source_row.file_path,
        "partitions": json.loads(source_row.partitions),
        "payload": json.loads(source_row.payload),
    }
    back.update(changes)
    return back


def test_rows_that_came_back_the_same_are_equal_whatever_the_key_order_or_number_form() -> None:
    """Catches a comparison of text: the two warehouses write the same JSON differently."""
    source = row("espn", "settings", {"a": 1, "b": [1.0, 2.5], "c": {"x": None}})
    back = loaded(source, payload={"c": {"x": None}, "b": [1, 2.5], "a": 1.0})
    as_text = loaded(source, payload='{"b": [1, 2.5], "a": 1, "c": {"x": null}}')
    for other in (back, as_text):
        result = loader.compare_rows([source], [other])
        assert result == {("espn", "settings"): loader.Tally(paired=1, equal=1)}
        assert loader.all_equal(result)


def test_a_payload_that_lost_or_changed_one_field_is_not_equal() -> None:
    """Catches what a row count would pass: a field dropped, changed, or a number rounded."""
    source = row("espn", "settings", {"a": 1, "b": {"c": 0.1234567890123}})
    for payload in ({"a": 1}, {"a": 2, "b": {"c": 0.1234567890123}}, {"a": 1, "b": {"c": 0.1234}}):
        result = loader.compare_rows([source], [loaded(source, payload=payload)])
        assert result == {("espn", "settings"): loader.Tally(paired=1, equal=0)}
        assert not loader.all_equal(result)


def test_a_different_file_path_or_partitions_is_not_equal() -> None:
    """Catches a changed file_path, the tie-break of fo_espn_latest, or changed partitions,
    which staging reads the league and season from."""
    source = row("espn", "roster", {"a": 1}, partitions='{"season": 2026}')
    for change in ({"file_path": "elsewhere"}, {"partitions": {"season": 2025}}):
        result = loader.compare_rows([source], [loaded(source, **change)])
        assert result[("espn", "roster")] == loader.Tally(paired=1, equal=0)


def test_a_row_on_one_side_only_is_counted_and_fails() -> None:
    """Catches a row that never arrived, and one that arrived from nowhere."""
    first = row("mlb", "boxscore", {"a": 1}, request_key="gamePk=1")
    second = row("mlb", "boxscore", {"a": 2}, request_key="gamePk=2")
    stray = loaded(row("mlb", "boxscore", {"a": 3}, request_key="gamePk=3"))
    result = loader.compare_rows([first, second], [loaded(first), stray])
    assert result == {
        ("mlb", "boxscore"): loader.Tally(paired=1, equal=1, only_source=1, only_loaded=1)
    }
    assert not loader.all_equal(result)
    assert not loader.all_equal(loader.compare_rows([first], []))


def test_the_same_key_loaded_twice_is_not_a_pair() -> None:
    """Catches a load that appended to a table it should have replaced: the second copy of
    a row has no source row left to pair with."""
    source = row("mlb", "boxscore", {"a": 1})
    result = loader.compare_rows([source], [loaded(source), loaded(source)])
    assert result[("mlb", "boxscore")] == loader.Tally(paired=1, equal=1, only_loaded=1)
