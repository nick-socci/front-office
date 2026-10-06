"""Tests for the fixture builder's allowlist.

This is the mechanism that keeps other people's data out of a public repo, so it is
tested directly rather than trusted. The rule: a field nobody listed cannot appear in a
fixture, no matter where it sits in the payload.
"""

import json
from pathlib import Path

import pytest

import make_fixtures
from front_office.landing import LandingZone
from make_fixtures import pick, rebuild


def test_rebuild_keeps_only_allowlisted_fields():
    source = {
        "gamePk": 1,
        "link": "/api/v1.1/game/1/feed/live",
        "status": {"abstractGameState": "Final", "codedGameState": "F"},
    }
    assert rebuild(source, ("gamePk", "status.abstractGameState")) == {
        "gamePk": 1,
        "status": {"abstractGameState": "Final"},
    }


def test_rebuild_drops_unlisted_nested_containers_entirely():
    source = {"teams": {"home": {"team": {"id": 5, "name": "X"}, "probablePitcher": {"id": 99}}}}
    rebuilt = rebuild(source, ("teams.home.team.id",))
    assert rebuilt == {"teams": {"home": {"team": {"id": 5}}}}
    assert "probablePitcher" not in rebuilt["teams"]["home"]
    assert "name" not in rebuilt["teams"]["home"]["team"]


def test_rebuild_skips_absent_fields_without_inventing_keys():
    # rescheduledFrom is present only on affected games; absence must not create a null.
    assert rebuild({"gamePk": 1}, ("gamePk", "rescheduledFrom")) == {"gamePk": 1}


def test_rebuild_of_an_espn_shaped_payload_omits_member_identity():
    """A shape resembling ESPN's: names and member GUIDs must not survive."""
    source = {
        "id": 7,
        "abbrev": "TM7",
        "name": "Real Team Name",
        "primaryOwner": "{ABC12345-1234-1234-1234-1234567890AB}",
        "members": [{"firstName": "A", "lastName": "B", "id": "{GUID}"}],
        "record": {"overall": {"wins": 15, "losses": 3}},
    }
    rebuilt = rebuild(source, ("id", "record.overall.wins", "record.overall.losses"))
    assert rebuilt == {"id": 7, "record": {"overall": {"wins": 15, "losses": 3}}}
    serialized = str(rebuilt)
    assert "Real Team Name" not in serialized
    assert "members" not in serialized
    assert "primaryOwner" not in serialized


def test_pick_returns_none_when_path_runs_into_a_non_dict():
    assert pick({"teams": [1, 2]}, "teams.home.id") is None


# -- the landing layout: real captures are read, fixtures are written, as directories ------------


@pytest.fixture
def roots(tmp_path, monkeypatch):
    """A pretend real landing zone and an empty fixture root, in place of data/raw and fixtures."""
    raw, fixtures = tmp_path / "raw", tmp_path / "fixtures"
    monkeypatch.setattr(make_fixtures, "RAW_ROOT", raw)
    monkeypatch.setattr(make_fixtures, "FIXTURE_ROOT", fixtures)
    monkeypatch.setattr(make_fixtures, "REPO_ROOT", tmp_path)
    return raw, fixtures


def land(raw, source, endpoint, partitions, stamp, payload):
    """Land one committed capture the way the package does."""
    return LandingZone(raw).write(
        source=source,
        endpoint=endpoint,
        partitions=partitions,
        name=f"fetched_at={stamp}",
        payload=payload,
        request={"url": "https://example.test/x", "params": {"k": 1}},
        fetched_at=stamp,
    )


def test_write_fixture_writes_a_capture_directory_with_unchanged_contents(roots):
    """Catches a fixture written in the old layout, or with a changed byte layout: the
    payload is indented by one and ends in a newline, the sidecar by two, with no size or
    checksum added (old-style sidecars are valid captures)."""
    _raw, fixtures = roots
    path = make_fixtures.write_fixture(
        source="espn",
        endpoint="teams",
        partitions={"season": 2026, "league_id": "111111"},
        payload={"a": 1},
        request={"url": "https://x/", "params": {"view": "mTeam"}},
    )
    directory = fixtures / "espn/teams/season=2026/league_id=111111/fetched_at=20260430T160000Z"
    assert path == directory / "payload.json"
    assert sorted(p.name for p in directory.iterdir()) == ["meta.json", "payload.json"]
    assert path.read_text() == json.dumps({"a": 1}, indent=1) + "\n"
    meta = json.loads((directory / "meta.json").read_text())
    assert list(meta) == [
        "source",
        "endpoint",
        "partitions",
        "url",
        "params",
        "request_key",
        "fetched_at",
    ]
    assert meta["request_key"] == "view=mTeam"
    assert LandingZone(fixtures).check(directory) is None


def test_latest_landed_reads_the_newest_committed_capture_and_ignores_debris(roots):
    """Catches a reader that takes a loose old-layout payload or a temporary directory as
    the newest capture."""
    raw, _fixtures = roots
    land(raw, "mlb", "schedule", {"season": 2026}, "20260101T000000Z", {"which": "old"})
    newest = land(raw, "mlb", "schedule", {"season": 2026}, "20260102T000000Z", {"which": "new"})
    folder = newest.parent
    (folder / "fetched_at=20260103T000000Z.json").write_text('{"which": "loose"}')
    temp = folder / "fetched_at=20260104T000000Z.tmp-9"
    temp.mkdir()
    (temp / "payload.json").write_text('{"which": "temp"}')
    found = make_fixtures.latest_landed("mlb", "schedule")
    assert found == newest / "payload.json"
    assert json.loads(found.read_text()) == {"which": "new"}


def test_latest_espn_selects_a_scoring_period_exactly(roots):
    """Catches `scoring_period=10` matching period 100's captures."""
    raw, _fixtures = roots
    base = {"season": 2026, "league_id": "7"}
    land(raw, "espn", "roster", {**base, "scoring_period": 10}, "20260101T000000Z", {"p": 10})
    land(raw, "espn", "roster", {**base, "scoring_period": 100}, "20260101T000000Z", {"p": 100})
    land(raw, "espn", "roster", {**base, "scoring_period": 100}, "20260102T000000Z", {"p": "100b"})
    assert make_fixtures.latest_espn("roster", scoring_period=10) == {"p": 10}
    assert make_fixtures.latest_espn("roster", scoring_period=100) == {"p": "100b"}
    assert make_fixtures.latest_espn("roster") == {"p": "100b"}
    with pytest.raises(SystemExit):
        make_fixtures.latest_espn("roster", scoring_period=5)


def test_the_first_transactions_page_is_offset_zero_of_the_newest_run(roots):
    """Catches offset=0 being found by a path glob of the old layout, or a later page taken."""
    raw, _fixtures = roots
    base = {"season": 2026, "league_id": "7"}
    land(raw, "espn", "transactions", {**base, "offset": 0}, "20260101T000000Z", {"page": "old0"})
    land(raw, "espn", "transactions", {**base, "offset": 0}, "20260102T000000Z", {"page": "new0"})
    land(raw, "espn", "transactions", {**base, "offset": 2000}, "20260103T000000Z", {"page": "p1"})
    assert make_fixtures.newest_transactions_first_page() == {"page": "new0"}


def test_boxscore_fixtures_and_the_correction_are_read_and_written_as_directories(roots):
    """Catches the boxscore path (a game folder of captures, then a correction built from
    the fixture just written) still assuming loose files."""
    raw, fixtures = roots
    final = {"status": {"detailedState": "Final"}, "gamePk": 5}
    land(
        raw,
        "mlb",
        "schedule",
        {"season": 2026, "game_type": "R"},
        "20260501T000000Z",
        {"dates": [{"date": "2026-04-29", "games": [final]}]},
    )
    side = {
        "team": {"id": 1},
        "teamStats": {"batting": {"hits": 3, "runs": 1, "atBats": 9}},
        "players": {
            "ID1": {"stats": {"batting": {"hits": 3, "runs": 1, "atBats": 9, "gamesPlayed": 1}}}
        },
    }
    land(
        raw,
        "mlb",
        "boxscore",
        {"season": 2026, "game_pk": 5},
        "20260501T000000Z",
        {"teams": {"home": side, "away": side}},
    )
    written = make_fixtures.build_mlb_boxscores(("2026-04-29",))
    assert [p.parent.name for p in written] == [
        "fetched_at=20260430T160000Z",
        f"fetched_at={make_fixtures.CORRECTION_FETCHED_AT}",
    ]
    zone = LandingZone(fixtures)
    assert [c.directory for c in zone.committed(source="mlb", endpoint="boxscore")] == [
        p.parent for p in written
    ]
    corrected = json.loads(written[1].read_text())
    assert corrected["teams"]["home"]["teamStats"]["batting"]["hits"] == 4
    assert Path(written[1].parent / "meta.json").exists()
