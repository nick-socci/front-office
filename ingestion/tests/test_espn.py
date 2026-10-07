"""Tests for ESPN ingestion: credentials, period completion, and re-fetch rules.

No test here touches the network or reads a real .env. The credential tests assert the
failure message, because an expired-cookie failure is the one a human has to act on.
"""

import json

import httpx
import pytest
from typer.testing import CliRunner

from front_office import cli
from front_office.espn import rosters as espn_rosters
from front_office.espn import settings as espn_settings
from front_office.espn.client import EspnCredentials, MissingCredentials
from front_office.http_client import AuthExpired, HttpClient, SourceLimits
from front_office.landing import LandingCollision, LandingZone

LEAGUE_ID = "73677"
SEASON = 2026

# Shape of the mStatus block: latestScoringPeriod is the period currently in progress.
MID_SEASON = {"latestScoringPeriod": 100, "finalScoringPeriod": 180}
SEASON_OVER = {"latestScoringPeriod": 186, "finalScoringPeriod": 180}


@pytest.fixture
def zone(tmp_path):
    return LandingZone(root=tmp_path)


def test_credentials_from_environment(monkeypatch):
    monkeypatch.setenv("ESPN_S2", "cookie-value")
    monkeypatch.setenv("SWID", "{GUID}")
    monkeypatch.setenv("LEAGUE_ID", LEAGUE_ID)
    creds = EspnCredentials.from_env()
    assert creds.league_id == LEAGUE_ID
    assert creds.cookies() == {"espn_s2": "cookie-value", "SWID": "{GUID}"}


def test_missing_credentials_names_what_to_do(monkeypatch):
    monkeypatch.delenv("ESPN_S2", raising=False)
    monkeypatch.setenv("SWID", "{GUID}")
    monkeypatch.setenv("LEAGUE_ID", LEAGUE_ID)
    with pytest.raises(MissingCredentials) as exc:
        EspnCredentials.from_env()
    message = str(exc.value)
    assert "ESPN_S2" in message
    assert ".env" in message


def test_credentials_are_never_included_in_their_repr(monkeypatch):
    """A traceback or log line must not leak a session cookie."""
    creds = EspnCredentials(espn_s2="super-secret", swid="{GUID}", league_id=LEAGUE_ID)
    assert "super-secret" not in repr(creds)
    assert "GUID" not in repr(creds)


@pytest.mark.parametrize(
    ("period", "status", "expected"),
    [
        (99, MID_SEASON, True),
        (100, MID_SEASON, False),  # in progress: rosters can still change
        (101, MID_SEASON, False),
        (180, SEASON_OVER, True),  # season finished: every period is settled
        (1, SEASON_OVER, True),
    ],
)
def test_period_is_over(period, status, expected):
    assert espn_rosters.period_is_over(period, status) is expected


def test_roster_needs_fetch_when_never_landed(zone):
    assert (
        espn_rosters.needs_fetch(
            zone, season=SEASON, league_id=LEAGUE_ID, period=5, status=MID_SEASON
        )
        is True
    )


def test_roster_is_skipped_once_its_period_is_over(zone):
    land_roster(zone, period=5)
    assert (
        espn_rosters.needs_fetch(
            zone, season=SEASON, league_id=LEAGUE_ID, period=5, status=MID_SEASON
        )
        is False
    )


def test_in_progress_period_is_refetched_even_when_landed(zone):
    land_roster(zone, period=100)
    assert (
        espn_rosters.needs_fetch(
            zone, season=SEASON, league_id=LEAGUE_ID, period=100, status=MID_SEASON
        )
        is True
    )


def test_refresh_forces_a_refetch(zone):
    land_roster(zone, period=5)
    assert (
        espn_rosters.needs_fetch(
            zone, season=SEASON, league_id=LEAGUE_ID, period=5, status=MID_SEASON, refresh=True
        )
        is True
    )


def land_roster(zone, *, period, stamp="20260901T000000Z"):
    return zone.write(
        source="espn",
        endpoint="roster",
        partitions={"season": SEASON, "league_id": LEAGUE_ID, "scoring_period": period},
        name=f"fetched_at={stamp}",
        payload={"teams": []},
        request={"url": "https://example.test", "params": {"scoringPeriodId": period}},
        fetched_at=stamp,
    )


def make_client(handler):
    return HttpClient(
        source="espn",
        limits=SourceLimits(min_interval_s=0.0, max_attempts=2, backoff_base_s=0.0),
        transport=httpx.MockTransport(handler),
        sleep=lambda _seconds: None,
    )


def test_settings_lands_a_new_snapshot_on_every_run(zone):
    client = make_client(
        lambda request: httpx.Response(200, json={"settings": {}, "status": MID_SEASON})
    )
    first, _ = espn_settings.backfill_settings(
        zone=zone, client=client, season=SEASON, league_id=LEAGUE_ID, fetched_at="20260101T000000Z"
    )
    second, payload = espn_settings.backfill_settings(
        zone=zone, client=client, season=SEASON, league_id=LEAGUE_ID, fetched_at="20260102T000000Z"
    )
    assert first != second, "settings are a snapshot: history accumulates"
    assert payload["status"] == MID_SEASON
    assert len(list(zone.iter_landed(source="espn", endpoint="settings"))) == 2


def test_roster_backfill_covers_periods_up_to_the_latest(zone):
    requested = []

    def handler(request):
        requested.append(request.url.params.get("scoringPeriodId"))
        return httpx.Response(200, json={"teams": []})

    summary = espn_rosters.backfill_rosters(
        zone=zone,
        client=make_client(handler),
        season=SEASON,
        league_id=LEAGUE_ID,
        status={"latestScoringPeriod": 4, "finalScoringPeriod": 180},
        fetched_at="20260101T000000Z",
    )
    assert requested == ["1", "2", "3", "4"]
    assert (summary.fetched, summary.skipped, summary.failed) == (4, 0, 0)


def test_roster_backfill_stops_at_the_final_period_when_the_season_is_over(zone):
    requested = []

    def handler(request):
        requested.append(request.url.params.get("scoringPeriodId"))
        return httpx.Response(200, json={"teams": []})

    espn_rosters.backfill_rosters(
        zone=zone,
        client=make_client(handler),
        season=SEASON,
        league_id=LEAGUE_ID,
        status={"latestScoringPeriod": 186, "finalScoringPeriod": 5},
        fetched_at="20260101T000000Z",
    )
    assert requested == ["1", "2", "3", "4", "5"], "periods past the final one do not exist"


def test_roster_backfill_records_the_scoring_period_in_metadata(zone):
    espn_rosters.backfill_rosters(
        zone=zone,
        client=make_client(lambda request: httpx.Response(200, json={"teams": []})),
        season=SEASON,
        league_id=LEAGUE_ID,
        status={"latestScoringPeriod": 2, "finalScoringPeriod": 180},
        fetched_at="20260101T000000Z",
    )
    landed = sorted(zone.iter_landed(source="espn", endpoint="roster"), key=lambda r: str(r.path))
    keys = [json.loads((r.path.parent / "meta.json").read_text())["request_key"] for r in landed]
    assert all("scoringPeriodId=" in key for key in keys)


def test_roster_backfill_continues_after_one_period_fails(zone):
    def handler(request):
        if request.url.params.get("scoringPeriodId") == "2":
            return httpx.Response(500)
        return httpx.Response(200, json={"teams": []})

    summary = espn_rosters.backfill_rosters(
        zone=zone,
        client=make_client(handler),
        season=SEASON,
        league_id=LEAGUE_ID,
        status={"latestScoringPeriod": 3, "finalScoringPeriod": 180},
        fetched_at="20260101T000000Z",
    )
    assert (summary.fetched, summary.failed) == (2, 1)
    assert summary.failed_periods == [2]


def expires_after_period_one(requested):
    """A handler whose cookies stop working after the first roster request."""

    def handler(request):
        period = request.url.params.get("scoringPeriodId")
        if period is None:  # settings, teams, matchups, transactions
            return httpx.Response(200, json={"status": {"latestScoringPeriod": 5}})
        requested.append(period)
        return httpx.Response(200 if period == "1" else 401, json={"teams": []})

    return handler


def test_roster_backfill_stops_when_authentication_expires(zone):
    requested = []
    with pytest.raises(AuthExpired):
        espn_rosters.backfill_rosters(
            zone=zone,
            client=make_client(expires_after_period_one(requested)),
            season=SEASON,
            league_id=LEAGUE_ID,
            status={"latestScoringPeriod": 5, "finalScoringPeriod": 180},
            fetched_at="20260101T000000Z",
        )
    assert requested == ["1", "2"], "no period after the rejected one is requested"
    assert len(list(zone.iter_landed(source="espn", endpoint="roster"))) == 1


def test_roster_backfill_stops_on_a_collision(zone):
    """Catches a collision counted as one failed period while later periods are fetched."""
    land_roster(zone, period=2, stamp="20260101T000000Z")
    requested = []

    def handler(request):
        requested.append(request.url.params.get("scoringPeriodId"))
        return httpx.Response(200, json={"teams": []})

    with pytest.raises(LandingCollision):
        espn_rosters.backfill_rosters(
            zone=zone,
            client=make_client(handler),
            season=SEASON,
            league_id=LEAGUE_ID,
            status={"latestScoringPeriod": 3, "finalScoringPeriod": 180},
            fetched_at="20260101T000000Z",
            refresh=True,
        )
    assert requested == ["1", "2"], "no period after the collision is requested"


def test_backfill_espn_exits_non_zero_when_authentication_expires(tmp_path, monkeypatch):
    monkeypatch.setenv("ESPN_S2", "s2-cookie-value")
    monkeypatch.setenv("SWID", "{swid-cookie-value}")
    monkeypatch.setenv("LEAGUE_ID", LEAGUE_ID)
    monkeypatch.setattr(cli, "load_env_file", lambda: None)
    requested = []
    monkeypatch.setattr(
        cli, "espn_client", lambda _credentials: make_client(expires_after_period_one(requested))
    )

    result = CliRunner().invoke(
        cli.app, ["backfill", "espn", "--season", str(SEASON), "--raw-root", str(tmp_path)]
    )

    assert result.exit_code == 1
    assert "cookies expired" in result.output
    assert "Traceback" not in result.output
    assert "cookie-value" not in result.output
    assert requested == ["1", "2"]


def _land_one_roster(zone, response_json, *, run_status=None):
    """Backfill period 1 against a fake roster response; return the landed sidecar."""
    espn_rosters.backfill_rosters(
        zone=zone,
        client=make_client(lambda request: httpx.Response(200, json=response_json)),
        season=SEASON,
        league_id=LEAGUE_ID,
        status=run_status or {"latestScoringPeriod": 1, "finalScoringPeriod": 180},
        fetched_at="20260101T000000Z",
    )
    (capture,) = zone.committed(source="espn", endpoint="roster")
    return capture.meta


def test_roster_sidecar_records_the_status_of_the_response_not_of_the_run(zone):
    """Catches the status taken from the run's settings instead of the response it landed (R1.1)."""
    meta = _land_one_roster(
        zone,
        {"teams": [], "status": {"latestScoringPeriod": 101, "finalScoringPeriod": 177}},
        run_status={"latestScoringPeriod": 1, "finalScoringPeriod": 180},
    )
    assert meta["source_status"] == {"latest_scoring_period": 101, "final_scoring_period": 177}


@pytest.mark.parametrize(
    "response",
    [
        {"teams": []},
        {"teams": [], "status": {"latestScoringPeriod": "101", "finalScoringPeriod": 180}},
        {"teams": [], "status": {"latestScoringPeriod": True, "finalScoringPeriod": 180}},
        {"teams": [], "status": [101]},
    ],
    ids=["no status", "string counter", "boolean counter", "status not a mapping"],
)
def test_a_roster_response_without_a_usable_status_still_lands_and_warns(zone, caplog, response):
    """Catches a crash losing the capture, or a non-integer counter recorded as a number (R1.2)."""
    with caplog.at_level("WARNING"):
        meta = _land_one_roster(zone, response)
    assert meta["source_status"]["latest_scoring_period"] is None
    assert any("scoring period 1" in record.getMessage() for record in caplog.records)
