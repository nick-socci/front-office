"""Tests for boxscore ingestion: which games to fetch, and when to fetch them again.

The interesting logic is not the HTTP call but the decision to skip: a season backfill
re-run must not re-download 2,400 games, while a game whose stats may still be corrected
must not be frozen too early.
"""

import datetime as dt
import json

import httpx
import pytest

from front_office.http_client import AuthExpired, HttpClient, SourceLimits
from front_office.landing import LandingCollision, LandingZone
from front_office.mlb.boxscore import (
    ScheduledGame,
    backfill_boxscores,
    games_from_landed_schedule,
    needs_fetch,
)

TODAY = dt.date(2026, 9, 26)


def land_schedule(zone, games):
    """Land a schedule response shaped like the MLB API's, containing `games`."""
    return zone.write(
        source="mlb",
        endpoint="schedule",
        partitions={"season": 2026, "game_type": "R"},
        name="fetched_at=20260926T000000Z",
        payload={"dates": [{"date": g["officialDate"], "games": [g]} for g in games]},
        request={"url": "https://statsapi.mlb.com/api/v1/schedule", "params": {"season": 2026}},
        fetched_at="20260926T000000Z",
    )


def game(pk, *, date="2026-04-14", state="Final", detailed="Final"):
    return {
        "gamePk": pk,
        "season": "2026",
        "officialDate": date,
        "gameType": "R",
        "status": {"abstractGameState": state, "detailedState": detailed},
    }


@pytest.fixture
def zone(tmp_path):
    return LandingZone(root=tmp_path)


def test_reads_final_games_from_the_landed_schedule(zone):
    land_schedule(zone, [game(1), game(2)])
    games = games_from_landed_schedule(zone, season=2026)
    assert [g.game_pk for g in games] == [1, 2]
    assert games[0].official_date == dt.date(2026, 4, 14)


def test_skips_games_that_have_not_been_played(zone):
    land_schedule(zone, [game(1), game(2, state="Preview", detailed="Scheduled")])
    assert [g.game_pk for g in games_from_landed_schedule(zone, season=2026)] == [1]


def test_prefers_the_played_copy_of_a_postponed_game(zone):
    """A postponed game and its makeup share one game_pk; only the makeup has a boxscore."""
    land_schedule(
        zone,
        [
            game(7, date="2026-04-30", detailed="Postponed"),
            game(7, date="2026-04-30", detailed="Final"),
        ],
    )
    games = games_from_landed_schedule(zone, season=2026)
    assert len(games) == 1
    assert games[0].detailed_state == "Final"


def test_drops_a_postponed_game_that_was_never_made_up(zone):
    """No makeup shares its game_pk, so it was never played and has no boxscore."""
    land_schedule(zone, [game(7, detailed="Postponed"), game(8)])
    assert [g.game_pk for g in games_from_landed_schedule(zone, season=2026)] == [8]


def test_drops_a_cancelled_game(zone):
    """MLB marks a cancelled game Final; it was never played (2026: game 823490)."""
    land_schedule(zone, [game(7, detailed="Cancelled"), game(8, detailed="Completed Early")])
    assert [g.game_pk for g in games_from_landed_schedule(zone, season=2026)] == [8]


def test_fetches_a_game_that_has_never_been_landed(zone):
    g = ScheduledGame(
        game_pk=1,
        season=2026,
        official_date=dt.date(2026, 4, 14),
        state="Final",
        detailed_state="Final",
    )
    assert needs_fetch(g, zone, today=TODAY) is True


def test_refetches_inside_the_settle_window(zone):
    """Official scorers change hits and errors for days after a game ends."""
    recent = ScheduledGame(
        game_pk=1,
        season=2026,
        official_date=TODAY - dt.timedelta(days=3),
        state="Final",
        detailed_state="Final",
    )
    land_boxscore(zone, recent)
    assert needs_fetch(recent, zone, today=TODAY) is True


def test_skips_a_settled_game(zone):
    old = ScheduledGame(
        game_pk=1,
        season=2026,
        official_date=TODAY - dt.timedelta(days=8),
        state="Final",
        detailed_state="Final",
    )
    land_boxscore(zone, old)
    assert needs_fetch(old, zone, today=TODAY) is False


def test_settle_window_boundary_is_inclusive_of_the_seventh_day(zone):
    seven = ScheduledGame(
        game_pk=1,
        season=2026,
        official_date=TODAY - dt.timedelta(days=7),
        state="Final",
        detailed_state="Final",
    )
    land_boxscore(zone, seven)
    assert needs_fetch(seven, zone, today=TODAY) is True


def test_refresh_overrides_the_skip(zone):
    old = ScheduledGame(
        game_pk=1,
        season=2026,
        official_date=TODAY - dt.timedelta(days=99),
        state="Final",
        detailed_state="Final",
    )
    land_boxscore(zone, old)
    assert needs_fetch(old, zone, today=TODAY, refresh=True) is True


def land_boxscore(zone, scheduled):
    return zone.write(
        source="mlb",
        endpoint="boxscore",
        partitions={"season": scheduled.season, "game_pk": scheduled.game_pk},
        name="fetched_at=20260901T000000Z",
        payload={"teams": {}},
        request={"url": "https://example.test", "params": {"gamePk": scheduled.game_pk}},
        fetched_at="20260901T000000Z",
    )


def make_client(handler):
    return HttpClient(
        source="mlb",
        limits=SourceLimits(min_interval_s=0.0, max_attempts=2, backoff_base_s=0.0),
        transport=httpx.MockTransport(handler),
        sleep=lambda _seconds: None,
    )


def test_backfill_lands_one_file_per_game_and_records_the_game_pk(zone):
    land_schedule(zone, [game(11), game(12)])
    client = make_client(lambda request: httpx.Response(200, json={"teams": {"home": {}}}))
    summary = backfill_boxscores(
        zone=zone, client=client, season=2026, fetched_at="20260926T120000Z", today=TODAY
    )
    assert (summary.fetched, summary.skipped, summary.failed) == (2, 0, 0)
    landed = [r for r in zone.iter_landed(source="mlb", endpoint="boxscore")]
    assert len(landed) == 2
    # The payload carries no gamePk, so the request metadata must preserve it.
    assert {
        json.loads((r.path.parent / "meta.json").read_text())["request_key"] for r in landed
    } == {
        "gamePk=11",
        "gamePk=12",
    }


def test_backfill_skips_already_settled_games(zone):
    land_schedule(zone, [game(11, date="2026-04-14")])
    land_boxscore(
        zone,
        ScheduledGame(
            game_pk=11,
            season=2026,
            official_date=dt.date(2026, 4, 14),
            state="Final",
            detailed_state="Final",
        ),
    )
    client = make_client(lambda request: pytest.fail("should not have fetched"))
    summary = backfill_boxscores(
        zone=zone, client=client, season=2026, fetched_at="20260926T120000Z", today=TODAY
    )
    assert (summary.fetched, summary.skipped) == (0, 1)


def test_backfill_continues_after_one_game_fails(zone):
    land_schedule(zone, [game(11), game(12), game(13)])

    def handler(request):
        if "12" in str(request.url):
            return httpx.Response(500)
        return httpx.Response(200, json={"teams": {}})

    summary = backfill_boxscores(
        zone=zone,
        client=make_client(handler),
        season=2026,
        fetched_at="20260926T120000Z",
        today=TODAY,
    )
    assert (summary.fetched, summary.failed) == (2, 1)
    assert summary.failed_game_pks == [12]


def test_backfill_stops_when_credentials_are_rejected(zone):
    land_schedule(zone, [game(11), game(12), game(13)])
    requested = []

    def handler(request):
        requested.append(request.url.path)
        return httpx.Response(403 if "/12/" in request.url.path else 200, json={"teams": {}})

    with pytest.raises(AuthExpired):
        backfill_boxscores(
            zone=zone,
            client=make_client(handler),
            season=2026,
            fetched_at="20260926T120000Z",
            today=TODAY,
        )
    assert len(requested) == 2, "no game after the rejected one is requested"


def test_backfill_honours_a_limit(zone):
    land_schedule(zone, [game(n) for n in range(1, 11)])
    client = make_client(lambda request: httpx.Response(200, json={"teams": {}}))
    summary = backfill_boxscores(
        zone=zone, client=client, season=2026, fetched_at="20260926T120000Z", today=TODAY, limit=3
    )
    assert summary.fetched == 3


def test_a_collision_stops_the_backfill_and_no_later_game_is_fetched(zone):
    """Catches a collision counted as one failed game while the run carries on (R1.4)."""
    recent = (TODAY - dt.timedelta(days=1)).isoformat()
    land_schedule(zone, [game(n, date=recent) for n in (11, 12, 13)])
    # Game 12 already has a capture at the stamp this run will use: its write collides.
    land_boxscore_at(zone, 12, "20260926T120000Z")
    requested = []

    def handler(request):
        requested.append(request.url.path)
        return httpx.Response(200, json={"teams": {}})

    with pytest.raises(LandingCollision):
        backfill_boxscores(
            zone=zone,
            client=make_client(handler),
            season=2026,
            fetched_at="20260926T120000Z",
            today=TODAY,
        )
    assert requested == ["/api/v1/game/11/boxscore", "/api/v1/game/12/boxscore"]


def land_boxscore_at(zone, game_pk, stamp):
    return zone.write(
        source="mlb",
        endpoint="boxscore",
        partitions={"season": 2026, "game_pk": game_pk},
        name=f"fetched_at={stamp}",
        payload={"teams": {}},
        request={"url": "https://example.test", "params": {"gamePk": game_pk}},
        fetched_at=stamp,
    )
