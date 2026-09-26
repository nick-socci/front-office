"""Tests for ESPN ingestion: credentials, period completion, and re-fetch rules.

No test here touches the network or reads a real .env. The credential tests assert the
failure message, because an expired-cookie failure is the one a human has to act on.
"""

import json

import httpx
import pytest

from front_office.espn import rosters as espn_rosters
from front_office.espn import settings as espn_settings
from front_office.espn.client import EspnCredentials, MissingCredentials
from front_office.http_client import HttpClient, SourceLimits
from front_office.landing import LandingZone

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


def land_roster(zone, *, period):
    return zone.write(
        source="espn",
        endpoint="roster",
        partitions={"season": SEASON, "league_id": LEAGUE_ID, "scoring_period": period},
        name="fetched_at=20260901T000000Z",
        payload={"teams": []},
        request={"url": "https://example.test", "params": {"scoringPeriodId": period}},
        fetched_at="20260901T000000Z",
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
    keys = [json.loads(r.path.with_suffix(".meta.json").read_text())["request_key"] for r in landed]
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
