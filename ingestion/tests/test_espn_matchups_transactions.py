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


def topics(count, *, start=0, short=False):
    return [
        {
            "id": f"t{n}",
            "messages": [{"id": f"m{n}"}],
            "totalMessageCount": 2 if short and n == start else 1,
        }
        for n in range(start, start + count)
    ]


def paged_log(pages, seen):
    """A handler serving `pages` by the offset in the filter header."""

    def handler(request):
        sent = json.loads(request.headers["x-fantasy-filter"])["topics"]
        seen.append(sent)
        return httpx.Response(200, json={"topics": pages.get(sent["offset"], [])})

    return handler


def backfill(zone, handler, limit=3):
    return espn_transactions.backfill_transactions(
        zone=zone,
        client=make_client(handler),
        season=SEASON,
        league_id=LEAGUE_ID,
        fetched_at="20260101T000000Z",
        limit=limit,
    )


def test_transactions_send_an_unfiltered_activity_header(zone):
    """ESPN filters this endpoint through a header; no message-type filter (#26)."""
    seen = []
    backfill(zone, paged_log({0: topics(1)}, seen), limit=50)
    assert seen[0]["filterType"]["value"] == ["ACTIVITY_TRANSACTIONS"]
    assert (seen[0]["limit"], seen[0]["offset"]) == (50, 0)
    assert "filterIncludeMessageTypeIds" not in seen[0]


def test_transactions_page_until_a_short_page_and_land_each(zone):
    seen = []
    pages = {0: topics(3), 3: topics(3, start=3), 6: topics(1, start=6)}
    paths = backfill(zone, paged_log(pages, seen))
    assert [sent["offset"] for sent in seen] == [0, 3, 6]
    assert len(paths) == 3
    landed = sorted(
        zone.iter_landed(source="espn", endpoint="transactions"),
        key=lambda r: r.meta["partitions"]["offset"],
    )
    assert [r.meta["partitions"]["offset"] for r in landed] == [0, 3, 6]
    assert {r.meta["fetched_at"] for r in landed} == {"20260101T000000Z"}
    assert [len(r.payload["topics"]) for r in landed] == [3, 3, 1]


def test_a_full_last_page_is_followed_by_an_empty_one(zone):
    seen = []
    backfill(zone, paged_log({0: topics(3)}, seen))
    assert [sent["offset"] for sent in seen] == [0, 3]


def test_an_incomplete_topic_fails_after_landing_every_page(zone):
    pages = {0: topics(3), 3: topics(1, start=3, short=True)}
    with pytest.raises(espn_transactions.TransactionLogIncomplete, match="1 transaction topic"):
        backfill(zone, paged_log(pages, []))
    assert len(list(zone.iter_landed(source="espn", endpoint="transactions"))) == 2


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
