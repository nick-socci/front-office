"""Tests for the remaining ESPN extractors and the player id crosswalk."""

import json

import httpx
import pytest

from front_office.espn import matchups as espn_matchups
from front_office.espn import transactions as espn_transactions
from front_office.http_client import HttpClient, SourceLimits
from front_office.idmap import sfbb
from front_office.landing import LandingZone

LEAGUE_ID = "73677"
SEASON = 2026


@pytest.fixture
def zone(tmp_path):
    return LandingZone(root=tmp_path)


def make_client(handler, source="espn"):
    return HttpClient(
        source=source,
        limits=SourceLimits(min_interval_s=0.0, max_attempts=2, backoff_base_s=0.0),
        transport=httpx.MockTransport(handler),
        sleep=lambda _seconds: None,
    )


def test_matchups_are_fetched_once_not_per_period(zone):
    """These views return the whole season, so one call is the whole point."""
    requests = []

    def handler(request):
        requests.append(request.url)
        return httpx.Response(200, json={"schedule": []})

    espn_matchups.backfill_matchups(
        zone=zone,
        client=make_client(handler),
        season=SEASON,
        league_id=LEAGUE_ID,
        fetched_at="20260101T000000Z",
    )
    assert len(requests) == 1
    assert "scoringPeriodId" not in str(requests[0])


def test_transactions_send_the_activity_filter_header(zone):
    """ESPN filters this endpoint through a header, not query parameters."""
    seen = {}

    def handler(request):
        seen["filter"] = request.headers.get("x-fantasy-filter")
        seen["url"] = str(request.url)
        return httpx.Response(200, json={"topics": []})

    espn_transactions.backfill_transactions(
        zone=zone,
        client=make_client(handler),
        season=SEASON,
        league_id=LEAGUE_ID,
        fetched_at="20260101T000000Z",
        limit=50,
    )
    sent = json.loads(seen["filter"])
    assert sent["topics"]["filterType"]["value"] == ["ACTIVITY_TRANSACTIONS"]
    assert sent["topics"]["limit"] == 50
    assert sent["topics"]["filterIncludeMessageTypeIds"]["value"] == list(
        espn_transactions.MESSAGE_TYPE_IDS
    )
    assert seen["url"].endswith("communication/?view=kona_league_communication")


def test_transactions_land_the_payload(zone):
    payload = {"topics": [{"id": "abc", "date": 1789921020086, "messages": []}]}
    espn_transactions.backfill_transactions(
        zone=zone,
        client=make_client(lambda r: httpx.Response(200, json=payload)),
        season=SEASON,
        league_id=LEAGUE_ID,
        fetched_at="20260101T000000Z",
    )
    landed = list(zone.iter_landed(source="espn", endpoint="transactions"))
    assert len(landed) == 1
    assert landed[0].payload == payload


def test_id_map_csv_becomes_json_rows(zone):
    csv_text = "IDPLAYER,PLAYERNAME,MLBID,ESPNID\nabc01,Some Player,430911,5933\n"
    path, count = sfbb.backfill_player_id_map(
        zone=zone,
        client=make_client(lambda r: httpx.Response(200, text=csv_text), source="idmap"),
        fetched_at="20260101T000000Z",
    )
    assert count == 1
    rows = json.loads(path.read_text())
    assert rows == [
        {"IDPLAYER": "abc01", "PLAYERNAME": "Some Player", "MLBID": "430911", "ESPNID": "5933"}
    ]


def test_id_map_parsing_keeps_blank_ids_as_empty_strings():
    """Players missing an ESPN id must survive parsing; staging filters them out."""
    rows = sfbb.parse_csv("MLBID,ESPNID\n430911,\n,5933\n")
    assert rows == [{"MLBID": "430911", "ESPNID": ""}, {"MLBID": "", "ESPNID": "5933"}]
