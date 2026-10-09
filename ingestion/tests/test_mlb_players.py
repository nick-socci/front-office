"""Tests for the MLB season player list capture (spec 0060, R5.1-R5.4).

No test here touches the network: every client has a fake transport, and every landing zone
lives under tmp_path. The player list is public, so nothing here sets or reads a credential.
"""

import json

import httpx
import pytest
from typer.testing import CliRunner

from front_office.cli import app
from front_office.http_client import HttpClient, SourceLimits
from front_office.landing import LandingZone
from front_office.mlb import players

SEASON = 2026
STAMP = "20261009T000000Z"
PLAYERS = {"copyright": "x", "people": [{"id": 660271, "fullName": "A Player", "batSide": None}]}
SCHEDULE = {
    "dates": [
        {
            "date": "2026-04-14",
            "games": [
                {
                    "gamePk": 11,
                    "season": "2026",
                    "officialDate": "2026-04-14",
                    "gameDate": "2026-04-14T18:00:00Z",
                    "gameType": "R",
                    "status": {"abstractGameState": "Final", "detailedState": "Final"},
                }
            ],
        }
    ]
}
runner = CliRunner()


@pytest.fixture
def zone(tmp_path):
    return LandingZone(root=tmp_path / "raw")


def make_client(handler, source="mlb"):
    return HttpClient(
        source,
        limits=SourceLimits(min_interval_s=0.0, max_attempts=1, backoff_base_s=0.0),
        transport=httpx.MockTransport(handler),
        sleep=lambda _seconds: None,
    )


def land(zone, seen=None):
    def serve(request):
        if seen is not None:
            seen.append(request)
        return httpx.Response(200, json=PLAYERS)

    return players.backfill_players(
        zone=zone, client=make_client(serve), season=SEASON, fetched_at=STAMP
    )


def test_one_request_for_the_season_list(zone):
    """Catches a wrong path, a missing season parameter, or more than one request (R5.1)."""
    seen: list[httpx.Request] = []
    land(zone, seen)
    assert [r.url.path for r in seen] == ["/api/v1/sports/1/players"]
    assert dict(seen[0].url.params) == {"season": "2026"}


def test_the_capture_is_where_the_staging_model_will_look(zone):
    """Catches a different folder layout or a capture missing its payload or sidecar."""
    path = land(zone)
    assert path == zone.root / f"mlb/players/season=2026/fetched_at={STAMP}"
    assert sorted(p.name for p in path.iterdir()) == ["meta.json", "payload.json"]


def test_the_landed_payload_is_the_response_as_parsed_json(zone):
    """Catches any interpretation or trimming of the response (fetch-and-save only). Bytes
    are not compared: the landing zone re-serialises."""
    path = land(zone)
    assert json.loads((path / "payload.json").read_text()) == PLAYERS


def test_the_sidecar_records_the_partition_and_the_request(zone):
    """Catches a sidecar the loader cannot key on: season partition, url, params (R5.6)."""
    path = land(zone)
    meta = json.loads((path / "meta.json").read_text())
    assert meta["partitions"] == {"season": SEASON}
    assert meta["url"].startswith("https://statsapi.mlb.com/api/v1/sports/1/players")
    assert meta["params"] == {"season": SEASON}


def test_the_public_client_needs_no_credential(zone, monkeypatch):
    """Catches the step reading ESPN credentials or environment (R5.4)."""
    for name in ("ESPN_S2", "ESPN_SWID", "ESPN_LEAGUE_ID"):
        monkeypatch.delenv(name, raising=False)
    assert land(zone).is_dir()


# -- the CLI ------------------------------------------------------------------------------------


@pytest.fixture
def fail():
    """Maps a request path to a response or exception to give instead of the default."""
    return {}


@pytest.fixture
def served(monkeypatch, fail):
    """Patch the CLI's client; the returned list records each request path."""
    seen: list[str] = []

    def handler(request):
        seen.append(request.url.path)
        outcome = fail.get(request.url.path)
        if isinstance(outcome, Exception):
            raise outcome
        if outcome is not None:
            return outcome
        if request.url.path.endswith("/players"):
            return httpx.Response(200, json=PLAYERS)
        if request.url.path.endswith("/schedule"):
            return httpx.Response(200, json=SCHEDULE)
        return httpx.Response(200, json={"teams": {}})

    monkeypatch.setattr("front_office.cli.HttpClient", lambda source: make_client(handler, source))
    monkeypatch.setattr("front_office.cli.utc_stamp", lambda: STAMP)
    return seen


def run(zone, *flags):
    return runner.invoke(
        app, ["backfill", "mlb", "--season", "2026", "--raw-root", str(zone.root), *flags]
    )


def endpoints_landed(zone):
    return sorted({c.meta["endpoint"] for c in zone.committed(source="mlb")})


def test_only_players_lands_that_capture_alone(zone, served):
    """Catches --only players also fetching the schedule or boxscores (R5.2)."""
    result = run(zone, "--only", "players")
    assert result.exit_code == 0, result.output
    assert served == ["/api/v1/sports/1/players"]
    assert endpoints_landed(zone) == ["players"]


def test_a_full_run_requests_the_list_between_schedule_and_boxscores(zone, served):
    """Catches the list landing in the wrong order or being skipped on a full run (R5.1)."""
    result = run(zone)
    assert result.exit_code == 0, result.output
    assert served == [
        "/api/v1/schedule",
        "/api/v1/sports/1/players",
        "/api/v1/game/11/boxscore",
    ]
    assert endpoints_landed(zone) == ["boxscore", "players", "schedule"]


def test_only_schedule_does_not_request_the_list(zone, served):
    """Catches the list leaking into the other --only modes."""
    assert run(zone, "--only", "schedule").exit_code == 0
    assert served == ["/api/v1/schedule"]


@pytest.mark.parametrize(
    "failure",
    [
        httpx.Response(500),
        httpx.Response(404),
        httpx.ConnectError("refused"),
        httpx.Response(403),
    ],
    ids=["http-500", "http-404", "transport-error", "http-403"],
)
def test_a_failing_list_request_does_not_stop_the_boxscores_but_exits_1(
    zone, served, fail, failure
):
    """Catches a players failure aborting the run before the boxscores, escaping as a
    traceback, or exiting 0 (R5.3)."""
    fail["/api/v1/sports/1/players"] = failure
    result = run(zone)
    assert result.exit_code == 1
    assert "Traceback" not in result.output
    assert "player list" in result.output
    assert served[-1] == "/api/v1/game/11/boxscore"
    assert "players" not in endpoints_landed(zone)
    assert "boxscore" in endpoints_landed(zone)


def test_both_failures_are_reported(zone, served, fail):
    """Catches the boxscore failure message being lost when the list also failed."""
    fail["/api/v1/sports/1/players"] = httpx.Response(500)
    fail["/api/v1/game/11/boxscore"] = httpx.Response(500)
    result = run(zone)
    assert result.exit_code == 1
    assert "player list" in result.output
    assert "failed game_pks" in result.output
