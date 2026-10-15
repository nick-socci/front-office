"""Tests for loading the landing zone into raw.captures (spec 0150, R1).

The table is a manifest: one row per committed capture, naming its payload file and holding
no payload, which dbt reads from the file. The loader must be safe to rerun: you will run
it after every backfill, and most of what it sees will already be in the table.
"""

import json
import shutil

import duckdb
import pytest

from front_office.landing import LandingZone
from front_office.load import (
    RawKeyCollision,
    RawSchemaOutdated,
    load_landing_zone,
)

MANIFEST_COLUMNS = [
    "source",
    "endpoint",
    "request_path",
    "request_key",
    "fetched_at",
    "partitions",
    "file_path",
]


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


def test_creates_the_manifest_and_loads_a_row(zone, con):
    """Catches a table that is not the manifest: other columns, or the payload kept (R1.1)."""
    land_one(zone)
    assert load_landing_zone(con, zone) == 1
    described = con.execute("describe raw.captures").fetchall()
    assert [column[0] for column in described] == MANIFEST_COLUMNS
    assert "payload" not in [column[0] for column in described]
    row = con.execute(
        "select source, endpoint, request_path, request_key, fetched_at, partitions, file_path "
        "from raw.captures"
    ).fetchone()
    source, endpoint, request_path, request_key, fetched_at, partitions, file_path = row
    assert (source, endpoint, request_key) == ("mlb", "schedule", "season=2026")
    assert request_path == "/api/v1/schedule"
    assert json.loads(partitions) == {"season": 2026}
    assert fetched_at == "20260926T000000Z"
    assert file_path == "mlb/schedule/season=2026/fetched_at=20260926T000000Z/payload.json"


def test_one_row_per_committed_capture(zone, con):
    """Catches a capture left out or loaded twice (R1.1)."""
    land_days(zone, 4)
    assert load_landing_zone(con, zone) == 4
    paths = [r[0] for r in con.execute("select file_path from raw.captures").fetchall()]
    assert sorted(paths) == sorted(
        f"mlb/schedule/season=2026/fetched_at=202609{day:02d}T000000Z/payload.json"
        for day in range(1, 5)
    )


def test_no_payload_is_read_during_a_load(zone, con, payload_reads):
    """Catches the loader reading payloads again: a manifest needs only sidecars (R1.3)."""
    land_days(zone, 3)
    assert load_landing_zone(con, zone) == 3
    assert load_landing_zone(con, zone) == 0
    land_one(zone, name="fetched_at=20260930T000000Z")
    assert load_landing_zone(con, zone) == 1
    assert payload_reads == []


def test_file_path_is_relative_to_the_root_however_the_root_is_spelled(
    zone, con, tmp_path, monkeypatch
):
    """Catches a file_path that follows the working directory or the root's spelling (R1.2)."""
    land_one(zone)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    spellings = []
    for cwd, root in (
        (tmp_path, "raw"),  # relative, from the zone's parent
        (elsewhere, zone.root),  # absolute, from another directory
        (zone.root, "."),  # relative, from inside the root
    ):
        monkeypatch.chdir(cwd)
        with duckdb.connect(":memory:") as fresh:
            assert load_landing_zone(fresh, LandingZone(root=root)) == 1
            spellings.append(fresh.execute("select file_path from raw.captures").fetchall())
    assert spellings[0] == spellings[1] == spellings[2]
    assert spellings[0] == [("mlb/schedule/season=2026/fetched_at=20260926T000000Z/payload.json",)]


def test_a_zone_loaded_by_another_spelling_is_not_a_collision(zone, con, tmp_path, monkeypatch):
    """Catches the second load comparing paths as spelled: the same file must stay the same
    file whether the root was given relative or absolute (R1.2, R1.4)."""
    land_one(zone)
    assert load_landing_zone(con, zone) == 1
    monkeypatch.chdir(tmp_path)
    assert load_landing_zone(con, LandingZone(root="raw")) == 0


def test_second_load_is_a_no_op(zone, con):
    land_one(zone)
    assert load_landing_zone(con, zone) == 1
    assert load_landing_zone(con, zone) == 0
    assert con.execute("select count(*) from raw.captures").fetchone()[0] == 1


def test_new_snapshot_of_same_request_is_a_new_row(zone, con):
    land_one(zone, name="fetched_at=20260926T000000Z")
    load_landing_zone(con, zone)
    land_one(zone, name="fetched_at=20260927T000000Z", payload={"dates": [1]})
    assert load_landing_zone(con, zone) == 1
    counts = con.execute("select count(*), count(distinct fetched_at) from raw.captures").fetchone()
    assert counts == (2, 2), "snapshots accumulate; history is never overwritten"


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
    sources = con.execute("select distinct source from raw.captures").fetchall()
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
    return con.execute("select count(*) from raw.captures").fetchone()[0]


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
        "select request_path, partitions from raw.captures order by request_path"
    ).fetchall()
    assert len({path for path, _ in rows}) == 4
    for path, partitions in rows:
        parsed = json.loads(partitions)
        assert f"/seasons/{parsed['season']}/segments/0/leagues/{parsed['league_id']}" in path


def test_partitions_are_stored_as_written(zone, con):
    """Catches partitions being re-ordered or stringified on the way into the table."""
    land_capture(zone, league="111", season=2026)
    load_landing_zone(con, zone)
    stored = con.execute("select partitions::varchar from raw.captures").fetchone()[0]
    assert stored == json.dumps({"season": 2026, "league_id": "111"})


def duplicate_into_other_folder(zone):
    """Copy the one landed capture under a different partition folder: same full key.

    Returns the two payload.json paths as the loader stores them: relative to the root, in
    posix form.
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
    return (
        (original / "payload.json").relative_to(zone.root).as_posix(),
        (copy / "payload.json").relative_to(zone.root).as_posix(),
    )


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
    assert original in message
    assert copy in message
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
    assert original in str(excinfo.value)
    assert copy in str(excinfo.value)
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
    request_path varchar not null,
    request_key varchar not null,
    fetched_at varchar not null,
    partitions json not null,
    payload json not null,
    file_path varchar not null,
    primary key (source, endpoint, request_path, request_key, fetched_at)
);
insert into raw.api_responses values ('mlb', 'schedule', '/p', 'a=1', 'T', '{}', '{}', '/x.json');
"""


def test_a_warehouse_holding_api_responses_is_refused_and_left_alone(zone, con):
    """Catches a loader that writes a manifest beside the old payload table, or alters it:
    a warehouse of the old shape is rebuilt into a new file (R1.5)."""
    con.execute(OLD_TABLE)
    land_one(zone)
    with pytest.raises(RawSchemaOutdated) as excinfo:
        load_landing_zone(con, zone)
    assert "--db" in str(excinfo.value)
    assert "raw.api_responses" in str(excinfo.value)
    tables = con.execute(
        "select table_name from information_schema.tables where table_schema = 'raw'"
    ).fetchall()
    assert tables == [("api_responses",)], "raw.captures was not created"
    assert con.execute("select * from raw.api_responses").fetchall() == [
        ("mlb", "schedule", "/p", "a=1", "T", "{}", "{}", "/x.json")
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


@pytest.mark.parametrize(
    "stamp", ["20260101T000000", "20260101T000000Zextra", "2026-01-01T00:00:00Z", "20260101"]
)
def test_a_committed_capture_with_a_malformed_stamp_fails_the_load(zone, con, stamp):
    """Catches a stamp the pipeline cannot parse reaching the manifest, where it would
    surface much later as a dbt error naming no file (R1.7). The capture is committed: its
    sidecar and directory agree, so only the loader's own check refuses it."""
    land_one(zone)
    bad = land_one(zone, name=f"fetched_at={stamp}")
    assert zone.check(bad) is None, "the test capture must be committed"
    with pytest.raises(ValueError) as excinfo:
        load_landing_zone(con, zone)
    assert f"fetched_at={stamp}" in str(excinfo.value)
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
    rows = con.execute("select source, endpoint, request_key from raw.captures").fetchall()
    assert rows == [("mlb", "players", "season=2026")]


# -- interruption and key checks against the table ----------------------------------------


class InsertThenFail:
    """A DuckDB connection whose executemany inserts and then raises, as a load killed
    after its insert but before its commit would."""

    def __init__(self, con):
        self._con = con

    def executemany(self, sql, rows):
        self._con.executemany(sql, rows)
        raise RuntimeError("the load was interrupted")

    def __getattr__(self, name):
        return getattr(self._con, name)


def land_days(zone, count):
    return [
        land_one(zone, name=f"fetched_at=202609{day:02d}T000000Z") for day in range(1, count + 1)
    ]


def test_a_load_interrupted_after_its_insert_leaves_no_row_of_the_run(zone, con):
    """Catches a partial load: the old loader inserted row by row with no transaction, and
    a load that died left 1,896 of 2,431 boxscores of a season in the table (R1.3)."""
    land_days(zone, 2)
    load_landing_zone(con, zone)
    land_one(zone, name="fetched_at=20260910T000000Z")
    land_one(zone, name="fetched_at=20260911T000000Z")
    with pytest.raises(RuntimeError, match="interrupted"):
        load_landing_zone(InsertThenFail(con), zone)
    assert row_count(con) == 2, "nothing from an interrupted run is inserted"
    assert load_landing_zone(con, zone) == 2
    assert row_count(con) == 4


def test_a_file_with_the_key_of_a_row_whose_own_file_is_gone_still_fails(zone, con):
    """Catches the check against the table being dropped: when the file a row was loaded
    from is no longer in the landing zone (moved to the quarantine, say), another file with
    that key cannot be told from it by looking at the files alone. Found by breaking that
    check and seeing every other collision test stay green (#149)."""
    land_capture(zone, league="111", season=2026)
    load_landing_zone(con, zone)
    original, copy = duplicate_into_other_folder(zone)
    shutil.rmtree((zone.root / original).parent)
    with pytest.raises(RawKeyCollision) as excinfo:
        load_landing_zone(con, zone)
    assert original in str(excinfo.value) and copy in str(excinfo.value)
    assert row_count(con) == 1
