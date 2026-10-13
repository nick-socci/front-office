"""Tests for loading the landing zone into raw.api_responses.

The loader must be safe to rerun: you will run it after every backfill, and most of what
it sees will already be in the table.
"""

import json
import shutil

import duckdb
import pytest

from front_office.landing import LandingZone, PayloadNotJson
from front_office.load import (
    RawKeyCollision,
    RawSchemaOutdated,
    load_landing_zone,
)


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
        "select source, endpoint, request_path, request_key, fetched_at, partitions, "
        "payload, file_path from raw.api_responses"
    ).fetchone()
    source, endpoint, request_path, request_key, fetched_at, partitions, payload, file_path = row
    assert (source, endpoint, request_key) == ("mlb", "schedule", "season=2026")
    assert request_path == "/api/v1/schedule"
    assert json.loads(partitions) == {"season": 2026}
    assert fetched_at == "20260926T000000Z"
    assert '"dates"' in payload
    assert file_path.endswith("fetched_at=20260926T000000Z/payload.json")


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


def land_capture(zone, *, league, season, fetched_at="20260926T000000Z", folder=None):
    """One ESPN-shaped capture: same endpoint and params for every league."""
    return zone.write(
        source="espn",
        endpoint="settings",
        partitions=folder or {"season": season, "league_id": league},
        name=f"fetched_at={fetched_at}",
        payload={"league": league, "season": season},
        request={
            "url": "https://lm-api-reads.fantasy.espn.com/apis/v3/games/flb/seasons/"
            f"{season}/segments/0/leagues/{league}?view=mSettings",
            "params": {"view": "mSettings"},
        },
        fetched_at=fetched_at,
    )


def row_count(con):
    return con.execute("select count(*) from raw.api_responses").fetchone()[0]


def test_two_leagues_and_two_seasons_at_one_instant_are_four_rows(zone, con):
    """Catches a key that cannot tell captures apart by request path (R5.4).

    Same endpoint, same params, same fetched_at: before request_path joined the key the
    loader kept one of the four.
    """
    for league in ("111", "222"):
        for season in (2025, 2026):
            land_capture(zone, league=league, season=season)
    assert load_landing_zone(con, zone) == 4
    rows = con.execute(
        "select request_path, partitions from raw.api_responses order by request_path"
    ).fetchall()
    assert len({path for path, _ in rows}) == 4
    for path, partitions in rows:
        parsed = json.loads(partitions)
        assert f"/seasons/{parsed['season']}/segments/0/leagues/{parsed['league_id']}" in path


def test_partitions_are_stored_as_written(zone, con):
    """Catches partitions being re-ordered or stringified on the way into the table."""
    land_capture(zone, league="111", season=2026)
    load_landing_zone(con, zone)
    stored = con.execute("select partitions::varchar from raw.api_responses").fetchone()[0]
    assert stored == json.dumps({"season": 2026, "league_id": "111"})


def duplicate_into_other_folder(zone):
    """Copy the one landed capture under a different partition folder: same full key.

    Returns the two payload.json paths, which is what the loader stores as file_path.
    """
    original = next(zone.root.glob("espn/**/fetched_at=*Z"))
    copy = original.parent.parent / "league_id=copy" / original.name
    copy.parent.mkdir(parents=True)
    shutil.copytree(original, copy)
    # The sidecar still names the original folder, which the committed check would reject;
    # point it at the copy so the two captures are both committed and share one key.
    meta = json.loads((copy / "meta.json").read_text())
    meta["partitions"]["league_id"] = "copy"
    (copy / "meta.json").write_text(json.dumps(meta))
    return original / "payload.json", copy / "payload.json"


def test_two_files_with_one_key_in_a_batch_fail_and_insert_nothing(zone, con):
    """Catches the old silent first-wins dedupe (R1.4): a collision must be loud."""
    land_one(zone)
    land_one(zone, name="fetched_at=20260101T000000Z")
    load_landing_zone(con, zone)
    before = row_count(con)
    land_capture(zone, league="111", season=2026, fetched_at="20260927T000000Z")
    original, copy = duplicate_into_other_folder(zone)
    with pytest.raises(RawKeyCollision) as excinfo:
        load_landing_zone(con, zone)
    message = str(excinfo.value)
    assert str(original) in message
    assert str(copy) in message
    assert "20260927T000000Z" in message
    assert row_count(con) == before, "nothing from a failed run is inserted"


def test_collision_in_an_empty_table_leaves_it_empty(zone, con):
    """Catches a partial insert before the collision is detected."""
    land_capture(zone, league="111", season=2026)
    duplicate_into_other_folder(zone)
    with pytest.raises(RawKeyCollision):
        load_landing_zone(con, zone)
    assert row_count(con) == 0


def test_a_file_with_the_key_of_an_existing_row_of_another_path_fails(zone, con):
    """Catches a later file silently losing to an earlier row with the same key (R1.4)."""
    land_capture(zone, league="111", season=2026)
    load_landing_zone(con, zone)
    original, copy = duplicate_into_other_folder(zone)
    with pytest.raises(RawKeyCollision) as excinfo:
        load_landing_zone(con, zone)
    assert str(original) in str(excinfo.value)
    assert str(copy) in str(excinfo.value)
    assert row_count(con) == 1


def test_loading_the_same_zone_twice_is_not_a_collision(zone, con):
    """Catches the same-file re-load being mistaken for a collision (R1.7)."""
    land_one(zone)
    land_capture(zone, league="111", season=2026)
    assert load_landing_zone(con, zone) == 2
    assert load_landing_zone(con, zone) == 0
    assert row_count(con) == 2


OLD_TABLE = """
create schema raw;
create table raw.api_responses (
    source varchar not null,
    endpoint varchar not null,
    request_key varchar not null,
    fetched_at varchar not null,
    payload json not null,
    file_path varchar not null,
    primary key (source, endpoint, request_key, fetched_at)
);
insert into raw.api_responses values ('mlb', 'schedule', 'a=1', 'T', '{}', '/x.json');
"""


def test_an_old_shape_table_is_refused_and_left_alone(zone, con):
    """Catches a loader that drops, alters or inserts into a pre-#28 table (R1.5)."""
    con.execute(OLD_TABLE)
    land_one(zone)
    with pytest.raises(RawSchemaOutdated) as excinfo:
        load_landing_zone(con, zone)
    assert "--db" in str(excinfo.value)
    columns = [c[0] for c in con.execute("describe raw.api_responses").fetchall()]
    assert columns == ["source", "endpoint", "request_key", "fetched_at", "payload", "file_path"]
    assert con.execute("select * from raw.api_responses").fetchall() == [
        ("mlb", "schedule", "a=1", "T", "{}", "/x.json")
    ]


@pytest.mark.parametrize("missing", ["url", "partitions"])
def test_a_sidecar_missing_url_or_partitions_is_not_committed_so_not_loaded(zone, con, missing):
    """Catches loading a capture whose request path or partitions cannot be known."""
    land_one(zone)
    bad = land_one(zone, name="fetched_at=20260927T000000Z")
    meta = json.loads((bad / "meta.json").read_text())
    del meta[missing]
    (bad / "meta.json").write_text(json.dumps(meta))
    assert load_landing_zone(con, zone) == 1


def test_a_temp_directory_and_a_loose_old_layout_file_are_not_loaded(zone, con):
    """Catches the loader reading anything but committed captures (R2.3)."""
    good = land_one(zone)
    shutil.copytree(good, good.with_name("fetched_at=20260927T000000Z.tmp-1"))
    (good.parent / "fetched_at=20260928T000000Z.json").write_text("{}")
    (good.parent / "fetched_at=20260928T000000Z.meta.json").write_text("{}")
    assert load_landing_zone(con, zone) == 1


def test_a_committed_capture_with_an_unparseable_payload_fails_the_load(zone, con):
    """Catches an unreadable committed payload being skipped instead of reported (R2.7)."""
    land_one(zone)
    bad = land_one(zone, name="fetched_at=20260927T000000Z")
    size = (bad / "payload.json").stat().st_size
    (bad / "payload.json").write_bytes(b"?" * size)
    with pytest.raises(PayloadNotJson) as excinfo:
        load_landing_zone(con, zone)
    assert str(bad / "payload.json") in str(excinfo.value)
    assert row_count(con) == 0, "nothing from a failed run is inserted"


def test_a_player_list_capture_loads_as_one_row_with_no_loader_change(zone, con):
    """Catches the loader needing to know the new endpoint (spec 0060, R5.6)."""
    zone.write(
        source="mlb",
        endpoint="players",
        partitions={"season": 2026},
        name="fetched_at=20261009T000000Z",
        payload={"people": [{"id": 660271}]},
        request={
            "url": "https://statsapi.mlb.com/api/v1/sports/1/players",
            "params": {"season": 2026},
        },
        fetched_at="20261009T000000Z",
    )
    assert load_landing_zone(con, zone) == 1
    rows = con.execute(
        "select source, endpoint, request_key, payload from raw.api_responses"
    ).fetchall()
    assert len(rows) == 1
    source, endpoint, request_key, payload = rows[0]
    assert (source, endpoint, request_key) == ("mlb", "players", "season=2026")
    assert json.loads(payload) == {"people": [{"id": 660271}]}


# -- memory: payloads are read only when new, and a batch at a time (#149) -------------------


class CountingConnection:
    """A DuckDB connection that records the size of every executemany, and can be told to
    fail on one of them, as a load that is killed part-way would."""

    def __init__(self, con, fail_on_batch=None):
        self._con = con
        self.batches: list[int] = []
        self.fail_on_batch = fail_on_batch

    def executemany(self, sql, rows):
        if self.fail_on_batch == len(self.batches) + 1:
            raise RuntimeError("the load was interrupted")
        self.batches.append(len(rows))
        return self._con.executemany(sql, rows)

    def __getattr__(self, name):
        return getattr(self._con, name)


@pytest.fixture
def payload_reads(monkeypatch):
    """The payload files read through the landing zone, in order."""
    from front_office.landing import Capture

    reads: list[str] = []
    original = Capture.payload.fget

    def counted(self):
        reads.append(str(self.payload_path))
        return original(self)

    monkeypatch.setattr(Capture, "payload", property(counted))
    return reads


def land_days(zone, count):
    return [
        land_one(zone, name=f"fetched_at=202609{day:02d}T000000Z") for day in range(1, count + 1)
    ]


def test_a_capture_already_loaded_is_not_read_again(zone, con, payload_reads):
    """Catches memory that follows the whole landing zone: the old loader read and held
    every landed payload, loaded or not, and was killed by the kernel on eight seasons. A
    second load, and a load after one new capture, read only what is new."""
    land_days(zone, 3)
    assert load_landing_zone(con, zone) == 3
    assert len(payload_reads) == 3
    assert load_landing_zone(con, zone) == 0
    assert len(payload_reads) == 3, "a load with nothing new reads no payload"
    new = land_one(zone, name="fetched_at=20260930T000000Z")
    assert load_landing_zone(con, zone) == 1
    assert payload_reads[3:] == [str(new / "payload.json")]


def test_payloads_are_read_and_inserted_a_batch_at_a_time(zone, con, payload_reads):
    """Catches every new payload being read before the first insert: with batches of two,
    the first insert happens when two payloads have been read, not five."""
    land_days(zone, 5)
    counting = CountingConnection(con)
    reads_at_insert: list[int] = []
    inner = counting.executemany

    def executemany(sql, rows):
        reads_at_insert.append(len(payload_reads))
        return inner(sql, rows)

    counting.executemany = executemany
    assert load_landing_zone(counting, zone, batch_rows=2) == 5
    assert counting.batches == [2, 2, 1]
    assert reads_at_insert == [2, 4, 5]
    assert row_count(con) == 5


def test_a_load_interrupted_between_batches_leaves_no_row_of_the_run(zone, con):
    """Catches a partial load: the old loader inserted row by row with no transaction, and
    a load that died left 1,896 of 2,431 boxscores of a season in the table."""
    land_days(zone, 2)
    load_landing_zone(con, zone)
    land_one(zone, name="fetched_at=20260910T000000Z")
    land_one(zone, name="fetched_at=20260911T000000Z")
    land_one(zone, name="fetched_at=20260912T000000Z")
    with pytest.raises(RuntimeError, match="interrupted"):
        load_landing_zone(CountingConnection(con, fail_on_batch=2), zone, batch_rows=2)
    assert row_count(con) == 2, "nothing from an interrupted run is inserted"
    assert load_landing_zone(con, zone, batch_rows=2) == 3
    assert row_count(con) == 5


def test_an_unparseable_payload_in_a_later_batch_undoes_the_earlier_ones(zone, con):
    """Catches the first batches staying in when a later capture turns out not to be JSON:
    the failure must leave nothing of the run, whichever batch it is found in."""
    captures = land_days(zone, 5)
    bad = captures[-1] / "payload.json"
    bad.write_bytes(b"?" * bad.stat().st_size)
    with pytest.raises(PayloadNotJson):
        load_landing_zone(con, zone, batch_rows=2)
    assert row_count(con) == 0


def test_the_batch_size_does_not_change_what_is_loaded(zone, tmp_path):
    """Catches a row lost or repeated at a batch boundary."""
    land_days(zone, 7)
    tables = []
    for batch_rows in (1, 3, 100):
        with duckdb.connect(":memory:") as fresh:
            assert load_landing_zone(fresh, zone, batch_rows=batch_rows) == 7
            tables.append(
                fresh.execute("select * from raw.api_responses order by fetched_at").fetchall()
            )
    assert tables[0] == tables[1] == tables[2] and len(tables[0]) == 7


def test_a_file_with_the_key_of_a_row_whose_own_file_is_gone_still_fails(zone, con):
    """Catches the check against the table being dropped: when the file a row was loaded
    from is no longer in the landing zone (moved to the quarantine, say), another file with
    that key cannot be told from it by looking at the files alone. Found by breaking that
    check and seeing every other collision test stay green (#149)."""
    land_capture(zone, league="111", season=2026)
    load_landing_zone(con, zone)
    original, copy = duplicate_into_other_folder(zone)
    shutil.rmtree(original.parent)
    with pytest.raises(RawKeyCollision) as excinfo:
        load_landing_zone(con, zone)
    assert str(original) in str(excinfo.value) and str(copy) in str(excinfo.value)
    assert row_count(con) == 1
