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


def test_latest_espn_ignores_a_newer_capture_of_another_season(roots):
    """Catches a roster of the same period landed for another season (a newer capture)
    being chosen because the newest path among all seasons wins (R1.4)."""
    raw, _fixtures = roots
    base = {"league_id": "7", "scoring_period": 36}
    land(raw, "espn", "roster", {"season": 2026, **base}, "20260101T000000Z", {"s": 2026})
    land(raw, "espn", "roster", {"season": 2027, **base}, "20270101T000000Z", {"s": 2027})
    land(raw, "espn", "settings", {"season": 2026, "league_id": "7"}, "20260101T000000Z", {"s": 26})
    land(raw, "espn", "settings", {"season": 2027, "league_id": "7"}, "20270101T000000Z", {"s": 27})
    assert make_fixtures.latest_espn("roster", scoring_period=36) == {"s": 2026}
    assert make_fixtures.latest_espn("roster") == {"s": 2026}
    assert make_fixtures.latest_espn("settings") == {"s": 26}


def test_the_first_transactions_page_is_of_season_2026_only(roots):
    """Catches a newer transactions run of another season being taken as the fixture's."""
    raw, _fixtures = roots
    base = {"league_id": "7", "offset": 0}
    land(raw, "espn", "transactions", {"season": 2026, **base}, "20260101T000000Z", {"s": 2026})
    land(raw, "espn", "transactions", {"season": 2027, **base}, "20270101T000000Z", {"s": 2027})
    assert make_fixtures.newest_transactions_first_page() == {"s": 2026}


def test_two_leagues_in_the_season_stop_generation_with_their_count(roots):
    """Catches a silent choice between leagues (R1.5): the message gives how many were
    found and never which."""
    raw, _fixtures = roots
    for league in ("7", "8"):
        land(
            raw,
            "espn",
            "settings",
            {"season": 2026, "league_id": league},
            "20260101T000000Z",
            {},
        )
    land(raw, "espn", "settings", {"season": 2027, "league_id": "9"}, "20270101T000000Z", {})
    with pytest.raises(SystemExit) as stop:
        make_fixtures.check_one_league()
    message = str(stop.value)
    assert "2 leagues" in message
    assert not any(league in message for league in ("7", "8", "9"))


@pytest.mark.parametrize(
    ("endpoint", "extra"),
    [
        ("teams", {}),
        ("matchups", {}),
        ("transactions", {"offset": 0}),
        ("roster", {"scoring_period": 36}),
    ],
)
def test_a_second_league_under_any_endpoint_stops_generation(roots, endpoint, extra):
    """Catches a guard that reads settings only: a second league that has a roster, a
    transaction page or any other league capture, but no settings capture, would supply
    fixture data unnoticed (R1.5)."""
    raw, _fixtures = roots
    land(raw, "espn", "settings", {"season": 2026, "league_id": "7"}, "20260101T000000Z", {})
    land(raw, "espn", endpoint, {"season": 2026, "league_id": "8", **extra}, "20260101T000000Z", {})
    with pytest.raises(SystemExit) as stop:
        make_fixtures.check_one_league()
    assert "2 leagues" in str(stop.value)


def test_the_pro_schedule_has_no_league_and_is_not_counted_as_one(roots):
    """Catches the season-level pro schedule, which has no league_id, being counted as a
    second league and stopping every generation."""
    raw, _fixtures = roots
    land(raw, "espn", "settings", {"season": 2026, "league_id": "7"}, "20260101T000000Z", {})
    land(raw, "espn", "pro_schedule", {"season": 2026}, "20260101T000000Z", {})
    make_fixtures.check_one_league()


def test_one_league_or_none_does_not_stop_generation(roots):
    """Catches the league check refusing a single league (another season's league does not
    count) or turning an empty landing zone into a different failure."""
    raw, _fixtures = roots
    make_fixtures.check_one_league()
    land(raw, "espn", "settings", {"season": 2026, "league_id": "7"}, "20260101T000000Z", {})
    land(raw, "espn", "settings", {"season": 2026, "league_id": "7"}, "20260102T000000Z", {})
    land(raw, "espn", "settings", {"season": 2027, "league_id": "9"}, "20270101T000000Z", {})
    make_fixtures.check_one_league()


def eastern_ms(stamp: str) -> int:
    from datetime import datetime
    from zoneinfo import ZoneInfo

    local = datetime.fromisoformat(stamp).replace(tzinfo=ZoneInfo("America/New_York"))
    return int(local.timestamp() * 1000)


def land_pro_schedule(raw, games_by_period: dict[str, list[str]]):
    """Land a made-up 2026 pro schedule: period -> Eastern times of its games."""
    teams = [
        {
            "id": 1,
            "proGamesByScoringPeriod": {
                period: [{"id": i, "date": eastern_ms(when)} for i, when in enumerate(times)]
                for period, times in games_by_period.items()
            },
        }
    ]
    land(
        raw,
        "espn",
        "pro_schedule",
        {"season": 2026},
        "20260501T000000Z",
        {"settings": {"proTeams": teams}},
    )


DATES = ("2026-04-29", "2026-04-30")


def test_source_periods_on_the_fixture_dates_pass(roots):
    """Catches the date check rejecting a correct pair, including a late-evening game that
    is the next day in UTC but still the fixture date in Eastern time."""
    raw, _fixtures = roots
    land_pro_schedule(
        raw,
        {
            "36": ["2026-04-29T13:10", "2026-04-29T23:40"],
            "37": ["2026-04-30T19:05"],
            "38": ["2026-05-01T19:05"],
        },
    )
    make_fixtures.check_source_periods_are_the_fixture_dates((36, 37), DATES)


def test_a_source_period_on_another_date_stops_generation(roots):
    """Catches the constant and the dates drifting apart (R1.2): the message names the
    period, the date found and the date wanted."""
    raw, _fixtures = roots
    land_pro_schedule(raw, {"36": ["2026-04-29T19:05"], "37": ["2026-05-02T19:05"]})
    with pytest.raises(SystemExit) as stop:
        make_fixtures.check_source_periods_are_the_fixture_dates((36, 37), DATES)
    message = str(stop.value)
    assert "37" in message and "2026-05-02" in message and "2026-04-30" in message


def test_a_source_period_on_two_dates_stops_generation(roots):
    """Catches a period whose games straddle two days passing because one of them matches."""
    raw, _fixtures = roots
    land_pro_schedule(
        raw, {"36": ["2026-04-29T19:05", "2026-04-30T19:05"], "37": ["2026-04-30T19:05"]}
    )
    with pytest.raises(SystemExit) as stop:
        make_fixtures.check_source_periods_are_the_fixture_dates((36, 37), DATES)
    message = str(stop.value)
    assert "36" in message and "2026-04-29" in message and "2026-04-30" in message


def test_a_source_period_with_no_games_stops_generation(roots):
    """Catches a period missing from the schedule passing for lack of dates to disagree."""
    raw, _fixtures = roots
    land_pro_schedule(raw, {"36": ["2026-04-29T19:05"]})
    with pytest.raises(SystemExit):
        make_fixtures.check_source_periods_are_the_fixture_dates((36, 37), DATES)


def made_up_entry(lines: list[dict]) -> dict:
    return {
        "playerId": 5,
        "lineupSlotId": 3,
        "injuryStatus": "ACTIVE",
        "acquisitionType": "DRAFT",
        "userProfile": "someone",
        "playerPoolEntry": {
            "id": 5,
            "player": {
                "fullName": "A Player",
                "defaultPositionId": 1,
                "proTeamId": 4,
                "eligibleSlots": [0, 12],
                "firstName": "nope",
                "stats": lines,
            },
        },
    }


def real_line(**changes) -> dict:
    line = {
        "id": "x",
        "proTeamId": 4,
        "seasonId": 2026,
        "scoringPeriodId": 36,
        "statSourceId": 0,
        "statSplitTypeId": 5,
        "externalId": "823471",
        "appliedTotal": 1.0,
        "appliedStats": {"1": 1.0},
        "stats": {"0": 4.0, "1": 2.0},
    }
    return line | changes


def test_stat_lines_kept_are_actuals_of_one_game_of_the_source_period(roots):
    """Catches a projection (source 1), a season or range total (other split types), or
    another period's line being published (R2.1)."""
    entry = made_up_entry(
        [
            real_line(),
            real_line(statSourceId=1),
            real_line(statSplitTypeId=0),
            real_line(scoringPeriodId=37),
            real_line(externalId="9", stats={"0": 1.0}),
        ]
    )
    lines = make_fixtures.stat_lines(entry, 36, 1)
    assert [line["externalId"] for line in lines] == ["823471", "9"]


def test_a_kept_line_has_the_five_allowlisted_keys_and_the_fixture_period(roots):
    """Catches a field outside the allowlist surviving (R2.2) or the period not being
    renumbered (R1.3); `stats` must be copied whole."""
    lines = make_fixtures.stat_lines(made_up_entry([real_line()]), 36, 1)
    assert lines == [
        {
            "scoringPeriodId": 1,
            "statSourceId": 0,
            "statSplitTypeId": 5,
            "externalId": "823471",
            "stats": {"0": 4.0, "1": 2.0},
        }
    ]
    assert tuple(lines[0]) == make_fixtures.ESPN_STAT_LINE_FIELDS


def test_the_rebuilt_entry_has_stats_only_when_a_line_was_kept(roots):
    """Catches an empty `stats` key on an entry with no line (R2.3), and a lost roster
    field (R2.4): the rest of the entry is what the allowlist gave before."""
    with_line = make_fixtures.rebuild_roster_entry(made_up_entry([real_line()]), 36, 1)
    without = make_fixtures.rebuild_roster_entry(
        made_up_entry([real_line(statSourceId=1), real_line(scoringPeriodId=37)]), 36, 1
    )
    bare = made_up_entry([])
    del bare["playerPoolEntry"]["player"]["stats"]
    none_at_all = make_fixtures.rebuild_roster_entry(bare, 36, 1)
    expected = make_fixtures.rebuild(made_up_entry([]), make_fixtures.ESPN_ROSTER_ENTRY_FIELDS)
    assert "stats" in with_line["playerPoolEntry"]["player"]
    assert without == expected and none_at_all == expected
    assert "stats" not in without["playerPoolEntry"]["player"]
    stripped = json.loads(json.dumps(with_line))
    del stripped["playerPoolEntry"]["player"]["stats"]
    assert stripped == expected
    assert "userProfile" not in with_line and "firstName" not in str(with_line)


def test_an_entry_with_no_player_gets_none_invented():
    """Catches a `playerPoolEntry.player` created only to hold stats."""
    rebuilt = make_fixtures.rebuild_roster_entry({"playerId": 5}, 36, 1)
    assert rebuilt == {"playerId": 5}


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


def test_committed_pro_schedule_fixture_is_the_allowlist_and_the_fixture_dates():
    """Catches a field outside the allowlist reaching the committed pro schedule (a team
    name, a flag), a wrong period slice, and games off the MLB fixture dates, which would
    put the fixture's period 1 on the wrong day."""
    from datetime import UTC, datetime
    from zoneinfo import ZoneInfo

    root = Path(__file__).resolve().parents[2] / "fixtures/landing"
    captures = list(
        LandingZone(root).committed(
            source="espn", endpoint="pro_schedule", partitions={"season": 2026}
        )
    )
    assert len(captures) == 1
    assert captures[0].meta["partitions"] == {"season": 2026}
    assert captures[0].meta["request_key"] == "view=proTeamSchedules_wl"
    payload = captures[0].payload
    assert set(payload) == {"settings"} and set(payload["settings"]) == {"proTeams"}
    teams = payload["settings"]["proTeams"]
    assert len(teams) == 31
    games_by_period: dict[str, list[dict]] = {}
    for team in teams:
        assert set(team) <= {"id", "proGamesByScoringPeriod"}
        for period, games in team.get("proGamesByScoringPeriod", {}).items():
            for game in games:
                assert set(game) == {
                    "id",
                    "date",
                    "scoringPeriodId",
                    "homeProTeamId",
                    "awayProTeamId",
                }
                assert str(game["scoringPeriodId"]) == period
                games_by_period.setdefault(period, []).append(game)
    assert set(games_by_period) == {"1", "2"}
    expected = {"1": (15, "2026-04-29"), "2": (11, "2026-04-30")}
    for period, (count, day) in expected.items():
        assert len({g["id"] for g in games_by_period[period]}) == count
        assert len(games_by_period[period]) == 2 * count  # listed under both teams
        for game in games_by_period[period]:
            local = (
                datetime.fromtimestamp(game["date"] / 1000, UTC)
                .astimezone(ZoneInfo("America/New_York"))
                .date()
            )
            assert local.isoformat() == day


def committed_rosters_and_games(root: Path, season: int) -> tuple[list, dict[str, set[str]]]:
    """(capture, period) of every committed roster of the season, and the pro schedule's
    game ids by period."""
    zone = LandingZone(root)
    rosters = [
        (capture, capture.meta["partitions"]["scoring_period"])
        for capture in zone.committed(source="espn", endpoint="roster")
        if capture.meta["partitions"]["season"] == season
    ]
    (schedule,) = zone.committed(
        source="espn", endpoint="pro_schedule", partitions={"season": season}
    )
    games: dict[str, set[str]] = {}
    for team in schedule.payload["settings"]["proTeams"]:
        for period, listed in team.get("proGamesByScoringPeriod", {}).items():
            games.setdefault(period, set()).update(str(game["id"]) for game in listed)
    return rosters, games


def test_committed_roster_fixtures_carry_allowlisted_lines_of_scheduled_games():
    """Catches a projected or season-total line, a field outside the allowlist, a line of
    another period, a game that is not in the pro schedule fixture for the same period (the
    rosters and the schedule from different days, R1.1), an empty `stats` key on an entry
    without lines, and a fixture with no real line to compare in either period."""
    root = Path(__file__).resolve().parents[2] / "fixtures/landing"
    rosters, games = committed_rosters_and_games(root, 2026)
    assert sorted(period for _, period in rosters) == [1, 2]
    for capture, period in rosters:
        payload = capture.payload
        assert payload["scoringPeriodId"] == period
        non_empty = 0
        for team in payload["teams"]:
            for entry in team["roster"]["entries"]:
                player = entry["playerPoolEntry"]["player"]
                lines = player.get("stats")
                if lines is None:
                    assert "stats" not in player
                    continue
                assert lines, "an entry with no line must have no stats key"
                for line in lines:
                    # Spelled out here, not read from the script: widening the script's
                    # allowlist must fail this test, not move it.
                    assert set(line) == {
                        "scoringPeriodId",
                        "statSourceId",
                        "statSplitTypeId",
                        "externalId",
                        "stats",
                    }
                    assert line["statSourceId"] == 0 and line["statSplitTypeId"] == 5
                    assert line["scoringPeriodId"] == period
                    assert line["externalId"].isdigit()
                    assert line["externalId"] in games[str(period)]
                    non_empty += bool(line["stats"])
        assert non_empty > 0
