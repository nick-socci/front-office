"""Tests for the landing zone: path conventions, atomic writes, skip logic."""

import json

import pytest

from front_office.landing import LandingZone


@pytest.fixture
def zone(tmp_path):
    return LandingZone(root=tmp_path)


def test_path_convention_snapshot(zone, tmp_path):
    path = zone.path_for(
        source="espn",
        endpoint="settings",
        partitions={"season": 2026, "league_id": 73677},
        name="fetched_at=20260926T142726Z",
    )
    assert path == (
        tmp_path / "espn/settings/season=2026/league_id=73677/fetched_at=20260926T142726Z.json"
    )


def test_path_convention_immutable_entity(zone, tmp_path):
    path = zone.path_for(
        source="mlb",
        endpoint="boxscore",
        partitions={"season": 2026},
        name="game_pk=746123",
    )
    assert path == tmp_path / "mlb/boxscore/season=2026/game_pk=746123.json"


def test_write_lands_payload_and_sidecar(zone):
    path = zone.write(
        source="mlb",
        endpoint="schedule",
        partitions={"season": 2026},
        name="fetched_at=20260926T000000Z",
        payload={"dates": []},
        request={"url": "https://statsapi.mlb.com/api/v1/schedule", "params": {"season": "2026"}},
        fetched_at="20260926T000000Z",
    )
    assert json.loads(path.read_text()) == {"dates": []}
    meta = json.loads(path.with_suffix(".meta.json").read_text())
    assert meta["url"] == "https://statsapi.mlb.com/api/v1/schedule"
    assert meta["request_key"] == "season=2026"
    assert meta["fetched_at"] == "20260926T000000Z"
    assert meta["source"] == "mlb"


def test_request_key_is_canonical_regardless_of_param_order(zone):
    first = zone.request_key({"b": 2, "a": 1})
    second = zone.request_key({"a": 1, "b": 2})
    assert first == second == "a=1&b=2"


def test_crash_mid_write_leaves_no_partial_file(zone, tmp_path, monkeypatch):
    def explode(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr("pathlib.Path.replace", explode)
    with pytest.raises(OSError):
        zone.write(
            source="mlb",
            endpoint="schedule",
            partitions={"season": 2026},
            name="fetched_at=20260926T000000Z",
            payload={"dates": []},
            request={"url": "https://example.test", "params": {}},
            fetched_at="20260926T000000Z",
        )
    landed = list(tmp_path.rglob("*.json"))
    leftovers = list(tmp_path.rglob("*.tmp*"))
    assert landed == [], "a failed write must not leave a readable .json file"
    assert leftovers == [], "the temp file must be cleaned up"


def test_has_landed_detects_existing_entity(zone):
    args = dict(source="mlb", endpoint="boxscore", partitions={"season": 2026}, name="game_pk=1")
    assert zone.has_landed(**args) is False
    zone.write(
        **args,
        payload={},
        request={"url": "https://example.test", "params": {"gamePk": 1}},
        fetched_at="20260926T000000Z",
    )
    assert zone.has_landed(**args) is True


def test_iter_landed_yields_payload_and_meta(zone):
    zone.write(
        source="mlb",
        endpoint="schedule",
        partitions={"season": 2026},
        name="fetched_at=20260926T000000Z",
        payload={"dates": [{"date": "2026-04-01"}]},
        request={"url": "https://example.test", "params": {"season": "2026"}},
        fetched_at="20260926T000000Z",
    )
    landed = list(zone.iter_landed())
    assert len(landed) == 1
    assert landed[0].meta["endpoint"] == "schedule"
    assert landed[0].payload["dates"][0]["date"] == "2026-04-01"


def test_iter_landed_skips_sidecars(zone):
    zone.write(
        source="mlb",
        endpoint="schedule",
        partitions={"season": 2026},
        name="fetched_at=20260926T000000Z",
        payload={},
        request={"url": "https://example.test", "params": {}},
        fetched_at="20260926T000000Z",
    )
    assert len(list(zone.iter_landed())) == 1, "the .meta.json file is not a landed response"


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
