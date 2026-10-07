"""Tests for the one definition of a committed capture, and everything built on it."""

import datetime as dt
import json
import shutil
from pathlib import Path

import duckdb
import pytest

from front_office.espn import rosters
from front_office.landing import LandingZone, PayloadNotJson
from front_office.load import load_landing_zone
from front_office.mlb import boxscore

STAMP = "20260926T000000Z"
BOX = {"source": "mlb", "endpoint": "boxscore", "partitions": {"season": 2026, "game_pk": 1}}


@pytest.fixture
def zone(tmp_path):
    return LandingZone(root=tmp_path / "raw")


def land(zone, *, stamp=STAMP, payload=None, source_status=None, **entity):
    entity = entity or BOX
    return zone.write(
        source=entity["source"],
        endpoint=entity["endpoint"],
        partitions=entity["partitions"],
        name=f"fetched_at={stamp}",
        payload={"x": 1} if payload is None else payload,
        request={"url": "https://example.test/x", "params": {"gamePk": 1}},
        fetched_at=stamp,
        source_status=source_status,
    )


def edit_meta(path, **changes):
    meta = json.loads((path / "meta.json").read_text())
    for key, value in changes.items():
        if value is DELETE:
            del meta[key]
        else:
            meta[key] = value
    (path / "meta.json").write_text(json.dumps(meta))


DELETE = object()


def has_landed(zone):
    return zone.has_landed(**BOX)


# -- R2.1 -------------------------------------------------------------------------------


def _remove_payload(path):
    (path / "payload.json").unlink()


def _remove_meta(path):
    (path / "meta.json").unlink()


def _extra_file(path):
    (path / "notes.txt").write_text("x")


def _meta_not_json(path):
    (path / "meta.json").write_text("{not json")


def _meta_lacks_field(path):
    edit_meta(path, url=DELETE)


def _meta_empty_url(path):
    edit_meta(path, url="")


def _meta_partitions_not_mapping(path):
    edit_meta(path, partitions=[1, 2])


def _other_partition(path):
    edit_meta(path, partitions={"season": 2026, "game_pk": 2})


def _other_partition_order(path):
    edit_meta(path, partitions={"game_pk": 1, "season": 2026})


def _other_source(path):
    edit_meta(path, source="espn")


def _other_stamp(path):
    edit_meta(path, fetched_at="20260101T000000Z")


def _other_size(path):
    edit_meta(path, payload_bytes=1)


@pytest.mark.parametrize(
    "damage",
    [
        _remove_payload,
        _remove_meta,
        _extra_file,
        _meta_not_json,
        _meta_lacks_field,
        _meta_empty_url,
        _meta_partitions_not_mapping,
        _other_partition,
        _other_partition_order,
        _other_source,
        _other_stamp,
        _other_size,
    ],
)
def test_a_capture_that_does_not_agree_is_not_committed(zone, damage):
    """Catches a capture that exists but is broken, or filed under the wrong entity, being
    counted as landed for the entity whose folder it sits in (R2.1)."""
    path = land(zone)
    assert zone.check(path) is None
    assert has_landed(zone)
    damage(path)
    assert isinstance(zone.check(path), str)
    assert not has_landed(zone)
    assert list(zone.committed()) == []


def test_a_source_status_of_any_shape_does_not_change_whether_a_capture_is_committed(zone):
    """Catches a new way for a capture to be quarantined: the check must not look inside
    source_status, present, absent or malformed (R1.4)."""
    plain = land(zone, stamp="20260926T000001Z")
    given = land(
        zone,
        stamp="20260926T000002Z",
        source_status={"latest_scoring_period": 5, "final_scoring_period": 180},
    )
    malformed = land(zone, stamp="20260926T000003Z", source_status={"latest_scoring_period": 5})
    edit_meta(malformed, source_status=["not", "a", "mapping"])  # size and hash stay valid
    for path in (plain, given, malformed):
        assert zone.check(path) is None
        assert zone.check(path, deep=True) is None
    assert len(list(zone.committed())) == 3


def test_an_empty_capture_directory_is_not_committed(zone):
    """Catches an empty fetched_at= directory counting as landed."""
    path = land(zone)
    shutil.rmtree(path)
    path.mkdir()
    assert isinstance(zone.check(path), str)
    assert not has_landed(zone)


def test_a_directory_not_named_fetched_at_is_not_committed(zone):
    """Catches a copy of a capture under another directory name being read."""
    path = land(zone)
    copy = path.with_name("copy")
    shutil.copytree(path, copy)
    shutil.rmtree(path)
    assert isinstance(zone.check(copy), str)
    assert list(zone.committed()) == []


def test_has_landed_looks_only_at_that_entitys_folder(zone):
    """Catches an entity counting as landed because another entity has a capture."""
    land(zone)
    assert not zone.has_landed(
        source="mlb", endpoint="boxscore", partitions={"season": 2026, "game_pk": 2}
    )
    assert not zone.has_landed(source="mlb", endpoint="boxscore", partitions={"season": 2026})


def test_committed_is_sorted_and_can_be_narrowed(zone):
    """Catches unsorted output (the schedule reader and the loader rely on it)."""
    land(zone, stamp="20260927T000000Z")
    land(zone, stamp=STAMP)
    land(zone, source="mlb", endpoint="schedule", partitions={"season": 2026}, stamp=STAMP)
    everything = [c.directory for c in zone.committed()]
    assert everything == sorted(everything) and len(everything) == 3
    assert len(list(zone.committed(source="mlb", endpoint="boxscore"))) == 2
    narrowed = list(zone.committed(**BOX))
    assert [c.directory.name for c in narrowed] == [
        f"fetched_at={STAMP}",
        "fetched_at=20260927T000000Z",
    ]
    assert narrowed[0].meta["endpoint"] == "boxscore"
    assert narrowed[0].payload == {"x": 1}


# -- R2.2 -------------------------------------------------------------------------------

SCHEDULED = boxscore.ScheduledGame(
    game_pk=1,
    season=2026,
    official_date=dt.date(2026, 4, 1),
    state="Final",
    detailed_state="Final",
)
TODAY = dt.date(2026, 9, 26)


def test_a_settled_game_with_only_a_temp_directory_needs_fetching(zone):
    """Catches debris from a killed run counting as landed (R2.2)."""
    folder = zone.root / "mlb/boxscore/season=2026/game_pk=1"
    (folder / f"fetched_at={STAMP}.tmp-99").mkdir(parents=True)
    assert boxscore.needs_fetch(SCHEDULED, zone, today=TODAY) is True


def test_a_settled_game_with_only_a_loose_old_layout_file_needs_fetching(zone):
    """Catches the old layout's lone payload freezing an entity (the original orphan bug)."""
    folder = zone.root / "mlb/boxscore/season=2026/game_pk=1"
    folder.mkdir(parents=True)
    (folder / f"fetched_at={STAMP}.json").write_text("{}")
    assert boxscore.needs_fetch(SCHEDULED, zone, today=TODAY) is True


def test_a_settled_game_with_a_committed_capture_does_not_need_fetching(zone):
    land(zone)
    assert boxscore.needs_fetch(SCHEDULED, zone, today=TODAY) is False


ROSTER = {
    "source": "espn",
    "endpoint": "roster",
    "partitions": {"season": 2026, "league_id": "9", "scoring_period": 1},
}
CLOSED = {"latestScoringPeriod": 5, "finalScoringPeriod": 5}


def _needs_roster(zone):
    return rosters.needs_fetch(zone, season=2026, league_id="9", period=1, status=CLOSED)


def test_a_closed_roster_period_with_only_debris_needs_fetching(zone):
    """Catches debris counting as a landed roster (rosters cannot be re-created later)."""
    folder = zone.root / "espn/roster/season=2026/league_id=9/scoring_period=1"
    (folder / f"fetched_at={STAMP}.tmp-99").mkdir(parents=True)
    (folder / f"fetched_at={STAMP}.json").write_text("{}")
    assert _needs_roster(zone) is True
    land(zone, **ROSTER)
    assert _needs_roster(zone) is False


def test_needs_fetch_reads_no_payload(zone, monkeypatch):
    """Catches the fetch logic reading every payload to decide what has landed (R2.6)."""
    path = land(zone)
    land(zone, **ROSTER)
    real_read_bytes = Path.read_bytes
    real_read_text = Path.read_text
    real_open = Path.open

    def guard(real):
        def wrapped(self, *args, **kwargs):
            if self.name == "payload.json":
                raise AssertionError(f"payload read: {self}")
            return real(self, *args, **kwargs)

        return wrapped

    monkeypatch.setattr(Path, "read_bytes", guard(real_read_bytes))
    monkeypatch.setattr(Path, "read_text", guard(real_read_text))
    monkeypatch.setattr(Path, "open", guard(real_open))
    assert boxscore.needs_fetch(SCHEDULED, zone, today=TODAY) is False
    assert _needs_roster(zone) is False
    assert zone.check(path) is None


# -- R2.3, R2.4 -------------------------------------------------------------------------


@pytest.fixture
def con():
    with duckdb.connect(":memory:") as con:
        yield con


def test_the_loader_inserts_nothing_for_debris(zone, con):
    """Catches the loader reading a temporary directory or an old-layout file (R2.3)."""
    folder = zone.root / "mlb/boxscore/season=2026/game_pk=1"
    (folder / f"fetched_at={STAMP}.tmp-99").mkdir(parents=True)
    (folder / f"fetched_at={STAMP}.tmp-99" / "payload.json").write_text("{}")
    (folder / "fetched_at=20260101T000000Z.json").write_text("{}")
    (folder / "fetched_at=20260101T000000Z.meta.json").write_text("{}")
    assert load_landing_zone(con, zone) == 0


def _schedule(zone, stamp, game_pks):
    games = [
        {
            "gamePk": pk,
            "season": "2026",
            "officialDate": "2026-04-01",
            "status": {"abstractGameState": "Final", "detailedState": "Final"},
        }
        for pk in game_pks
    ]
    return zone.write(
        source="mlb",
        endpoint="schedule",
        partitions={"season": 2026},
        name=f"fetched_at={stamp}",
        payload={"dates": [{"games": games}]},
        request={"url": "https://example.test/schedule", "params": {"season": 2026}},
        fetched_at=stamp,
    )


def test_the_newest_committed_schedule_is_used_when_a_newer_one_is_invalid(zone):
    """Catches the newest schedule being picked by name when it is not a capture (R2.4)."""
    _schedule(zone, "20260901T000000Z", [1, 2])
    newer = _schedule(zone, "20260902T000000Z", [1, 2, 3])
    (newer / "meta.json").unlink()
    assert [g.game_pk for g in boxscore.games_from_landed_schedule(zone, season=2026)] == [1, 2]


# -- R2.5, R2.6, R2.7 ------------------------------------------------------------------


def test_a_sidecar_without_size_or_hash_is_committed(zone):
    """Catches captures landed before this change being rejected (R2.5)."""
    path = land(zone)
    meta = json.loads((path / "meta.json").read_text())
    del meta["payload_bytes"], meta["payload_sha256"]
    (path / "meta.json").write_text(json.dumps(meta))
    assert zone.check(path) is None
    assert zone.check(path, deep=True) is None
    assert has_landed(zone)


def test_deep_reports_what_shallow_does_not(zone):
    """Catches corruption at rest going unnoticed, or the shallow check getting slow (R2.6)."""
    garbled = land(zone, stamp="20260901T000000Z")
    (garbled / "payload.json").write_bytes(b"x" * (garbled / "payload.json").stat().st_size)
    flipped = land(zone, stamp="20260902T000000Z", payload={"x": 1})
    (flipped / "payload.json").write_text('{"x": 2}')
    for path in (garbled, flipped):
        assert zone.check(path) is None, "same size, so shallow still says committed"
    assert "not valid JSON" in zone.check(garbled, deep=True)
    assert "SHA-256" in zone.check(flipped, deep=True)


def test_the_loader_fails_naming_a_committed_capture_whose_payload_is_not_json(zone, con):
    """Catches a silently skipped capture (R2.7), and a partial insert before the failure."""
    land(zone, stamp="20260901T000000Z")
    bad = land(zone, stamp="20260902T000000Z")
    size = (bad / "payload.json").stat().st_size
    (bad / "payload.json").write_bytes(b"x" * size)
    with pytest.raises(PayloadNotJson) as excinfo:
        load_landing_zone(con, zone)
    assert str(bad / "payload.json") in str(excinfo.value)
    assert con.execute("select count(*) from raw.api_responses").fetchone()[0] == 0


# -- R2.8 -------------------------------------------------------------------------------


def test_an_entry_removed_between_listing_and_reading_is_skipped(zone, con, monkeypatch):
    """Catches a reader crashing because a sweep moved a capture mid-run (R2.8)."""
    land(zone, stamp="20260901T000000Z")
    doomed = land(zone, stamp="20260902T000000Z")
    land(zone, stamp="20260903T000000Z")
    real_dirs = LandingZone._capture_dirs

    def listing_then_vanishing(folder, *, recurse):
        for entry in real_dirs(folder, recurse=recurse):
            if entry == doomed and doomed.exists():
                shutil.rmtree(doomed)
            yield entry

    monkeypatch.setattr(LandingZone, "_capture_dirs", staticmethod(listing_then_vanishing))
    assert [c.directory.name for c in zone.committed()] == [
        "fetched_at=20260901T000000Z",
        "fetched_at=20260903T000000Z",
    ]


def test_every_reader_survives_a_capture_vanishing_after_it_was_checked(zone, con, monkeypatch):
    """Catches iter_landed and the loader crashing when payload.json goes after the check."""
    land(zone, stamp="20260901T000000Z")
    doomed = land(zone, stamp="20260902T000000Z")
    real_check = LandingZone.check

    def check_then_vanish(self, capture_dir, deep=False):
        result = real_check(self, capture_dir, deep)
        if capture_dir == doomed and doomed.exists():
            shutil.rmtree(doomed)
        return result

    monkeypatch.setattr(LandingZone, "check", check_then_vanish)
    assert load_landing_zone(con, zone) == 1


def test_a_vanished_directory_is_not_committed(zone):
    """Catches check raising for a path that no longer exists."""
    path = land(zone)
    shutil.rmtree(path)
    assert isinstance(zone.check(path), str)
    assert list(zone.committed(**BOX)) == []


# -- scan -------------------------------------------------------------------------------


def test_scan_classifies_each_kind_and_not_structure(zone):
    """Catches a kind misclassified, structure folders reported, or capture contents listed."""
    good = land(zone)
    invalid = good.with_name("fetched_at=20260101T000000Z")
    invalid.mkdir()
    temp = good.with_name("fetched_at=20260102T000000Z.tmp-7")
    temp.mkdir()
    (temp / "payload.json").write_text("{}")
    loose = good.parent.parent / "game_pk=2" / "fetched_at=20260101T000000Z.json"
    loose.parent.mkdir()
    loose.write_text("{}")
    empty = zone.root / "espn/settings/season=2026"
    empty.mkdir(parents=True)

    found = {(entry.kind, entry.path) for entry in zone.scan()}
    assert found == {
        ("committed", good),
        ("invalid", invalid),
        ("temp", temp),
        ("loose", loose),
        ("empty", empty),
    }
    paths = [entry.path for entry in zone.scan()]
    assert paths == sorted(paths)


def test_scan_of_an_empty_or_missing_root_reports_nothing(zone):
    assert list(zone.scan()) == []
    zone.root.mkdir()
    assert list(zone.scan()) == []


# -- iter_landed ------------------------------------------------------------------------


def test_iter_landed_yields_committed_captures_with_the_payload_path(zone):
    """Catches iter_landed losing `.path` (the loader's file_path) or yielding debris."""
    path = land(zone)
    (path.parent / "fetched_at=20260101T000000Z.tmp-1").mkdir()
    landed = list(zone.iter_landed())
    assert [r.path for r in landed] == [path / "payload.json"]
    assert landed[0].meta["endpoint"] == "boxscore"
    assert landed[0].payload == {"x": 1}
