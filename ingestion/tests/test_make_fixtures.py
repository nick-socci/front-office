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


def land_pro_schedule(raw, games_by_period: dict[str, list[str]], season: int = 2026):
    """Land a made-up pro schedule (2026 unless told): period -> Eastern times of its games."""
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
        {"season": season},
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


def test_boxscore_fixtures_and_the_correction_are_read_and_written_as_directories(
    roots, monkeypatch
):
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
    monkeypatch.setattr(make_fixtures, "FIXTURE_HISTORY_GAME_PKS", ())
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


# -- the 2025 past season (spec 0085, R3) ------------------------------------------------------

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures/landing"
PAST_DATES = ("2025-03-18", "2025-03-19")


def eastern_day(epoch_ms: int) -> str:
    from datetime import UTC, datetime
    from zoneinfo import ZoneInfo

    local = datetime.fromtimestamp(epoch_ms / 1000, UTC).astimezone(ZoneInfo("America/New_York"))
    return local.date().isoformat()


def committed_of_season(season: int) -> list:
    zone = LandingZone(FIXTURES)
    return [
        capture
        for source in ("espn", "mlb", "idmap")
        for capture in zone.committed(source=source)
        if capture.meta["partitions"].get("season") == season
    ]


def leaf_paths(node, prefix=""):
    """Dotted paths down to the first non-dict value (lists and scalars are leaves)."""
    if not isinstance(node, dict):
        yield prefix
        return
    for key, value in node.items():
        yield from leaf_paths(value, f"{prefix}.{key}" if prefix else key)


def only_allowed(payload, allowed: set[str]) -> None:
    for path in leaf_paths(payload):
        assert path in allowed or any(path.startswith(a + ".") for a in allowed), path


def test_the_2025_fixture_season_holds_four_captures_and_nothing_else():
    """Catches a 2025 roster, team, transaction, boxscore or id-map capture in the fixtures
    (R3.1), or one of the four wanted captures missing."""
    captures = committed_of_season(2025)
    kinds = sorted((c.meta["source"], c.meta["endpoint"]) for c in captures)
    assert kinds == [
        ("espn", "matchups"),
        ("espn", "pro_schedule"),
        ("espn", "settings"),
        ("mlb", "schedule"),
    ]


def test_the_2025_settings_fixture_is_the_allowlist_of_the_fixture_league():
    """Catches a field outside the settings allowlist, the real league id or name, or a
    season not cut to the two fixture periods (R3.1, R3.2)."""
    (capture,) = (c for c in committed_of_season(2025) if c.meta["endpoint"] == "settings")
    assert capture.meta["partitions"] == {"season": 2025, "league_id": "111111"}
    payload = capture.payload
    allowed = {
        "id",
        "seasonId",
        "scoringPeriodId",
        "settings.name",
        "settings.size",
        "settings.scoringSettings.scoringType",
        "settings.scoringSettings.scoringItems",
        "settings.scheduleSettings.playoffTeamCount",
        "status.currentMatchupPeriod",
        "status.latestScoringPeriod",
        "status.finalScoringPeriod",
        "status.isActive",
        "settings.rosterSettings.lineupSlotCounts",
    }
    only_allowed(payload, allowed)
    assert payload["id"] == "111111" and payload["seasonId"] == 2025
    assert payload["settings"]["name"] == "Fixture League"
    assert payload["status"]["latestScoringPeriod"] == 2
    assert payload["status"]["finalScoringPeriod"] == 2
    for item in payload["settings"]["scoringSettings"]["scoringItems"]:
        assert set(item) <= {"statId", "isReverseItem", "points"}


def test_the_2025_matchups_fixture_is_two_allowlisted_matchups_of_two_periods():
    """Catches a field outside the matchup allowlist, more or fewer than two matchups, or a
    pointsByScoringPeriod left at its real span instead of periods 1 and 2 (R3.1)."""
    (capture,) = (c for c in committed_of_season(2025) if c.meta["endpoint"] == "matchups")
    assert capture.meta["partitions"] == {"season": 2025, "league_id": "111111"}
    payload = capture.payload
    assert set(payload) == {"id", "seasonId", "schedule"}
    assert payload["id"] == "111111" and payload["seasonId"] == 2025
    assert len(payload["schedule"]) == 2
    allowed = {"id", "matchupPeriodId", "winner", "playoffTierType"}
    for side in ("home", "away"):
        allowed |= {
            f"{side}.teamId",
            f"{side}.cumulativeScore.wins",
            f"{side}.cumulativeScore.losses",
            f"{side}.cumulativeScore.ties",
            f"{side}.cumulativeScore.scoreByStat",
            f"{side}.pointsByScoringPeriod",
        }
    kept = set()
    for matchup in payload["schedule"]:
        only_allowed(matchup, allowed)
        for side in ("home", "away"):
            kept |= set(matchup[side]["pointsByScoringPeriod"])
    assert kept == {"1", "2"}


def test_the_2025_pro_schedule_is_periods_one_and_two_on_the_tokyo_dates():
    """Catches a wrong period slice, a field outside the allowlist, or periods that are not
    on 2025-03-18 and 2025-03-19, which would put the fixture's opening day wrong (R3.2)."""
    (capture,) = (c for c in committed_of_season(2025) if c.meta["endpoint"] == "pro_schedule")
    assert capture.meta["partitions"] == {"season": 2025}
    assert capture.meta["request_key"] == "view=proTeamSchedules_wl"
    payload = capture.payload
    assert set(payload) == {"settings"} and set(payload["settings"]) == {"proTeams"}
    days: dict[str, set[str]] = {}
    for team in payload["settings"]["proTeams"]:
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
                days.setdefault(period, set()).add(eastern_day(game["date"]))
    assert days == {"1": {"2025-03-18"}, "2": {"2025-03-19"}}


def test_the_2025_mlb_schedule_has_regular_season_games_on_exactly_the_two_dates():
    """Catches an MLB schedule on other dates than ESPN's periods 1 and 2, or one with a
    non-regular-season game or no game on a date (R3.2)."""
    (capture,) = (c for c in committed_of_season(2025) if c.meta["source"] == "mlb")
    assert capture.meta["partitions"] == {"season": 2025, "game_type": "R"}
    days = capture.payload["dates"]
    assert tuple(day["date"] for day in days) == PAST_DATES
    for day in days:
        assert day["games"]
        assert {game["gameType"] for game in day["games"]} == {"R"}


def test_the_2026_fixture_season_is_untouched_by_the_past_season():
    """Catches the 2026 captures changing in number: the past season is added beside them
    (R3.3). Their bytes are held by git; this holds the set."""
    kinds = {(c.meta["source"], c.meta["endpoint"]) for c in committed_of_season(2026)}
    assert kinds == {
        ("espn", "matchups"),
        ("espn", "pro_schedule"),
        ("espn", "roster"),
        ("espn", "settings"),
        ("espn", "teams"),
        ("espn", "transactions"),
        ("mlb", "boxscore"),
        ("mlb", "schedule"),
    }


def test_the_date_check_runs_on_the_season_it_is_given(roots):
    """Catches a date check reading the 2026 pro schedule for a past season: 2026 is wrong
    for periods 1 and 2 here and 2025 is right, so only a per-season read passes."""
    raw, _fixtures = roots
    land_pro_schedule(raw, {"1": ["2026-09-01T19:05"], "2": ["2026-09-02T19:05"]}, season=2026)
    land_pro_schedule(
        raw,
        {"1": ["2025-03-18T06:10"], "2": ["2025-03-19T06:10"], "3": ["2025-03-27T19:05"]},
        season=2025,
    )
    make_fixtures.check_source_periods_are_the_fixture_dates((1, 2), PAST_DATES, season=2025)


def test_a_past_period_off_its_expected_date_stops_generation(roots):
    """Catches generation going on when ESPN's period 2 of 2025 is not 2025-03-19 (R3.2):
    the message names the period, the date found and the date wanted."""
    raw, _fixtures = roots
    land_pro_schedule(raw, {"1": ["2025-03-18T06:10"], "2": ["2025-03-20T19:05"]}, season=2025)
    with pytest.raises(SystemExit) as stop:
        make_fixtures.check_source_periods_are_the_fixture_dates((1, 2), PAST_DATES, season=2025)
    message = str(stop.value)
    assert "period 2" in message and "2025-03-20" in message and "2025-03-19" in message


def land_schedule(raw, days: dict[str, list[str]], season: int = 2025):
    """Land a made-up MLB schedule: date -> gameType of each game that day."""
    land(
        raw,
        "mlb",
        "schedule",
        {"season": season, "game_type": "R"},
        "20260501T000000Z",
        {
            "dates": [
                {"date": day, "games": [{"gamePk": i, "gameType": t} for i, t in enumerate(types)]}
                for day, types in days.items()
            ]
        },
    )


def test_mlb_games_on_both_past_dates_pass(roots):
    """Catches the MLB check rejecting a correct schedule, or reading another season's."""
    raw, _fixtures = roots
    land_schedule(raw, {"2025-03-18": ["R"], "2025-03-19": ["R", "R"], "2025-03-27": ["R"]})
    land_schedule(raw, {"2026-04-29": ["R"]}, season=2026)
    make_fixtures.check_mlb_has_games_on_the_fixture_dates(PAST_DATES, season=2025)


@pytest.mark.parametrize(
    "days",
    [
        {"2025-03-18": ["R"]},
        {"2025-03-18": ["R"], "2025-03-19": []},
        {"2025-03-18": ["R"], "2025-03-19": ["S"]},
    ],
    ids=["date absent", "date with no game", "date with spring training only"],
)
def test_mlb_without_regular_season_games_on_a_date_stops_generation(roots, days):
    """Catches generation going on with no regular-season MLB game on one of the dates
    (R3.2), including a date that holds only another game type."""
    raw, _fixtures = roots
    land_schedule(raw, days)
    with pytest.raises(SystemExit) as stop:
        make_fixtures.check_mlb_has_games_on_the_fixture_dates(PAST_DATES, season=2025)
    assert "2025-03-19" in str(stop.value)


def test_the_season_builders_take_their_captures_from_the_season_they_are_given(roots):
    """Catches settings, matchups or the MLB schedule chosen from the newest path of any
    season, and a past season written under 2026 (R3.1)."""
    raw, fixtures = roots
    for season, stamp in ((2025, "20250101T000000Z"), (2026, "20260101T000000Z")):
        partitions = {"season": season, "league_id": "7"}
        status = {"latestScoringPeriod": 196, "finalScoringPeriod": 188}
        scoring = {"scoringType": "H2H_CATEGORY", "scoringItems": []}
        settings = {"id": 7, "seasonId": season, "status": status}
        settings["settings"] = {"name": "Real Name", "scoringSettings": scoring}
        land(raw, "espn", "settings", partitions, stamp, settings)
        schedule = [{"id": n, "matchupPeriodId": 1} for n in range(5)]
        land(raw, "espn", "matchups", partitions, stamp, {"seasonId": season, "schedule": schedule})
    land_schedule(raw, {"2025-03-18": ["R"], "2025-03-19": ["R"]})
    land_schedule(raw, {"2026-04-29": ["R"]}, season=2026)

    settings_path = make_fixtures.build_espn_settings(2025, (1, 2), "20250319T160000Z")
    matchups_path = make_fixtures.build_espn_matchups(2025, (1, 2), "20250319T160000Z")
    schedule_path = make_fixtures.build_mlb_schedule(PAST_DATES, 2025, "20250319T160000Z")

    assert settings_path.is_relative_to(fixtures / "espn/settings/season=2025")
    assert matchups_path.is_relative_to(fixtures / "espn/matchups/season=2025")
    assert schedule_path.is_relative_to(fixtures / "mlb/schedule/season=2025")
    settings = json.loads(settings_path.read_text())
    assert settings["seasonId"] == 2025 and settings["id"] == "111111"
    assert settings["settings"]["name"] == "Fixture League"
    assert settings["status"] == {"latestScoringPeriod": 2, "finalScoringPeriod": 2}
    assert len(json.loads(matchups_path.read_text())["schedule"]) == 2
    days = json.loads(schedule_path.read_text())["dates"]
    assert [d["date"] for d in days] == list(PAST_DATES)


def test_the_league_check_runs_per_season(roots):
    """Catches the one-league guard looking at 2026 only: two leagues landed for 2025 stop
    generation, and 2026's single league does not hide them."""
    raw, _fixtures = roots
    land(raw, "espn", "settings", {"season": 2026, "league_id": "7"}, "20260101T000000Z", {})
    for league in ("7", "8"):
        land(raw, "espn", "matchups", {"season": 2025, "league_id": league}, "20250101T000000Z", {})
    make_fixtures.check_one_league(2026)
    with pytest.raises(SystemExit) as stop:
        make_fixtures.check_one_league(2025)
    assert "2 leagues" in str(stop.value)


# -- the seven-period fixture season (spec 0093) -------------------------------------------------

SOURCE_PERIODS = (31, 36, 37)
SEASON_DATES = ("2026-04-24", "2026-04-29", "2026-04-30")


def land_roster(raw, source_period: int, player_ids=(5,), lines_period: int | None = None):
    """Land a made-up roster of one source period; each entry has one game line."""
    period = source_period if lines_period is None else lines_period
    entries = [
        made_up_entry([real_line(scoringPeriodId=period)]) | {"playerId": p} for p in player_ids
    ]
    land(
        raw,
        "espn",
        "roster",
        {"season": 2026, "league_id": "7", "scoring_period": source_period},
        "20260501T000000Z",
        {"seasonId": 2026, "teams": [{"id": 1, "roster": {"entries": entries}}]},
    )


def test_pro_schedule_periods_are_numbered_by_offset_from_the_first(roots):
    """Catches numbering by position (31, 36, 37 -> 1, 2, 3), which would put 04-29 on
    period 2 and the schedule off its dates; and 2025's (1, 2) moving at all (R1.2)."""
    raw, _fixtures = roots
    land_pro_schedule(
        raw,
        {"31": ["2026-04-24T19:05"], "36": ["2026-04-29T19:05"], "37": ["2026-04-30T19:05"]},
    )
    land_pro_schedule(
        raw, {"1": ["2025-03-18T06:10"], "2": ["2025-03-19T06:10"], "3": ["2025-03-27T19:05"]}, 2025
    )
    path = make_fixtures.build_espn_pro_schedule(2026, SOURCE_PERIODS)
    (team,) = json.loads(path.read_text())["settings"]["proTeams"]
    by_period = team["proGamesByScoringPeriod"]
    assert list(by_period) == ["1", "6", "7"]
    for period, games in by_period.items():
        assert {game["scoringPeriodId"] for game in games} == {int(period)}
    past = make_fixtures.build_espn_pro_schedule(2025, (1, 2), "20250319T160000Z")
    (past_team,) = json.loads(past.read_text())["settings"]["proTeams"]
    assert list(past_team["proGamesByScoringPeriod"]) == ["1", "2"]


def test_roster_fixtures_and_their_game_lines_are_numbered_by_offset(roots, monkeypatch):
    """Catches rosters (partition, payload, and the scoringPeriodId of each stat line)
    numbered by position instead of offset (R1.2), and 2025-style (1, 2) changing."""
    raw, fixtures = roots
    for source in SOURCE_PERIODS:
        land_roster(raw, source)
    monkeypatch.setattr(make_fixtures, "FIXTURE_SOURCE_SCORING_PERIODS", SOURCE_PERIODS)
    paths = make_fixtures.build_espn_rosters()
    assert [p.parent.parent.name for p in paths] == [
        "scoring_period=1",
        "scoring_period=6",
        "scoring_period=7",
    ]
    for path, number in zip(paths, (1, 6, 7), strict=True):
        payload = json.loads(path.read_text())
        assert payload["scoringPeriodId"] == number
        (entry,) = payload["teams"][0]["roster"]["entries"]
        assert [
            line["scoringPeriodId"] for line in entry["playerPoolEntry"]["player"]["stats"]
        ] == [number]
    monkeypatch.setattr(make_fixtures, "FIXTURE_SOURCE_SCORING_PERIODS", (1, 2))
    for source in (1, 2):
        land_roster(raw, source)
    paths = make_fixtures.build_espn_rosters()
    assert [json.loads(p.read_text())["scoringPeriodId"] for p in paths] == [1, 2]
    assert fixtures in paths[0].parents


def land_settings_and_matchups(raw, season: int):
    partitions = {"season": season, "league_id": "7"}
    status = {"latestScoringPeriod": 196, "finalScoringPeriod": 188}
    scoring = {"scoringType": "H2H_CATEGORY", "scoringItems": []}
    settings = {"id": 7, "seasonId": season, "scoringPeriodId": 99, "status": status}
    settings["settings"] = {"name": "Real Name", "scoringSettings": scoring}
    land(raw, "espn", "settings", partitions, "20260101T000000Z", settings)
    points = {str(n): 1.0 for n in range(1, 41)}
    side = {"teamId": 1, "pointsByScoringPeriod": points}
    schedule = [{"id": n, "matchupPeriodId": 1, "home": side, "away": side} for n in range(5)]
    land(
        raw,
        "espn",
        "matchups",
        partitions,
        "20260101T000000Z",
        {"seasonId": season, "schedule": schedule},
    )


def test_settings_say_the_span_and_matchup_keys_are_trimmed_not_offset(roots):
    """Catches settings counting source periods (3) instead of the span (7), and matchup
    keys being offset or cut to the count: they stay 1 to 7 (R1.3)."""
    raw, _fixtures = roots
    land_settings_and_matchups(raw, 2026)
    settings = json.loads(make_fixtures.build_espn_settings(2026, SOURCE_PERIODS).read_text())
    assert settings["scoringPeriodId"] == 7
    assert settings["status"] == {"latestScoringPeriod": 7, "finalScoringPeriod": 7}
    matchups = json.loads(make_fixtures.build_espn_matchups(2026, SOURCE_PERIODS).read_text())
    for matchup in matchups["schedule"]:
        for side in ("home", "away"):
            assert sorted(matchup[side]["pointsByScoringPeriod"], key=int) == [
                str(n) for n in range(1, 8)
            ]


def test_the_helpers_give_the_2025_numbers_unchanged():
    """Catches the offset helpers changing what (1, 2) gives today: 1, 2 and span 2."""
    assert [make_fixtures.fixture_period_number(s, (1, 2)) for s in (1, 2)] == [1, 2]
    assert make_fixtures.fixture_span((1, 2)) == 2
    assert [make_fixtures.fixture_period_number(s, SOURCE_PERIODS) for s in SOURCE_PERIODS] == [
        1,
        6,
        7,
    ]
    assert make_fixtures.fixture_span(SOURCE_PERIODS) == 7


def test_the_2026_fixture_season_constants_are_the_seven_periods():
    """Catches the constants not being moved to 2026-04-24 and real periods 31, 36, 37 (R1.1)."""
    assert make_fixtures.DEFAULT_DATES == SEASON_DATES
    assert make_fixtures.FIXTURE_SOURCE_SCORING_PERIODS == SOURCE_PERIODS
    assert make_fixtures.FIXTURE_HISTORY_GAME_PKS == (824854,)


def made_up_side(players: dict | None = None) -> dict:
    return {
        "team": {"id": 1},
        "teamStats": {"batting": {"hits": 3, "runs": 1, "atBats": 9}},
        "players": players
        or {"ID1": {"stats": {"batting": {"hits": 3, "runs": 1, "atBats": 9, "gamesPlayed": 1}}}},
    }


def land_game(raw, game_pk: int, home_players: dict | None = None):
    land(
        raw,
        "mlb",
        "boxscore",
        {"season": 2026, "game_pk": game_pk},
        "20260501T000000Z",
        {"teams": {"home": made_up_side(home_players), "away": made_up_side()}},
    )


def land_season_schedule(raw, games_by_date: dict[str, list[int]]):
    final = {"detailedState": "Final"}
    land(
        raw,
        "mlb",
        "schedule",
        {"season": 2026, "game_type": "R"},
        "20260501T000000Z",
        {
            "dates": [
                {"date": day, "games": [{"gamePk": pk, "status": final} for pk in pks]}
                for day, pks in games_by_date.items()
            ]
        },
    )


def test_an_earlier_date_does_not_displace_the_two_later_games(roots, monkeypatch):
    """Catches the earlier date's lower game ids (50, 100) displacing the two later games
    (R2.2): the later games are chosen from the last two dates, the named history game is
    appended, and the correction snapshot is of the first one written (R2.4)."""
    raw, _fixtures = roots
    land_season_schedule(
        raw,
        {"2026-04-24": [100, 50], "2026-04-29": [300, 200], "2026-04-30": [400]},
    )
    for pk in (50, 100, 200, 300, 400):
        land_game(raw, pk)
    monkeypatch.setattr(make_fixtures, "FIXTURE_HISTORY_GAME_PKS", (100,))
    written = make_fixtures.build_mlb_boxscores(SEASON_DATES)
    games = [
        json.loads((p.parent / "meta.json").read_text())["partitions"]["game_pk"] for p in written
    ]
    assert games == [200, 300, 100, 200]
    assert [p.parent.name for p in written][-1] == (
        f"fetched_at={make_fixtures.CORRECTION_FETCHED_AT}"
    )


def test_a_history_game_that_is_not_landed_stops_generation(roots, monkeypatch):
    """Catches a missing named game being skipped like an ordinary one: the fixture would
    regenerate with no earlier start and an empty pool (R2.2)."""
    raw, _fixtures = roots
    land_season_schedule(raw, {"2026-04-29": [200], "2026-04-30": [400]})
    land_game(raw, 200)
    monkeypatch.setattr(make_fixtures, "FIXTURE_HISTORY_GAME_PKS", (100,))
    with pytest.raises(SystemExit) as stop:
        make_fixtures.build_mlb_boxscores(SEASON_DATES)
    assert "100" in str(stop.value)


# -- the purpose check: a free agent starts on the earlier day and again later (spec 0093, R3) ----


def pitcher(person_id: int, *, started: int = 1, outs: int = 15, faced: int = 20, pa: int = 0):
    """One boxscore player entry: a pitcher's line, and his own plate appearances if any."""
    return {
        f"ID{person_id}": {
            "person": {"id": person_id},
            "stats": {
                "pitching": {"gamesStarted": started, "outs": outs, "battersFaced": faced},
                "batting": {"plateAppearances": pa},
            },
        }
    }


def land_id_map(raw, pairs: dict[int, int]):
    """Land a made-up id map: MLB person id -> ESPN player id."""
    rows = [{"MLBID": str(mlb), "ESPNID": str(espn)} for mlb, espn in pairs.items()]
    land(raw, "idmap", "player_id_map", {"provider": "sfbb"}, "20260501T000000Z", rows)


def start_pool_zone(
    raw,
    monkeypatch,
    *,
    earlier: dict | None,
    later: dict | None,
    rostered_later: tuple[int, ...] = (),
    id_map: dict[int, int] | None = None,
):
    """A landing zone where game 100 is the history game (04-24, period 31), game 200 is
    played on 04-29 (period 36) and game 300 on 04-30 (period 37)."""
    monkeypatch.setattr(make_fixtures, "FIXTURE_HISTORY_GAME_PKS", (100,))
    land_season_schedule(raw, {"2026-04-24": [100], "2026-04-29": [200], "2026-04-30": [300]})
    land_game(raw, 100, earlier)
    land_game(raw, 200, later)
    land_game(raw, 300)
    land_roster(raw, 31, player_ids=(9011,))  # rostered on the earlier day: irrelevant
    land_roster(raw, 36, player_ids=rostered_later or (9999,))
    land_roster(raw, 37)
    land_id_map(raw, {11: 9011} if id_map is None else id_map)


def check_start_pool():
    make_fixtures.check_a_free_agent_starts_on_the_earlier_day_and_again_later(SEASON_DATES)


def test_a_free_agent_who_starts_on_both_days_passes(roots, monkeypatch):
    """Catches the check refusing a good fixture, or counting a roster of the EARLIER day
    against the pitcher (he is rostered on 04-24 here and free on 04-29)."""
    raw, _fixtures = roots
    start_pool_zone(raw, monkeypatch, earlier=pitcher(11), later=pitcher(11))
    check_start_pool()


def test_a_pitcher_with_no_id_map_row_counts_as_unrostered(roots, monkeypatch):
    """Catches an unresolved pitcher being treated as rostered: in the model an unresolved
    roster entry has no mlbam_player_id, so he is a free agent."""
    raw, _fixtures = roots
    start_pool_zone(raw, monkeypatch, earlier=pitcher(11), later=pitcher(11), id_map={})
    check_start_pool()


def test_no_start_in_the_earlier_game_fails_condition_a(roots, monkeypatch):
    """Catches a history game in which nobody started (a wrong named game) passing (R3.1a)."""
    raw, _fixtures = roots
    start_pool_zone(raw, monkeypatch, earlier=pitcher(11, started=0), later=pitcher(11))
    with pytest.raises(SystemExit) as stop:
        check_start_pool()
    assert "(a)" in str(stop.value) and "100" in str(stop.value)


def test_an_earlier_start_with_no_outs_fails_condition_a(roots, monkeypatch):
    """Catches a start with no outs recorded counting as a starter's earlier appearance:
    fo_replacement_group would not call it SP (R3.1a)."""
    raw, _fixtures = roots
    start_pool_zone(raw, monkeypatch, earlier=pitcher(11, outs=0), later=pitcher(11))
    with pytest.raises(SystemExit) as stop:
        check_start_pool()
    assert "(a)" in str(stop.value)


def test_an_earlier_start_with_more_plate_appearances_than_batters_faced_fails_a(
    roots, monkeypatch
):
    """Catches a two-way player's batting being read as a pitcher's role (R3.1a)."""
    raw, _fixtures = roots
    start_pool_zone(raw, monkeypatch, earlier=pitcher(11, faced=3, pa=4), later=pitcher(11))
    with pytest.raises(SystemExit) as stop:
        check_start_pool()
    assert "(a)" in str(stop.value)


def test_no_later_start_by_the_earlier_starter_fails_condition_b(roots, monkeypatch):
    """Catches a fixture where the earlier starter never starts again, so the pool would
    have an SP with no start to count (R3.1b)."""
    raw, _fixtures = roots
    start_pool_zone(raw, monkeypatch, earlier=pitcher(11), later=pitcher(12))
    with pytest.raises(SystemExit) as stop:
        check_start_pool()
    message = str(stop.value)
    assert "(b)" in message and "(a)" not in message


def test_a_later_start_by_a_rostered_pitcher_fails_condition_c(roots, monkeypatch):
    """Catches a later start by a pitcher on a roster that day, who is not a free agent and
    so not in the pool (R3.1c); matched through the id map."""
    raw, _fixtures = roots
    start_pool_zone(
        raw, monkeypatch, earlier=pitcher(11), later=pitcher(11), rostered_later=(9011,)
    )
    with pytest.raises(SystemExit) as stop:
        check_start_pool()
    message = str(stop.value)
    assert "(c)" in message and "(a)" not in message and "(b)" not in message
