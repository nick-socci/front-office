"""Tests for writing the landing zone: a capture is a directory published by one rename."""

import hashlib
import json
import os
from pathlib import Path

import pytest

from front_office.landing import LandingCollision, LandingZone

STAMP = "20260926T000000Z"


@pytest.fixture
def zone(tmp_path):
    return LandingZone(root=tmp_path)


def write(zone, *, payload=None, stamp=STAMP, partitions=None, endpoint="schedule"):
    return zone.write(
        source="mlb",
        endpoint=endpoint,
        partitions=partitions if partitions is not None else {"season": 2026},
        name=f"fetched_at={stamp}",
        payload={"dates": []} if payload is None else payload,
        request={"url": "https://statsapi.mlb.com/api/v1/schedule", "params": {"season": "2026"}},
        fetched_at=stamp,
    )


def entity_folder(zone):
    return zone.root / "mlb/schedule/season=2026"


def test_path_convention_snapshot(zone, tmp_path):
    """Catches a capture path that is still a file stem rather than a directory."""
    path = zone.path_for(
        source="espn",
        endpoint="settings",
        partitions={"season": 2026, "league_id": 73677},
        name="fetched_at=20260926T142726Z",
    )
    assert path == (
        tmp_path / "espn/settings/season=2026/league_id=73677/fetched_at=20260926T142726Z"
    )


def test_path_convention_entity(zone, tmp_path):
    """Catches partition folders losing their order or the fetch stamp leaving the path."""
    path = zone.path_for(
        source="mlb",
        endpoint="boxscore",
        partitions={"season": 2026, "game_pk": 746123},
        name="fetched_at=20260926T000000Z",
    )
    assert path == tmp_path / "mlb/boxscore/season=2026/game_pk=746123/fetched_at=20260926T000000Z"


def test_a_capture_is_a_directory_of_exactly_two_files(zone):
    """Catches a capture with a stray file, or a sidecar missing the old fields or their
    order, or one whose recorded size or hash is not that of the payload on disk (R1.5)."""
    path = write(zone, payload={"dates": [1, 2]})
    assert path == entity_folder(zone) / f"fetched_at={STAMP}"
    assert sorted(p.name for p in path.iterdir()) == ["meta.json", "payload.json"]
    assert json.loads((path / "payload.json").read_text()) == {"dates": [1, 2]}

    meta = json.loads((path / "meta.json").read_text())
    assert list(meta) == [
        "source",
        "endpoint",
        "partitions",
        "url",
        "params",
        "request_key",
        "fetched_at",
        "payload_bytes",
        "payload_sha256",
    ]
    assert meta["request_key"] == "season=2026"
    assert meta["url"] == "https://statsapi.mlb.com/api/v1/schedule"
    on_disk = (path / "payload.json").read_bytes()
    assert meta["payload_bytes"] == len(on_disk)
    assert meta["payload_sha256"] == hashlib.sha256(on_disk).hexdigest()


def test_the_final_directory_does_not_exist_until_the_rename(zone, monkeypatch):
    """Catches a capture visible half-built: the final name must appear only by the rename,
    and the source of the rename must already hold both files."""
    final = entity_folder(zone) / f"fetched_at={STAMP}"
    seen = {}
    real_rename = os.rename

    def watching_rename(src, dst):
        seen["final_exists"] = Path(dst).exists()
        seen["src_files"] = sorted(p.name for p in Path(src).iterdir())
        seen["src_is_temp"] = ".tmp-" in Path(src).name
        real_rename(src, dst)

    monkeypatch.setattr("front_office.landing.os.rename", watching_rename)
    write(zone)
    assert seen == {
        "final_exists": False,
        "src_files": ["meta.json", "payload.json"],
        "src_is_temp": True,
    }
    assert final.is_dir()


def test_a_second_write_of_the_same_capture_is_a_collision(zone):
    """Catches the old silent overwrite (R1.3): the first capture must survive untouched."""
    path = write(zone, payload={"first": True})
    before = {name: (path / name).read_bytes() for name in ("payload.json", "meta.json")}
    with pytest.raises(LandingCollision) as excinfo:
        write(zone, payload={"second": True})
    assert str(path) in str(excinfo.value)
    assert {name: (path / name).read_bytes() for name in before} == before
    assert [p.name for p in entity_folder(zone).iterdir()] == [path.name], "no temporary left"


def test_an_existing_empty_final_directory_is_also_a_collision(zone):
    """Catches rename silently replacing an empty directory (R1.3)."""
    final = entity_folder(zone) / f"fetched_at={STAMP}"
    final.mkdir(parents=True)
    with pytest.raises(LandingCollision):
        write(zone)
    assert final.is_dir()
    assert list(final.iterdir()) == []
    assert [p.name for p in entity_folder(zone).iterdir()] == [final.name]


def test_a_rename_that_finds_the_destination_non_empty_is_a_collision(zone, monkeypatch):
    """Catches a race (no lock held) surfacing as a bare OSError instead of a collision,
    and leaving the temporary directory behind."""

    def occupied(src, dst):
        raise OSError(39, "Directory not empty")

    monkeypatch.setattr("front_office.landing.os.rename", occupied)
    with pytest.raises(LandingCollision):
        write(zone)
    assert list(zone.root.rglob("*")) == [], "no temporary directory and no new folders"


def _fail_mkdir_of_temp(monkeypatch):
    real = Path.mkdir

    def mkdir(self, *args, **kwargs):
        if ".tmp-" in self.name:
            raise OSError("no space for the temporary directory")
        return real(self, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", mkdir)


def _fail_write_of(monkeypatch, method, filename):
    real = getattr(Path, method)

    def failing(self, *args, **kwargs):
        if self.name == filename:
            raise OSError(f"disk full writing {filename}")
        return real(self, *args, **kwargs)

    monkeypatch.setattr(Path, method, failing)


def _fail_rename(monkeypatch):
    def failing(src, dst):
        raise OSError(5, "input/output error")

    monkeypatch.setattr("front_office.landing.os.rename", failing)


@pytest.mark.parametrize(
    "inject",
    [
        _fail_mkdir_of_temp,
        lambda mp: _fail_write_of(mp, "write_bytes", "payload.json"),
        lambda mp: _fail_write_of(mp, "write_text", "meta.json"),
        _fail_rename,
    ],
    ids=["create_temp_dir", "write_payload", "write_meta", "rename"],
)
def test_a_failure_at_any_step_leaves_nothing_and_re_raises(zone, monkeypatch, inject):
    """Catches a failed write leaving a temporary or final directory a reader or the next
    run could mistake for (part of) a capture (R1.6)."""
    inject(monkeypatch)
    with pytest.raises(OSError):
        write(zone)
    monkeypatch.undo()
    assert list(zone.root.rglob("fetched_at=*")) == []
    folder = entity_folder(zone)
    assert not folder.exists() or list(folder.iterdir()) == []


def test_a_write_can_follow_a_failed_one(zone, monkeypatch):
    """Catches a failure poisoning the entity: after cleanup the same capture writes."""
    _fail_rename(monkeypatch)
    with pytest.raises(OSError):
        write(zone)
    monkeypatch.undo()
    assert write(zone).is_dir()


def test_request_key_is_canonical_regardless_of_param_order(zone):
    first = zone.request_key({"b": 2, "a": 1})
    second = zone.request_key({"a": 1, "b": 2})
    assert first == second == "a=1&b=2"


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        (
            "https://lm-api-reads.fantasy.espn.com/apis/v3/games/flb/seasons/2026/segments/0"
            "/leagues/111111?view=mSettings&view=mStatus",
            "/apis/v3/games/flb/seasons/2026/segments/0/leagues/111111",
        ),
        (
            "https://lm-api-reads.fantasy.espn.com/apis/v3/games/flb/seasons/2026/segments/0"
            "/leagues/111111/communication/?view=kona_league_communication",
            "/apis/v3/games/flb/seasons/2026/segments/0/leagues/111111/communication",
        ),
        ("https://statsapi.mlb.com/api/v1/schedule?sportId=1&season=2026", "/api/v1/schedule"),
        ("https://statsapi.mlb.com/api/v1/game/825108/boxscore", "/api/v1/game/825108/boxscore"),
        ("https://www.smartfantasybaseball.com/PLAYERIDMAPCSV", "/PLAYERIDMAPCSV"),
        ("https://other.example/api/v1/schedule?x=1", "/api/v1/schedule"),
        (None, ""),
        ("", ""),
        ("https://statsapi.mlb.com", ""),
    ],
)
def test_request_path_is_the_url_path_only(url, expected):
    """Catches a request_path that keeps the host, the query string or a trailing slash.

    The path is what tells two ESPN leagues apart, so it must be stable across the
    host and parameters and must not differ by a trailing slash.
    """
    assert LandingZone.request_path(url) == expected


def test_a_failed_first_write_leaves_no_new_folders(zone, monkeypatch):
    """Catches a failed write leaving the source/endpoint/partition folders it created as
    empty directories for the next sweep to report."""
    _fail_write_of(monkeypatch, "write_bytes", "payload.json")
    with pytest.raises(OSError):
        write(zone)
    monkeypatch.undo()
    assert list(zone.root.rglob("*")) == []
    assert zone.root.is_dir(), "the root itself is never removed"


def test_a_failed_write_beside_an_existing_capture_leaves_the_folder_alone(zone, monkeypatch):
    """Catches cleanup removing a folder it did not create, or an existing capture."""
    first = write(zone, stamp="20260926T000000Z")
    before = sorted(str(p) for p in zone.root.rglob("*"))
    _fail_rename(monkeypatch)
    with pytest.raises(OSError):
        write(zone, stamp="20260927T000000Z")
    monkeypatch.undo()
    assert sorted(str(p) for p in zone.root.rglob("*")) == before
    assert first.is_dir()


def test_a_failed_write_removes_only_the_folders_it_created(zone, monkeypatch):
    """Catches cleanup walking above the first folder that already existed."""
    write(zone, partitions={"season": 2025})
    _fail_rename(monkeypatch)
    with pytest.raises(OSError):
        write(zone, partitions={"season": 2026})
    monkeypatch.undo()
    assert [p.name for p in (zone.root / "mlb/schedule").iterdir()] == ["season=2025"]
