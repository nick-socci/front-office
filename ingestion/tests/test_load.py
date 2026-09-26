"""Tests for loading the landing zone into raw.api_responses.

The loader must be safe to rerun: you will run it after every backfill, and most of what
it sees will already be in the table.
"""

import duckdb
import pytest

from front_office.landing import LandingZone
from front_office.load import load_landing_zone


@pytest.fixture
def zone(tmp_path):
    return LandingZone(root=tmp_path / "raw")


@pytest.fixture
def con():
    with duckdb.connect(":memory:") as con:
        yield con


def land_one(zone, *, name="fetched_at=20260926T000000Z", payload=None, params=None):
    return zone.write(
        source="mlb",
        endpoint="schedule",
        partitions={"season": 2026},
        name=name,
        payload=payload if payload is not None else {"dates": []},
        request={
            "url": "https://statsapi.mlb.com/api/v1/schedule",
            "params": params or {"season": "2026"},
        },
        fetched_at=name.removeprefix("fetched_at="),
    )


def test_creates_table_and_loads_row(zone, con):
    land_one(zone)
    inserted = load_landing_zone(con, zone)
    assert inserted == 1
    row = con.execute(
        "select source, endpoint, request_key, fetched_at, payload, file_path "
        "from raw.api_responses"
    ).fetchone()
    source, endpoint, request_key, fetched_at, payload, file_path = row
    assert (source, endpoint, request_key) == ("mlb", "schedule", "season=2026")
    assert fetched_at == "20260926T000000Z"
    assert '"dates"' in payload
    assert file_path.endswith("fetched_at=20260926T000000Z.json")


def test_second_load_is_a_no_op(zone, con):
    land_one(zone)
    assert load_landing_zone(con, zone) == 1
    assert load_landing_zone(con, zone) == 0
    assert con.execute("select count(*) from raw.api_responses").fetchone()[0] == 1


def test_new_snapshot_of_same_request_is_a_new_row(zone, con):
    land_one(zone, name="fetched_at=20260926T000000Z")
    load_landing_zone(con, zone)
    land_one(zone, name="fetched_at=20260927T000000Z", payload={"dates": [1]})
    assert load_landing_zone(con, zone) == 1
    counts = con.execute(
        "select count(*), count(distinct fetched_at) from raw.api_responses"
    ).fetchone()
    assert counts == (2, 2), "snapshots accumulate; history is never overwritten"


def test_payload_is_queryable_as_json(zone, con):
    land_one(zone, payload={"dates": [{"games": [{"gamePk": 746123}]}]})
    load_landing_zone(con, zone)
    game_pk = con.execute(
        "select payload->'$.dates[0].games[0].gamePk' from raw.api_responses"
    ).fetchone()[0]
    assert int(str(game_pk).strip('"')) == 746123


def test_empty_landing_zone_is_not_an_error(zone, con):
    assert load_landing_zone(con, zone) == 0


def test_files_without_a_sidecar_are_skipped(zone, con):
    """The throwaway spike scripts landed JSON with no metadata sidecar.

    Those files must never become rows: with no metadata the key columns would all be
    empty, which both collides on the primary key and produces untraceable rows.
    """
    orphan_dir = zone.root / "espn/roster_matchup/season=2026"
    orphan_dir.mkdir(parents=True)
    (orphan_dir / "scoring_period=1.json").write_text('{"teams": []}')
    (orphan_dir / "scoring_period=2.json").write_text('{"teams": []}')

    land_one(zone)
    assert load_landing_zone(con, zone) == 1
    sources = con.execute("select distinct source from raw.api_responses").fetchall()
    assert sources == [("mlb",)]


def test_duplicate_keys_within_one_batch_insert_once(zone, con):
    """Two files describing the same request at the same instant collapse to one row."""
    land_one(zone)
    duplicate = zone.path_for(
        source="mlb",
        endpoint="schedule",
        partitions={"season": 2026},
        name="copy",
    )
    original = zone.path_for(
        source="mlb",
        endpoint="schedule",
        partitions={"season": 2026},
        name="fetched_at=20260926T000000Z",
    )
    duplicate.write_text(original.read_text())
    duplicate.with_suffix(".meta.json").write_text(original.with_suffix(".meta.json").read_text())

    assert load_landing_zone(con, zone) == 1
    assert con.execute("select count(*) from raw.api_responses").fetchone()[0] == 1
