"""Tests for boxscore ingestion: which games to fetch, and when to fetch them again.

The interesting logic is not the HTTP call but the decision to skip: a season backfill
re-run must not re-download 2,400 games, while a game whose stats may still be corrected
must not be frozen too early.
"""

import datetime as dt
import json
import types

import httpx
import pytest

from front_office.http_client import AuthExpired, HttpClient, SourceLimits
from front_office.landing import LandingCollision, LandingZone
from front_office.mlb.boxscore import (
    ScheduledGame,
    backfill_boxscores,
    capture_stamps,
    first_final,
    games_from_landed_schedule,
    is_settled,
    needs_fetch,
    parse_stamp,
)

TODAY = dt.date(2026, 9, 26)


def land_schedule(zone, games, stamp="20260926T000000Z"):
    """Land a schedule response shaped like the MLB API's, containing `games`."""
    return zone.write(
        source="mlb",
        endpoint="schedule",
        partitions={"season": 2026, "game_type": "R"},
        name=f"fetched_at={stamp}",
        payload={"dates": [{"date": g["officialDate"], "games": [g]} for g in games]},
        request={"url": "https://statsapi.mlb.com/api/v1/schedule", "params": {"season": 2026}},
        fetched_at=stamp,
    )


_UNSET = object()


def game(pk, *, date="2026-04-14", state="Final", detailed="Final", start=_UNSET):
    """A schedule entry. `start` is its gameDate; omit it for 18:00Z on the official date,
    pass None to leave the field out."""
    entry = {
        "gamePk": pk,
        "season": "2026",
        "officialDate": date,
        "gameType": "R",
        "status": {"abstractGameState": state, "detailedState": detailed},
    }
    if start is _UNSET:
        start = f"{date}T18:00:00Z"
    if start is not None:
        entry["gameDate"] = start
    return entry


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


def utc(*args):
    return dt.datetime(*args, tzinfo=dt.UTC)


def last_start_of(zone, pk):
    return {g.game_pk: g.last_start for g in games_from_landed_schedule(zone, season=2026)}[pk]


def test_last_start_is_the_game_date_of_a_single_entry(zone):
    """Catches last_start left unset or parsed without its UTC offset."""
    land_schedule(zone, [game(1, start="2026-04-14T23:05:00Z")])
    assert last_start_of(zone, 1) == utc(2026, 4, 14, 23, 5)
    assert last_start_of(zone, 1).utcoffset() == dt.timedelta(0)


def test_last_start_of_a_postponed_then_played_game_is_the_makeup(zone):
    """Catches the first (postponed) entry's start being used instead of the makeup's."""
    land_schedule(
        zone,
        [
            game(7, date="2026-04-30", detailed="Postponed", start="2026-04-30T23:05:00Z"),
            game(7, date="2026-05-20", start="2026-05-20T17:10:00Z"),
        ],
    )
    assert last_start_of(zone, 7) == utc(2026, 5, 20, 17, 10)


def test_last_start_of_a_resumed_game_is_its_later_session(zone):
    """Catches a resumed game (two played entries) keeping its first session's start."""
    land_schedule(
        zone,
        [
            game(9, date="2026-06-16", start="2026-06-16T23:15:00Z"),
            game(9, date="2026-06-16", start="2026-06-17T18:00:00Z"),
        ],
    )
    assert last_start_of(zone, 9) == utc(2026, 6, 17, 18, 0)


def test_last_start_counts_a_later_session_that_is_still_scheduled(zone):
    """Catches only played entries being considered: a pending session must hold the game open."""
    land_schedule(
        zone,
        [
            game(9, date="2026-06-16", start="2026-06-16T23:15:00Z"),
            game(
                9,
                date="2026-06-16",
                state="Preview",
                detailed="Scheduled",
                start="2026-06-20T18:00:00Z",
            ),
        ],
    )
    assert last_start_of(zone, 9) == utc(2026, 6, 20, 18, 0)


def test_a_missing_game_date_gives_no_last_start_and_a_warning(zone, caplog):
    """Catches a crash, or a start guessed for a game with no gameDate; the game is kept."""
    land_schedule(zone, [game(3, start=None)])
    assert last_start_of(zone, 3) is None
    assert caplog.text.count("3") >= 1
    assert [r.levelname for r in caplog.records].count("WARNING") == 1


def test_an_unparseable_game_date_gives_no_last_start_and_a_warning(zone, caplog):
    """Catches a crash on junk, and a start taken from a gameDate with no offset."""
    land_schedule(zone, [game(3, start="not a date"), game(4, start="2026-04-14T18:00:00")])
    starts = {g.game_pk: g.last_start for g in games_from_landed_schedule(zone, season=2026)}
    assert starts == {3: None, 4: None}
    assert [r.levelname for r in caplog.records].count("WARNING") == 2


def test_an_unreadable_later_entry_leaves_a_resumed_game_with_no_last_start(zone, caplog):
    """Catches the readable first session being trusted when the later one cannot be read."""
    land_schedule(
        zone,
        [
            game(9, date="2026-06-16", start="2026-06-16T23:15:00Z"),
            game(9, date="2026-06-16", start="garbage"),
        ],
    )
    assert last_start_of(zone, 9) is None
    assert "9" in caplog.text


def test_fetches_a_game_that_has_never_been_landed():
    """Catches a game with no captures being treated as settled."""
    g = ScheduledGame(
        game_pk=1,
        season=2026,
        official_date=dt.date(2026, 4, 14),
        state="Final",
        detailed_state="Final",
        last_start=utc(2026, 4, 14, 18, 0),
    )
    assert needs_fetch(g, []) is True


def test_refresh_overrides_the_skip():
    """Catches --refresh being ignored for a settled game."""
    old = ScheduledGame(
        game_pk=1,
        season=2026,
        official_date=dt.date(2026, 4, 14),
        state="Final",
        detailed_state="Final",
        last_start=utc(2026, 4, 14, 18, 0),
    )
    stamps = [utc(2026, 4, 15), utc(2026, 4, 23)]
    assert needs_fetch(old, stamps) is False
    assert needs_fetch(old, stamps, refresh=True) is True


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
        zone=zone, client=client, season=2026, fetched_at="20260926T120000Z"
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
        )
    assert len(requested) == 2, "no game after the rejected one is requested"


def test_backfill_honours_a_limit(zone):
    land_schedule(zone, [game(n) for n in range(1, 11)])
    client = make_client(lambda request: httpx.Response(200, json={"teams": {}}))
    summary = backfill_boxscores(
        zone=zone, client=client, season=2026, fetched_at="20260926T120000Z", limit=3
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


START = utc(2026, 6, 17, 18, 0)
WEEK = dt.timedelta(days=7)


def test_parse_stamp_reads_the_compact_utc_stamp():
    """Catches a stamp parsed as naive or in local time."""
    assert parse_stamp("20260926T162307Z") == utc(2026, 9, 26, 16, 23, 7)
    assert parse_stamp("20260926T162307Z").utcoffset() == dt.timedelta(0)


def test_parse_stamp_rejects_a_malformed_stamp():
    """Catches junk stamps being accepted silently."""
    with pytest.raises(ValueError):
        parse_stamp("2026-09-26")


def test_no_captures_is_neither_final_nor_settled():
    """Catches an empty capture list crashing or counting as settled."""
    assert first_final([], START) is None
    assert is_settled([], START) is False


def test_first_final_is_the_earliest_capture_strictly_after_the_last_start():
    """Catches the guard using >= (a capture at the start instant has not seen the end)."""
    stamps = [START - WEEK, START, START + dt.timedelta(hours=5), START + dt.timedelta(hours=2)]
    assert first_final(stamps, START) == START + dt.timedelta(hours=2)


def test_captures_before_the_last_start_are_ignored():
    """Catches a pre-start capture starting the clock for a resumed game."""
    stamps = [START - dt.timedelta(days=9), START - dt.timedelta(days=1)]
    assert first_final(stamps, START) is None
    assert is_settled(stamps, START) is False


def test_without_a_last_start_nothing_is_final_or_settled():
    """Catches a game with no boundary settling anyway (R1.3)."""
    stamps = [START, START + WEEK, START + 2 * WEEK]
    assert first_final(stamps, None) is None
    assert is_settled(stamps, None) is False


def test_one_capture_does_not_settle_a_game():
    """Catches a single capture counting as its own evidence."""
    assert is_settled([START + dt.timedelta(hours=1)], START) is False


def test_seven_days_less_a_second_does_not_settle():
    """Catches an off-by-one that settles a game a second early."""
    first = START + dt.timedelta(hours=1)
    assert is_settled([first, first + WEEK - dt.timedelta(seconds=1)], START) is False


def test_exactly_seven_days_settles():
    """Catches > in place of >= at the boundary."""
    first = START + dt.timedelta(hours=1)
    assert is_settled([first, first + WEEK], START) is True


def test_the_window_runs_from_the_first_final_capture_not_a_later_one():
    """Catches the window measured from the latest capture, which would never settle."""
    first = START + dt.timedelta(hours=1)
    stamps = [first, first + dt.timedelta(days=3), first + WEEK + dt.timedelta(days=1)]
    assert is_settled(stamps, START) is True


def test_a_custom_settle_window_is_honoured():
    """Catches the settle_window argument being ignored."""
    first = START + dt.timedelta(hours=1)
    assert is_settled([first, first + dt.timedelta(days=1)], START, dt.timedelta(days=1)) is True


def test_the_functions_accept_a_generator_and_read_it_once():
    """Catches a first pass consuming the stamps so the second pass sees none."""
    first = START + dt.timedelta(hours=1)

    def stamps():
        yield first
        yield first + WEEK

    assert first_final(stamps(), START) == first
    assert is_settled(stamps(), START) is True


# -- the fetch path: scenarios driven through backfill_boxscores -------------------------

GAME_START = utc(2026, 6, 1, 18, 0)
DAY0 = utc(2026, 6, 1, 20, 0)  # two hours after the start: the game is over


def stamp_at(day, *, hours=0, base=DAY0):
    """The compact stamp `day` days (and `hours`) after the end of the game."""
    return (base + dt.timedelta(days=day, hours=hours)).strftime("%Y%m%dT%H%M%SZ")


def run(zone, stamp, **kwargs):
    """One backfill run at `stamp` against a transport that always answers."""
    client = make_client(lambda request: httpx.Response(200, json={"teams": {}}))
    return backfill_boxscores(zone=zone, client=client, season=2026, fetched_at=stamp, **kwargs)


def one_game(zone, **kwargs):
    land_schedule(zone, [game(1, date="2026-06-01", start="2026-06-01T18:00:00Z", **kwargs)])


def test_a_game_captured_only_on_day_zero_is_fetched_on_day_eight_then_skipped(zone):
    """Catches the R4 defect: a game last seen on day 0 skipped on day 8 with no later capture."""
    one_game(zone)
    assert run(zone, stamp_at(0)).fetched == 1
    assert run(zone, stamp_at(8)).fetched == 1
    assert (run(zone, stamp_at(9)).fetched, run(zone, stamp_at(9, hours=1)).skipped) == (0, 1)


def test_a_missed_week_repairs_itself_on_the_next_run(zone):
    """Catches a week without runs freezing every game played before it."""
    one_game(zone)
    for day in (1, 2, 3):
        assert run(zone, stamp_at(day)).fetched == 1
    assert run(zone, stamp_at(12)).fetched == 1
    assert run(zone, stamp_at(13)).skipped == 1


def test_a_game_with_an_old_official_date_first_captured_now_is_not_settled(zone):
    """Catches the official date surviving in the rule: a month-old date is not evidence."""
    land_schedule(zone, [game(1, date="2026-05-01", start="2026-05-01T18:00:00Z")])
    assert run(zone, stamp_at(0)).fetched == 1
    assert run(zone, stamp_at(1)).fetched == 1


def test_a_resumed_game_starts_its_clock_at_the_first_capture_after_the_later_session(zone):
    """Catches a capture from before the resumed session counting toward the settle window."""
    land_schedule(
        zone,
        [
            game(1, date="2026-06-01", start="2026-06-01T18:00:00Z"),
            game(1, date="2026-06-01", start="2026-06-20T18:00:00Z"),
        ],
    )
    land_boxscore_at(zone, 1, "20260602T100000Z")  # during the suspension
    land_boxscore_at(zone, 1, "20260621T100000Z")  # after the resumed session
    # Seven days after the early capture is long gone; seven after the later one is not.
    assert run(zone, "20260627T100000Z").fetched == 1
    assert run(zone, "20260628T100000Z").fetched == 1  # exactly 7 days after 06-21: not yet seen
    assert run(zone, "20260629T100000Z").skipped == 1


def test_refresh_fetches_a_settled_game(zone):
    """Catches --refresh not reaching the loop for a settled game."""
    one_game(zone)
    land_boxscore_at(zone, 1, stamp_at(1))
    land_boxscore_at(zone, 1, stamp_at(8))
    assert run(zone, stamp_at(9)).skipped == 1
    assert run(zone, stamp_at(10), refresh=True).fetched == 1


def test_another_seasons_capture_and_debris_settle_nothing(zone):
    """Catches cross-season leakage and temp or loose files being counted as captures."""
    one_game(zone)
    for stamp in (stamp_at(1), stamp_at(9)):
        zone.write(
            source="mlb",
            endpoint="boxscore",
            partitions={"season": 2025, "game_pk": 1},
            name=f"fetched_at={stamp}",
            payload={"teams": {}},
            request={"url": "https://example.test", "params": {"gamePk": 1}},
            fetched_at=stamp,
        )
    land_boxscore_at(zone, 1, stamp_at(1))
    folder = zone.root / "mlb/boxscore/season=2026/game_pk=1"
    (folder / f"fetched_at={stamp_at(9)}.tmp-99").mkdir()
    (folder / f"fetched_at={stamp_at(10)}.json").write_text("{}")
    assert capture_stamps(zone, season=2026) == {1: [parse_stamp(stamp_at(1))]}
    assert run(zone, stamp_at(11)).fetched == 1


@pytest.mark.parametrize("later", ["Final", "Preview"])
def test_a_newer_schedule_with_a_later_session_reopens_a_settled_game(zone, later):
    """Catches a partial boxscore staying settled, or settlement being stored somewhere."""
    one_game(zone)
    assert run(zone, stamp_at(1)).fetched == 1
    assert run(zone, stamp_at(8)).fetched == 1
    assert run(zone, stamp_at(9)).skipped == 1
    state = {"Final": ("Final", "Final"), "Preview": ("Preview", "Scheduled")}[later]
    land_schedule(
        zone,
        [
            game(1, date="2026-06-01", start="2026-06-01T18:00:00Z"),
            game(
                1,
                date="2026-06-01",
                start="2026-06-12T12:00:00Z",
                state=state[0],
                detailed=state[1],
            ),
        ],
        stamp="20261001T000000Z",
    )
    assert run(zone, "20260613T120000Z").fetched == 1  # first capture after the new start
    assert run(zone, "20260619T120000Z").fetched == 1  # 6 days later: not settled
    assert run(zone, "20260620T120000Z").fetched == 1  # exactly 7 days: only now evidence
    assert run(zone, "20260621T120000Z").skipped == 1


@pytest.mark.parametrize(
    "entries",
    [
        [game(1, start=None)],
        [game(1, start="not a date")],
        [game(1, start="2026-06-01T18:00:00Z"), game(1, start="garbage")],
    ],
    ids=["missing", "unparseable", "resumed-with-unreadable-later-entry"],
)
def test_a_game_with_an_unreadable_game_date_is_fetched_on_every_run(zone, entries):
    """Catches a game with no boundary settling, or an unreadable later session being skipped."""
    land_schedule(zone, entries)
    for day in (1, 9, 17, 18, 40):
        assert run(zone, stamp_at(day)).fetched == 1


def test_the_decision_does_not_read_the_clock(zone, monkeypatch):
    """Catches today's date or the current time surviving in the rule (R1.4)."""

    class NoClock(dt.datetime):
        @classmethod
        def now(cls, tz=None):
            raise AssertionError("the clock was read")

        @classmethod
        def utcnow(cls):
            raise AssertionError("the clock was read")

        @classmethod
        def today(cls):
            raise AssertionError("the clock was read")

    class NoToday(dt.date):
        @classmethod
        def today(cls):
            raise AssertionError("the clock was read")

    frozen = types.SimpleNamespace(**vars(dt))
    frozen.datetime = NoClock
    frozen.date = NoToday
    monkeypatch.setattr("front_office.mlb.boxscore.dt", frozen)
    one_game(zone)
    assert run(zone, stamp_at(0)).fetched == 1
    assert run(zone, stamp_at(8)).fetched == 1
    assert run(zone, stamp_at(9)).skipped == 1
