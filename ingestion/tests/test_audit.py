"""Tests for the landing-zone audit: the gate before landed data is trusted as evidence.

Each test builds a small world that audits clean, breaks one thing, and checks that the
audit names it. The clean world: one MLB game on opening day (2026-03-25), boxscore
captured on 2026-04-10 with its settle window still open at the audit's as-of instant,
2026-04-12; one ESPN league whose two scoring periods closed
before the run that captured them.
"""

import datetime as dt
import json
import shutil

import duckdb
import pytest
from typer.testing import CliRunner

from front_office.audit import (
    Severity,
    _ranges,
    check_espn,
    check_landing,
    eastern_date,
    run_audit,
)
from front_office.cli import app
from front_office.landing import LandingZone
from front_office.load import load_landing_zone

SEASON = 2026
LEAGUE = "1"
RUN = "20260327T160000Z"  # noon Eastern, 2026-03-27: period 3 is current
AS_OF = dt.datetime(2026, 4, 12, 12, 0, tzinfo=dt.UTC)  # the clean world's boxscore window is open
LATER = dt.datetime(2026, 5, 1, 12, 0, tzinfo=dt.UTC)


def land(
    zone,
    source,
    endpoint,
    partitions,
    payload,
    *,
    fetched_at=RUN,
    params=None,
    url=None,
    source_status=None,
):
    return zone.write(
        source=source,
        endpoint=endpoint,
        partitions=partitions,
        name=f"fetched_at={fetched_at}",
        payload=payload,
        request={"url": url or f"https://example.test/{endpoint}", "params": params or {}},
        fetched_at=fetched_at,
        source_status=source_status,
    )


def captures_of(zone, pattern):
    """Capture directories under the root matching a glob such as `mlb/boxscore/**`."""
    return sorted(zone.root.glob(f"{pattern}/fetched_at=*"))


def drop(zone, pattern, stamp="*"):
    """Remove whole captures (a capture is a directory) and any folder that leaves empty."""
    for directory in sorted(zone.root.glob(f"{pattern}/fetched_at={stamp}")):
        shutil.rmtree(directory)
        parent = directory.parent
        while parent != zone.root and not any(parent.iterdir()):
            parent.rmdir()
            parent = parent.parent


def schedule_game(pk, date, detailed="Final", **extra):
    # As MLB reports them: over-but-unplayed games are abstractGameState Final too.
    state = (
        "Final" if detailed in ("Final", "Completed Early", "Postponed", "Cancelled") else "Preview"
    )
    return {
        "gamePk": pk,
        "season": str(SEASON),
        "officialDate": date,
        "gameDate": f"{date}T18:00:00Z",
        "status": {"abstractGameState": state, "detailedState": detailed},
        **extra,
    }


def land_schedule(zone, games):
    # A capture is never overwritten now, so "the schedule changed" replaces the capture.
    drop(zone, "mlb/schedule/**")
    land(
        zone,
        "mlb",
        "schedule",
        {"season": SEASON, "game_type": "R"},
        {"dates": [{"games": games}]},
        params={"season": SEASON},
    )


def epoch_ms(stamp):
    """Epoch milliseconds, as ESPN writes a game's `date`, of an ISO UTC instant."""
    instant = dt.datetime.fromisoformat(stamp).replace(tzinfo=dt.UTC)
    return int(instant.timestamp() * 1000)


def pro_game(game_id, when, period):
    return {
        "id": game_id,
        "date": epoch_ms(when),
        "scoringPeriodId": period,
        "homeProTeamId": 1,
        "awayProTeamId": 2,
    }


def land_pro_schedule(zone, games, *, fetched_at="20260320T120000Z", payload=None):
    """A season-level pro schedule capture (no league_id), each game under both its teams,
    as ESPN lists it. `payload` replaces the whole thing, for malformed shapes."""
    if payload is None:
        by_team = {team: {str(game["scoringPeriodId"]): [] for game in games} for team in (1, 2)}
        for game in games:
            for team in (1, 2):
                by_team[team][str(game["scoringPeriodId"])].append(game)
        payload = {
            "settings": {
                "proTeams": [
                    {"id": team, "proGamesByScoringPeriod": periods}
                    for team, periods in by_team.items()
                ]
            }
        }
    land(
        zone,
        "espn",
        "pro_schedule",
        {"season": SEASON},
        payload,
        fetched_at=fetched_at,
        params={"view": "proTeamSchedules_wl"},
    )


def land_boxscore(zone, pk, fetched_at, payload=None):
    land(
        zone,
        "mlb",
        "boxscore",
        {"season": SEASON, "game_pk": pk},
        payload or {},
        fetched_at=fetched_at,
        params={"gamePk": pk},
    )


def land_players(zone, fetched_at=RUN):
    return land(zone, "mlb", "players", {"season": SEASON}, {"people": []}, fetched_at=fetched_at)


def land_settings(zone, *, latest, final=2, fetched_at=RUN, league=LEAGUE):
    status = {"firstScoringPeriod": 1, "latestScoringPeriod": latest, "finalScoringPeriod": final}
    land(
        zone,
        "espn",
        "settings",
        {"season": SEASON, "league_id": league},
        {"status": status},
        fetched_at=fetched_at,
        params={"view": "mSettings"},
    )


def land_roster(zone, period, fetched_at=RUN, source_status=None):
    land(
        zone,
        "espn",
        "roster",
        {"season": SEASON, "league_id": LEAGUE, "scoring_period": period},
        {"teams": []},
        fetched_at=fetched_at,
        params={"view": "mRoster", "scoringPeriodId": period},
        source_status=source_status,
    )


def land_transactions(zone, topics, *, offset=0, limit=2000, paged=True):
    partitions = {"season": SEASON, "league_id": LEAGUE}
    params = {"view": "kona_league_communication", "limit": limit}
    if paged:
        partitions["offset"] = offset
        params["offset"] = offset
    land(zone, "espn", "transactions", partitions, {"topics": topics}, params=params)


def topic(messages, total=None, topic_id="t"):
    return {"id": topic_id, "messages": [{}] * messages, "totalMessageCount": total or messages}


@pytest.fixture
def zone(tmp_path):
    zone = LandingZone(root=tmp_path / "raw")
    land_schedule(zone, [schedule_game(1, "2026-03-25")])
    land_boxscore(zone, 1, "20260410T160000Z")
    land_players(zone)
    land_pro_schedule(zone, [pro_game(401, "2026-03-25T20:00:00", 1)])
    land_settings(zone, latest=3)
    for period in (1, 2):
        land_roster(zone, period)
    for endpoint in ("teams", "matchups"):
        land(zone, "espn", endpoint, {"season": SEASON, "league_id": LEAGUE}, {})
    land_transactions(zone, [topic(1)])
    return zone


def audit(zone, *, load=True, as_of=AS_OF):
    con = duckdb.connect()
    if load:
        load_landing_zone(con, zone)
    return run_audit(zone, con, season=SEASON, as_of=as_of)


def problems(findings):
    return [(f.severity, f.check, f.detail) for f in findings if f.severity != Severity.INFO]


def details(findings, severity):
    return " | ".join(f.detail for f in findings if f.severity == severity)


def test_the_clean_world_audits_clean(zone):
    findings = audit(zone)
    assert problems(findings) == []
    info = details(findings, Severity.INFO)
    assert "all 10 committed capture(s) loaded" in info
    assert "1 settings capture(s) taken after the final period" in info
    assert "period 1 = 2026-03-25 per ESPN's schedule (20260320T120000Z, 1 games)" in info
    assert "2 of 2 rosters captured after their period closed" in info


def test_capture_dates_are_eastern_like_the_scoring_day():
    """The 2026-09-21 02:52 UTC settings snapshot belongs to the 20th in fantasy terms."""
    assert eastern_date("20260921T025212Z") == dt.date(2026, 9, 20)
    assert eastern_date("20260921T040000Z") == dt.date(2026, 9, 21)


# -- landing ---------------------------------------------------------------------------


def test_a_payload_without_a_sidecar_is_an_error(zone):
    """Was `payload_only`. A capture directory holding only its payload fails the capture
    check, which is the same condition in the directory layout."""
    sidecar = captures_of(zone, "mlb/boxscore/**")[0] / "meta.json"
    sidecar.unlink()
    findings, captures = check_landing(zone)
    assert "1 capture director(y/ies) that fail the capture check" in details(
        findings, Severity.ERROR
    )
    assert all(capture.endpoint != "boxscore" for capture in captures)


def test_a_sidecar_without_a_payload_is_an_error(zone):
    """Was `sidecar_only`; likewise a capture directory that fails the capture check."""
    (captures_of(zone, "mlb/boxscore/**")[0] / "payload.json").unlink()
    findings, captures = check_landing(zone)
    assert "1 capture director(y/ies) that fail the capture check" in details(
        findings, Severity.ERROR
    )
    assert all(capture.endpoint != "boxscore" for capture in captures)


def test_a_leftover_temp_directory_is_an_error(zone):
    """Was a temporary file; a write is now a temporary directory."""
    (zone.root / "mlb/boxscore/fetched_at=x.tmp-123").mkdir()
    findings, _ = check_landing(zone)
    assert "1 temporary director(y/ies) left by an interrupted write" in details(
        findings, Severity.ERROR
    )


def test_an_unreadable_payload_is_an_error_and_not_a_capture(zone):
    """A truncated payload no longer has the size its sidecar records, so it fails the
    capture check itself; it must be an error and withheld from the captures."""
    directory = captures_of(zone, "mlb/boxscore/**")[0]
    (directory / "payload.json").write_text('{"truncated": ')
    assert zone.check(directory) is not None
    findings, captures = check_landing(zone)
    assert "1 capture director(y/ies) that fail the capture check" in details(
        findings, Severity.ERROR
    )
    assert all(capture.endpoint != "boxscore" for capture in captures)


def test_a_sidecar_that_disagrees_with_its_path_is_an_error(zone):
    directory = captures_of(zone, "mlb/boxscore/**")[0]
    moved = directory.parent.parent / "game_pk=2" / directory.name
    moved.parent.mkdir()
    directory.rename(moved)
    directory.parent.rmdir()
    findings, _ = check_landing(zone)
    assert "sidecar describes mlb/boxscore/season=2026/game_pk=1/" in details(
        findings, Severity.ERROR
    )


def test_a_payload_that_changed_but_kept_its_size_is_a_deep_error_only(zone):
    """Catches corruption at rest going unreported: shallow says committed, the audit's
    deep check (R5.2) says error."""
    directory = captures_of(zone, "mlb/boxscore/**")[0]
    payload = directory / "payload.json"
    body = payload.read_text()
    payload.write_text(body.replace("{", "[", 1).replace("}", "]", 1))
    assert zone.check(directory) is None
    findings, captures = check_landing(zone)
    assert "1 capture(s) whose payload is unreadable or does not match its checksum" in details(
        findings, Severity.ERROR
    )
    assert all(capture.endpoint != "boxscore" for capture in captures)


def test_a_payload_that_is_not_json_is_a_deep_error(zone):
    """Catches an unparseable payload passing because its size matches."""
    directory = captures_of(zone, "mlb/boxscore/**")[0]
    meta_path = directory / "meta.json"
    meta = json.loads(meta_path.read_text())
    (directory / "payload.json").write_text("not json")
    meta.pop("payload_sha256")
    meta["payload_bytes"] = len("not json")
    meta_path.write_text(json.dumps(meta))
    assert zone.check(directory) is None
    findings, _ = check_landing(zone)
    assert "1 capture(s) whose payload is unreadable or does not match its checksum" in details(
        findings, Severity.ERROR
    )


def test_a_loose_file_and_an_empty_directory_are_errors(zone):
    """Catches debris that holds no capture: an old-layout file, an empty folder (R5.1)."""
    (zone.root / "mlb/schedule/stray.json").write_text("{}")
    (zone.root / "espn/roster/season=2026/league_id=9").mkdir(parents=True)
    findings, _ = check_landing(zone)
    errors = details(findings, Severity.ERROR)
    assert "1 loose file(s) outside any capture directory (old layout?)" in errors
    assert "1 empty director(y/ies)" in errors


def test_an_old_layout_pair_says_the_migration_must_run(zone):
    """Catches an unmigrated tree audited as merely untidy (R6.7)."""
    folder = zone.root / "mlb/schedule/season=2026/game_type=R"
    (folder / "fetched_at=20260101T000000Z.json").write_text("{}")
    (folder / "fetched_at=20260101T000000Z.meta.json").write_text("{}")
    findings, _ = check_landing(zone)
    layout = [f for f in findings if f.subject == "layout"]
    assert len(layout) == 1 and layout[0].severity == Severity.ERROR
    assert "migrate_landing_layout.py" in layout[0].detail


def test_a_clean_tree_has_no_layout_line_and_counts_checksums(zone):
    findings, _ = check_landing(zone)
    assert not [f for f in findings if f.subject == "layout"]
    info = details(findings, Severity.INFO)
    assert "10 capture(s) checksum-verified, 0 with no recorded checksum" in info


def test_a_capture_with_no_recorded_checksum_is_counted_not_failed(zone):
    directory = captures_of(zone, "mlb/boxscore/**")[0]
    meta_path = directory / "meta.json"
    meta = json.loads(meta_path.read_text())
    meta.pop("payload_sha256")
    meta.pop("payload_bytes")
    meta_path.write_text(json.dumps(meta))
    findings, _ = check_landing(zone)
    assert problems(findings) == []
    assert "9 capture(s) checksum-verified, 1 with no recorded checksum" in details(
        findings, Severity.INFO
    )


def test_a_non_empty_quarantine_is_a_warning_and_an_empty_one_is_not(zone):
    """Catches a forgotten quarantine (R5.3), and a warning for a quarantine that holds
    nothing (absent, or only its ignore file)."""
    assert [f for f in problems(check_landing(zone)[0])] == []
    zone.quarantine_root.mkdir()
    (zone.quarantine_root / ".gitignore").write_text("*\n")
    assert problems(check_landing(zone)[0]) == []
    (zone.quarantine_root / "20260930T000000Z" / "mlb").mkdir(parents=True)
    (zone.quarantine_root / "20260930T000000Z" / "mlb" / "x.json").write_text("{}")
    findings, _ = check_landing(zone)
    warnings = [f for f in findings if f.severity == Severity.WARN]
    assert len(warnings) == 1 and warnings[0].subject == "quarantine"
    assert "20260930T000000Z" in warnings[0].detail


# -- loaded ----------------------------------------------------------------------------


def test_an_unloaded_capture_is_an_error(zone):
    con = duckdb.connect()
    load_landing_zone(con, zone)
    land_boxscore(zone, 1, "20260420T160000Z")
    findings = run_audit(zone, con, season=SEASON, as_of=AS_OF)
    assert "1 committed capture(s) not in raw.api_responses" in details(findings, Severity.ERROR)


def test_a_warehouse_without_the_raw_table_is_an_error(zone):
    assert "table missing" in details(audit(zone, load=False), Severity.ERROR)


def test_captures_that_share_a_raw_key_are_an_error(zone):
    """Two leagues, same URL and parameters, same second: the loader now refuses to load
    them, so the audit sees them against a table loaded before the second one landed."""
    con = duckdb.connect()
    load_landing_zone(con, zone)
    land_settings(zone, latest=3, league="2")
    findings = run_audit(zone, con, season=SEASON, as_of=AS_OF)
    assert "2 captures share raw key" in details(findings, Severity.ERROR)


def test_a_capture_is_not_loaded_because_another_leagues_row_has_its_old_key(zone):
    """Catches an audit that compares on the pre-#28 key (R1.6).

    League 2's settings differ from league 1's only by URL path. Its row is loaded; the
    capture for league 3 is not. Compared on (source, endpoint, request_key, fetched_at)
    league 3 would count as loaded because leagues 1 and 2 hold that key.
    """
    con = duckdb.connect()
    load_landing_zone(con, zone)
    land_settings_at(zone, league="2")
    load_landing_zone(con, zone)
    land_settings_at(zone, league="3")
    findings = run_audit(zone, con, season=SEASON, as_of=AS_OF)
    assert "1 committed capture(s) not in raw.api_responses" in details(findings, Severity.ERROR)


def land_settings_at(zone, *, league):
    land(
        zone,
        "espn",
        "settings",
        {"season": SEASON, "league_id": league},
        {"status": {"firstScoringPeriod": 1, "latestScoringPeriod": 3, "finalScoringPeriod": 2}},
        params={"view": "mSettings"},
        url=f"https://example.test/leagues/{league}",
    )


def test_an_old_shape_raw_table_is_an_error_not_a_crash(zone):
    """Catches a SQL error when the audit meets a table with no request_path (R1.6)."""
    con = duckdb.connect()
    con.execute(
        "create schema raw; create table raw.api_responses (source varchar, endpoint varchar, "
        "request_key varchar, fetched_at varchar, payload json, file_path varchar)"
    )
    findings = run_audit(zone, con, season=SEASON, as_of=AS_OF)
    errors = details(findings, Severity.ERROR)
    assert "old shape" in errors
    assert "new warehouse file" in errors


# -- mlb -------------------------------------------------------------------------------


def test_a_played_game_without_a_boxscore_is_an_error(zone):
    land_schedule(zone, [schedule_game(1, "2026-03-25"), schedule_game(2, "2026-03-26")])
    assert "1 played game(s) with no boxscore; e.g. 2" in details(audit(zone), Severity.ERROR)


def test_unplayed_games_are_given_a_disposition(zone):
    land_schedule(
        zone,
        [
            schedule_game(1, "2026-03-25"),
            schedule_game(2, "2026-03-26", detailed="Postponed"),
            schedule_game(3, "2026-09-27", detailed="Scheduled"),
            schedule_game(4, "2026-09-27", detailed="Cancelled"),
        ],
    )
    findings = audit(zone)
    assert "4 scheduled, 1 played; not played: Cancelled 1, Postponed 1, Scheduled 1" in details(
        findings, Severity.INFO
    )
    assert problems(findings) == [], "a never-made-up postponement is not a played game"
    assert "no boxscore" not in details(findings, Severity.ERROR)


def rosters_only(*, batted=False):
    """A boxscore shaped like a cancelled game's: players listed, no appearances."""
    batting = {"gamesPlayed": 1, "atBats": 3} if batted else {}
    return {"teams": {"home": {"players": {"ID1": {"stats": {"batting": batting}}}}}}


def test_a_cancelled_games_boxscore_without_appearances_is_harmless(zone):
    land_schedule(
        zone, [schedule_game(1, "2026-03-25"), schedule_game(5, "2026-03-26", detailed="Cancelled")]
    )
    land_boxscore(zone, 5, "20260327T160000Z", rosters_only())
    findings = audit(zone)
    assert problems(findings) == []
    assert "1 boxscore(s) for games not played (Cancelled 1), with no appearances" in details(
        findings, Severity.INFO
    )


def test_a_not_played_games_boxscore_with_appearances_is_an_error(zone):
    land_schedule(
        zone, [schedule_game(1, "2026-03-25"), schedule_game(5, "2026-03-26", detailed="Cancelled")]
    )
    land_boxscore(zone, 5, "20260327T160000Z", rosters_only(batted=True))
    assert "1 boxscore(s) record appearances for games the newest schedule says were not" in (
        details(audit(zone), Severity.ERROR)
    )


def test_a_boxscore_for_an_unscheduled_game_is_a_warning(zone):
    land_boxscore(zone, 99, "20260326T160000Z", rosters_only())
    assert "1 boxscore(s) for games the newest schedule does not list; e.g. 99" in details(
        audit(zone), Severity.WARN
    )


def test_a_postponed_game_that_was_made_up_is_played(zone):
    land_schedule(
        zone,
        [
            schedule_game(1, "2026-03-24", detailed="Postponed"),
            schedule_game(1, "2026-03-25"),
        ],
    )
    assert problems(audit(zone)) == []


def settle_findings(findings):
    """The WARN and INFO text of the boxscore settle checks."""
    return details(findings, Severity.WARN) + " | " + details(findings, Severity.INFO)


def only_boxscores(zone, *stamps):
    drop(zone, "mlb/boxscore/**")
    for stamp in stamps:
        land_boxscore(zone, 1, stamp)


def test_a_settled_game_is_not_reported(zone):
    """Catches a game with a capture exactly 7 days after its first-final one being flagged."""
    only_boxscores(zone, "20260326T160000Z", "20260402T160000Z")
    findings = audit(zone)
    assert problems(findings) == []
    assert "settle window" not in settle_findings(findings)


def test_a_game_whose_window_closed_without_a_later_capture_warns_and_names_the_command(zone):
    """Catches a closed window going unreported, or advice that needs --refresh."""
    only_boxscores(zone, "20260326T160000Z", "20260330T160000Z")
    warning = details(audit(zone, as_of=LATER), Severity.WARN)
    assert "1 game(s) not captured after their settle window closed" in warning
    assert "`front-office backfill mlb --season 2026`" in warning
    assert "--refresh" not in warning
    assert "e.g. 1" in warning


def test_a_game_inside_its_window_is_information_not_a_warning(zone):
    """Catches an open window being reported as a problem."""
    only_boxscores(zone, "20260326T160000Z")
    findings = audit(zone, as_of=dt.datetime(2026, 3, 30, 12, 0, tzinfo=dt.UTC))
    assert problems(findings) == []
    assert "1 game(s) still in settle window" in details(findings, Severity.INFO)


def test_captures_only_before_the_last_start_warn(zone):
    """Catches a capture from before the game's last start counting as settle evidence."""
    land_schedule(zone, [schedule_game(1, "2026-03-25", gameDate="2026-03-25T18:00:00Z")])
    only_boxscores(zone, "20260325T100000Z", "20260325T120000Z")
    warning = details(audit(zone), Severity.WARN)
    assert "1 game(s) captured only before their last scheduled start; e.g. 1" in warning
    assert "settle window closed" not in warning
    assert "unreadable gameDate" not in warning


def test_a_game_with_no_readable_start_is_reported_as_such_and_never_settled(zone):
    """Catches an unreadable gameDate reported as 'captured before the start', or settling."""
    land_schedule(zone, [schedule_game(1, "2026-03-25", gameDate=None)])
    only_boxscores(zone, "20260326T160000Z", "20260420T160000Z")
    warning = details(audit(zone), Severity.WARN)
    assert "1 game(s) with an unreadable gameDate in the schedule" in warning
    assert "they cannot settle; e.g. 1" in warning
    assert "before their last scheduled start" not in warning
    assert "settle window closed" not in warning


def test_a_capture_whose_stamp_is_not_a_utc_stamp_is_reported_and_not_counted(zone):
    """Catches one odd fetched_at crashing the audit, or counting as the settling capture."""
    only_boxscores(zone, "20260326T160000Z", "2026-04-20")
    findings = audit(zone, as_of=LATER)
    warning = details(findings, Severity.WARN)
    assert "1 boxscore capture(s) with a fetched_at that is not a UTC stamp" in warning
    assert "1 game(s) not captured after their settle window closed" in warning


def test_a_game_whose_every_stamp_is_unreadable_is_not_called_captured_before_its_start(zone):
    """Catches a comparison with the start claimed for a game that has no readable stamp."""
    only_boxscores(zone, "2026-04-20")
    warning = details(audit(zone, as_of=LATER), Severity.WARN)
    assert "1 boxscore capture(s) with a fetched_at that is not a UTC stamp" in warning
    assert "1 game(s) have no other capture, so cannot settle; e.g. 1" in warning
    assert "before their last scheduled start" not in warning
    assert "settle window closed" not in warning


def test_an_unreadable_start_and_unreadable_stamps_are_both_reported(zone):
    """Catches one fault hiding the other when a game has neither a start nor a stamp."""
    land_schedule(zone, [schedule_game(1, "2026-03-25", gameDate=None)])
    only_boxscores(zone, "2026-04-20")
    warning = details(audit(zone, as_of=LATER), Severity.WARN)
    assert "1 game(s) with an unreadable gameDate in the schedule" in warning
    assert "1 game(s) have no other capture, so cannot settle; e.g. 1" in warning
    assert "before their last scheduled start" not in warning
    assert "settle window closed" not in warning


def test_a_resumed_game_is_judged_by_the_guard_not_by_resume_game_date(zone):
    """Catches resumeGameDate starting the clock for captures from before the later session."""
    land_schedule(
        zone,
        [
            schedule_game(1, "2026-03-25", resumeGameDate="2026-03-26"),
            schedule_game(1, "2026-03-25", gameDate="2026-04-05T18:00:00Z"),
        ],
    )
    only_boxscores(zone, "20260401T160000Z", "20260403T160000Z")
    findings = audit(zone)
    assert "1 game(s) captured only before their last scheduled start" in details(
        findings, Severity.WARN
    )
    assert "resumed" not in settle_findings(findings)


def cli_audit(zone, tmp_path, today):
    db = tmp_path / f"{today}.duckdb"
    with duckdb.connect(str(db)) as con:
        load_landing_zone(con, zone)
    args = ["audit", "--season", "2026", "--raw-root", str(zone.root), "--db", str(db)]
    return CliRunner().invoke(app, [*args, "--today", today]).output


def test_today_judges_the_window_by_the_end_of_that_eastern_day(zone, tmp_path):
    """Catches the as-of instant off by a day: the window closes 2026-04-02T16:00Z."""
    only_boxscores(zone, "20260326T160000Z")
    assert "1 game(s) still in settle window" in cli_audit(zone, tmp_path, "2026-04-01")
    closed = cli_audit(zone, tmp_path, "2026-04-02")
    assert "1 game(s) not captured after their settle window closed" in closed


def test_a_settling_capture_taken_after_today_still_counts(zone, tmp_path):
    """Catches --today read as a time machine that hides later captures."""
    only_boxscores(zone, "20260326T160000Z", "20260410T160000Z")
    output = cli_audit(zone, tmp_path, "2026-03-28")
    assert "settle window" not in output


# -- espn ------------------------------------------------------------------------------


def land_status(zone, status, fetched_at):
    """A settings capture whose status is exactly `status`, however malformed."""
    land(
        zone,
        "espn",
        "settings",
        {"season": SEASON, "league_id": LEAGUE},
        {"status": status},
        fetched_at=fetched_at,
        params={"view": "mSettings"},
    )


def test_captures_past_the_final_period_are_counted_and_never_compared_with_a_date(zone):
    """The 2026 situation: ESPN's counter stops one past the last pro game day, so five
    captures past the final period imply dates that are not opening day. Catches an
    audit that compares them (an ERROR) instead of counting them (R4.3)."""
    drop(zone, "espn/settings/**")
    stamps = {
        "20260926T162307Z": 186,
        "20260926T173627Z": 186,
        "20260928T225612Z": 188,
        "20261007T011005Z": 188,
        "20261007T171657Z": 188,
    }
    for stamp, latest in stamps.items():
        land_settings(zone, latest=latest, final=180, fetched_at=stamp)
    findings = audit(zone)
    assert "period 1" not in details(findings, Severity.ERROR)
    assert "different dates" not in details(findings, Severity.ERROR)
    assert (
        "5 settings capture(s) taken after the final period; their period counter is not "
        "compared with a date"
    ) in details(findings, Severity.INFO)


def test_an_in_progress_capture_off_opening_day_is_an_error_naming_it(zone):
    """Catches a shifted calendar going unreported: latest 3 on 03-27 implies 03-25, but
    latest 2 on the same day implies 03-26, not MLB opening day (R4.2)."""
    drop(zone, "espn/settings/**")
    land_settings(zone, latest=2, final=180, fetched_at="20260327T170000Z")
    land_settings(zone, latest=3, final=180, fetched_at=RUN)
    errors = details(audit(zone), Severity.ERROR)
    assert "20260327T170000Z -> 2026-03-26" in errors
    assert "20260327T160000Z" not in errors
    assert "the schedule gives 2026-03-25" in errors


def test_in_progress_captures_that_all_imply_opening_day_are_information(zone):
    """Catches a missing all-clear: the count of in-progress captures that agree (R4.5)."""
    drop(zone, "espn/settings/**")
    land_settings(zone, latest=3, final=180, fetched_at=RUN)
    land_settings(zone, latest=4, final=180, fetched_at="20260328T160000Z")
    findings = audit(zone)
    assert "period 1" not in details(findings, Severity.ERROR)
    assert (
        "2 in-progress settings capture(s) imply period 1 = 2026-03-25, as ESPN's schedule gives"
    ) in details(findings, Severity.INFO)


def test_period_one_per_the_schedule_must_be_mlb_opening_day(zone):
    """Catches the two sources disagreeing unreported (R5.3). Settings agree with ESPN's
    schedule here, so the only error is the schedule against MLB."""
    drop(zone, "espn/settings/**")
    land_settings(zone, latest=3, final=180)
    land_schedule(zone, [schedule_game(1, "2026-03-26")])
    errors = details(audit(zone), Severity.ERROR)
    assert "period 1 = 2026-03-25 per ESPN's schedule, but MLB opening day is 2026-03-26" in errors
    assert "imply a period 1 other than" not in errors


def test_in_progress_captures_are_compared_with_the_schedule_not_with_mlb(zone):
    """Catches the comparison still using MLB opening day (R5.2): the capture implies
    03-25, MLB says 03-26, ESPN's schedule says 03-25, so no capture is named."""
    drop(zone, "espn/settings/**")
    land_settings(zone, latest=3, final=180)
    land_schedule(zone, [schedule_game(1, "2026-03-26")])
    assert "imply a period 1 other than" not in details(audit(zone), Severity.ERROR)


def test_no_mlb_schedule_is_a_warning_in_the_espn_section_and_the_mlb_error_stays(zone):
    """Catches the old ESPN error (ADR 0023: MLB is a witness, not the rule), a lost
    warning that nothing confirms period 1, and an MLB error that went missing (R5.3, R5.5)."""
    drop(zone, "mlb/schedule/**")
    land_settings(zone, latest=3, final=180, fetched_at="20260328T160000Z")
    findings = audit(zone)
    assert "cannot be dated" not in details(findings, Severity.ERROR)
    espn_warnings = [f.detail for f in findings if f.check == "espn" and f.severity == "WARN"]
    assert any("no MLB schedule to confirm period 1" in w for w in espn_warnings)
    assert any(
        f.check == "mlb" and f.detail == "no committed schedule capture" and f.severity == "ERROR"
        for f in findings
    )
    # The capture is still named, with its games.
    assert "(20260320T120000Z, 1 games)" in details(findings, Severity.INFO)


def test_no_pro_schedule_capture_means_periods_cannot_be_dated(zone):
    """Catches an undated season passing (R5.1), and any date comparison made without a
    date: an in-progress capture that would be off must not be named, and everything else
    in the league check still runs."""
    drop(zone, "espn/pro_schedule/**")
    land_settings(zone, latest=2, final=180, fetched_at="20260327T170000Z")
    findings = audit(zone)
    errors = details(findings, Severity.ERROR)
    assert "no committed pro schedule capture, so scoring periods cannot be dated" in errors
    assert "imply a period 1" not in errors
    assert "per ESPN's schedule" not in details(findings, Severity.INFO)
    assert "rosters captured after their period closed" in details(findings, Severity.INFO)


def test_a_pro_schedule_capture_is_not_a_league(zone):
    """Catches a season-level capture (no league_id) being taken for a league with an
    empty id: the error is reported once per real league only."""
    drop(zone, "espn/pro_schedule/**")
    findings = audit(zone)
    subjects = {f.subject for f in findings if "cannot be dated" in f.detail}
    assert subjects == {f"espn {SEASON} league {LEAGUE}"}


def test_the_landing_section_counts_the_pro_schedule(zone):
    """Catches the landing section special-casing endpoints (R5.5)."""
    landing = [f.detail for f in audit(zone) if f.subject == "espn/pro_schedule"]
    assert landing == ["1 committed capture(s)"]


def test_games_implying_two_dates_for_period_one_are_an_error_and_no_date_is_used(zone):
    """Catches a schedule that disagrees with itself being resolved silently (R5.4): the
    error lists each date with its games, and no comparison is made with either."""
    land_pro_schedule(
        zone,
        [
            pro_game(401, "2026-03-25T20:00:00", 1),
            pro_game(402, "2026-03-25T23:00:00", 1),
            pro_game(403, "2026-03-27T20:00:00", 1),
        ],
        fetched_at="20260321T120000Z",
    )
    drop(zone, "espn/settings/**")
    land_settings(zone, latest=2, final=180, fetched_at="20260327T170000Z")
    findings = audit(zone)
    errors = details(findings, Severity.ERROR)
    assert (
        "pro schedule 20260321T120000Z: games imply different dates for period 1: "
        "2026-03-25 (2 game(s)), 2026-03-27 (1 game(s))"
    ) in errors
    assert "imply a period 1 other than" not in errors
    assert "per ESPN's schedule, but MLB" not in errors
    assert "per ESPN's schedule" not in details(findings, Severity.INFO)


def test_a_game_listed_under_both_teams_counts_once(zone):
    """Catches games counted per team: the count in the all-clear is distinct games."""
    land_pro_schedule(
        zone,
        [pro_game(401, "2026-03-25T20:00:00", 1), pro_game(402, "2026-03-26T20:00:00", 2)],
        fetched_at="20260321T120000Z",
    )
    assert "(20260321T120000Z, 2 games)" in details(audit(zone), Severity.INFO)


@pytest.mark.parametrize(
    "payload",
    [
        {"settings": {"proTeams": []}},
        {"settings": {"proTeams": [{"id": 1}]}},
        {"settings": {"proTeams": [{"id": 1, "proGamesByScoringPeriod": {"1": []}}]}},
    ],
)
def test_a_pro_schedule_with_no_games_dates_nothing(zone, payload):
    """Catches an empty schedule (empty proTeams, a team with no games) being taken for a
    date or silently ignored (R5.4, R7.4)."""
    land_pro_schedule(zone, [], fetched_at="20260321T120000Z", payload=payload)
    findings = audit(zone)
    assert "pro schedule 20260321T120000Z dates nothing" in details(findings, Severity.ERROR)
    assert "per ESPN's schedule" not in details(findings, Severity.INFO)


def test_games_without_a_usable_date_or_period_date_nothing(zone):
    """Catches games with a missing, boolean or text date or period being used (R5.4)."""
    games = [
        {"id": 1, "scoringPeriodId": 1},
        {"id": 2, "date": epoch_ms("2026-03-25T20:00:00")},
        {"id": 3, "date": True, "scoringPeriodId": 1},
        {"id": 4, "date": epoch_ms("2026-03-25T20:00:00"), "scoringPeriodId": True},
        {"id": 5, "date": "2026-03-25", "scoringPeriodId": 1},
        {"id": 6, "date": epoch_ms("2026-03-25T20:00:00"), "scoringPeriodId": "1"},
    ]
    payload = {"settings": {"proTeams": [{"id": 1, "proGamesByScoringPeriod": {"1": games}}]}}
    land_pro_schedule(zone, [], fetched_at="20260321T120000Z", payload=payload)
    assert "pro schedule 20260321T120000Z dates nothing" in details(audit(zone), Severity.ERROR)


def test_a_game_after_midnight_utc_counts_on_the_previous_eastern_date(zone):
    """Catches a UTC date used for the fantasy day: 02:05 UTC on the 26th is the 25th in
    New York, so period 1 is the 25th, not the 26th."""
    land_pro_schedule(
        zone, [pro_game(401, "2026-03-26T02:05:00", 1)], fetched_at="20260321T120000Z"
    )
    findings = audit(zone)
    assert problems(findings) == []
    assert "period 1 = 2026-03-25 per ESPN's schedule" in details(findings, Severity.INFO)


def test_a_later_period_dates_period_one_by_subtracting_the_days(zone):
    """Catches the period number being ignored: period 3 on 03-27 is period 1 on 03-25."""
    land_pro_schedule(
        zone, [pro_game(401, "2026-03-27T20:00:00", 3)], fetched_at="20260321T120000Z"
    )
    assert problems(audit(zone)) == []


def test_the_newest_pro_schedule_capture_is_the_one_used(zone):
    """Catches the first or an arbitrary capture being read: the older one is wrong, the
    newer right, and the audit is clean; with the stamps swapped it is not."""
    land_pro_schedule(
        zone, [pro_game(401, "2026-03-30T20:00:00", 1)], fetched_at="20260310T120000Z"
    )
    findings = audit(zone)
    assert problems(findings) == []
    assert "(20260320T120000Z, 1 games)" in details(findings, Severity.INFO)
    land_pro_schedule(
        zone, [pro_game(401, "2026-03-30T20:00:00", 1)], fetched_at="20260322T120000Z"
    )
    assert "period 1 = 2026-03-30 per ESPN's schedule, but MLB opening day is 2026-03-25" in (
        details(audit(zone), Severity.ERROR)
    )


@pytest.mark.parametrize(
    "payload",
    [
        [],
        "text",
        {},
        {"settings": []},
        {"settings": {"proTeams": {}}},
        {"settings": {"proTeams": ["x", None, 3]}},
        {"settings": {"proTeams": [{"id": 1, "proGamesByScoringPeriod": []}]}},
        {"settings": {"proTeams": [{"id": 1, "proGamesByScoringPeriod": {"1": "x"}}]}},
        {"settings": {"proTeams": [{"id": 1, "proGamesByScoringPeriod": {"1": [1, None, "x"]}}]}},
    ],
)
def test_malformed_pro_schedule_shapes_do_not_crash_the_audit(zone, payload):
    """Catches an unguarded access in the schedule reader: each shape is skipped, and the
    capture then dates nothing."""
    land_pro_schedule(zone, [], fetched_at="20260321T120000Z", payload=payload)
    findings = audit(zone)
    assert "pro schedule 20260321T120000Z dates nothing" in details(findings, Severity.ERROR)


def test_opening_day_comes_from_a_schedule_with_no_game_played_yet(zone):
    """Catches opening day taken over played games only: in March 2027 nothing is played
    yet, but the audit must still date period 1 (R4.7)."""
    drop(zone, "mlb/boxscore/**")
    drop(zone, "espn/settings/**")
    land_schedule(
        zone,
        [
            schedule_game(1, "2026-03-26", detailed="Scheduled"),
            schedule_game(2, "2026-03-25", detailed="Scheduled"),
        ],
    )
    land_settings(zone, latest=3, final=180)
    findings = audit(zone)
    assert "period 1" not in details(findings, Severity.ERROR)
    assert "cannot be dated" not in details(findings, Severity.ERROR)
    assert "imply period 1 = 2026-03-25" in details(findings, Severity.INFO)


@pytest.mark.parametrize(
    "status",
    [
        {"finalScoringPeriod": 180},
        {"latestScoringPeriod": 3},
        {"latestScoringPeriod": "3", "finalScoringPeriod": 180},
        {"latestScoringPeriod": 3, "finalScoringPeriod": None},
    ],
)
def test_a_status_without_usable_counters_is_a_warning_and_in_neither_group(zone, status):
    """Catches a malformed status being counted as in progress or past the final period,
    or crashing the audit (R4.8)."""
    land_status(zone, status, "20260326T160000Z")
    findings = audit(zone)
    assert "20260326T160000Z" in details(findings, Severity.WARN)
    assert "unusable" in details(findings, Severity.WARN)
    info = details(findings, Severity.INFO)
    assert "1 settings capture(s) taken after the final period" in info, "only the clean world's"
    assert "in-progress settings capture(s)" not in info
    assert "20260326T160000Z" not in details(findings, Severity.ERROR)


def test_a_scoring_period_without_a_roster_is_an_error(zone):
    drop(zone, "espn/roster/**/scoring_period=2")
    assert "1 scoring period(s) with no roster; e.g. 2" in details(audit(zone), Severity.ERROR)


def test_a_roster_captured_while_its_period_was_current_is_unproven(zone):
    """Period 2 was the latest period in the earlier run, so its lineup could still change."""
    early = "20260326T160000Z"
    land_settings(zone, latest=2, fetched_at=early)
    drop(zone, "espn/roster/**/scoring_period=2")
    land_roster(zone, 2, fetched_at=early)
    assert "1 roster(s) with no capture shown final" in details(audit(zone), Severity.WARN)


def test_a_roster_with_no_same_run_settings_is_unproven(zone):
    land_roster(zone, 2, fetched_at="20260401T160000Z")
    drop(zone, "espn/roster/**/scoring_period=2", RUN)
    assert "1 roster(s) with no capture shown final" in details(audit(zone), Severity.WARN)


def status_of(latest, final=2):
    return {"latest_scoring_period": latest, "final_scoring_period": final}


def test_a_roster_closed_by_its_own_status_needs_no_settings_from_its_run(zone):
    """Catches the audit still judging by same-run settings, not the fetch logic's rule (R4.2)."""
    drop(zone, "espn/roster/**/scoring_period=2", RUN)
    land_roster(zone, 2, fetched_at="20260401T160000Z", source_status=status_of(3))
    findings = audit(zone)
    assert "shown final" not in details(findings, Severity.WARN)
    assert "2 of 2 rosters captured after their period closed" in details(findings, Severity.INFO)


def test_closed_periods_inside_the_recheck_window_are_reported_as_information(zone):
    """Catches the re-check window invisible in the audit (R6.3)."""
    findings = audit(zone)
    assert (
        "2 closed roster period(s) inside the 7-period re-check window; "
        "the next run fetches them again; e.g. 1, 2"
    ) in details(findings, Severity.INFO)
    assert "re-check window" not in details(findings, Severity.WARN)


def test_no_recheck_line_when_every_closed_period_is_settled(zone):
    """Catches a re-check line emitted for zero periods (R6.3)."""
    for period in (1, 2):
        drop(zone, f"espn/roster/**/scoring_period={period}")
        land_roster(zone, period, source_status=status_of(period + 8))
    assert "re-check window" not in details(audit(zone), Severity.INFO)


def a_season_whose_counter_stopped(tmp_path, *, last_seen, final_twice=False):
    """The 2022 shape: final 182, the counter resting at 183, rosters landed by runs a day apart.

    Periods 1-175 are settled by one capture. Periods 176-181 were captured on the first
    day the counter read 183 and again `last_seen` days later; period 182 only on the later
    day, unless `final_twice`.
    """
    zone = LandingZone(root=tmp_path / "raw")
    first, later = "20221004T100000Z", f"202210{4 + last_seen:02d}T100000Z"
    land_settings(zone, latest=183, final=182, fetched_at=later)
    for period in range(1, 176):
        land_roster(zone, period, fetched_at=first, source_status=status_of(183, 182))
    for period in range(176, 182):
        land_roster(zone, period, fetched_at=first, source_status=status_of(183, 182))
        land_roster(zone, period, fetched_at=later, source_status=status_of(183, 182))
    if final_twice:
        land_roster(zone, 182, fetched_at=first, source_status=status_of(183, 182))
    land_roster(zone, 182, fetched_at=later, source_status=status_of(183, 182))
    _, captures = check_landing(zone)
    return details(check_espn(captures, season=SEASON, opening_day=None), Severity.INFO)


def test_the_recheck_line_says_which_periods_wait_on_the_calendar_and_for_what_counter(tmp_path):
    """Catches a re-check line that cannot say why a period is still fetched (R2.2).

    Three days after the counter first read 183 the extended counter is 186: 176-178 are
    settled, 179-181 wait on the calendar, and 182, seen on one day only, is listed but not
    counted among them.
    """
    info = a_season_whose_counter_stopped(tmp_path, last_seen=3)
    assert (
        "4 closed roster period(s) inside the 7-period re-check window; "
        "the next run fetches them again; e.g. 179, 180, 181 and 1 more; "
        "3 of them wait on the calendar: ESPN's counter has read 183 "
        "across captures a day or more apart"
    ) in info


def test_no_recheck_line_once_the_calendar_has_settled_the_last_periods(tmp_path):
    """Catches a re-check line outliving the week the calendar was waited for (R2.3)."""
    info = a_season_whose_counter_stopped(tmp_path, last_seen=7, final_twice=True)
    assert "re-check window" not in info


def test_a_season_with_only_ordinary_rechecks_keeps_todays_line_exactly(tmp_path):
    """Catches the new clause leaking into a season whose counter kept moving (R2.2)."""
    zone = LandingZone(root=tmp_path / "raw")
    land_settings(zone, latest=186, final=180)
    land_settings(zone, latest=188, final=180, fetched_at="20260928T160000Z")
    for period in range(1, 181):
        land_roster(zone, period)
    _, captures = check_landing(zone)
    info = [f.detail for f in check_espn(captures, season=SEASON, opening_day=None)]
    assert (
        "2 closed roster period(s) inside the 7-period re-check window; "
        "the next run fetches them again; e.g. 179, 180"
    ) in info


def test_a_finished_season_warns_of_a_roster_never_captured_after_the_final_period(zone):
    """Catches a finished season left without its closing refresh unnoticed (R6.4)."""
    # Period 1 is closed by a capture that records latest 2, which is not past the final period 2.
    drop(zone, "espn/roster/**/scoring_period=1")
    land_roster(zone, 1, fetched_at="20260401T160000Z", source_status=status_of(2))
    findings = audit(zone)
    assert (
        "1 scoring period(s) with no roster captured after the final scoring period: 1; "
        "run `front-office backfill espn --season 2026 --refresh` to close the season"
    ) in details(findings, Severity.WARN)


def test_the_season_close_warning_names_every_period_including_one_with_no_roster(zone):
    """Catches periods left out of the closing refresh: sampled away, or missing (R6.4)."""
    land_settings(zone, latest=9, final=6, fetched_at="20260501T160000Z")
    for period in (3, 4, 6):
        land_roster(zone, period, fetched_at="20260405T160000Z", source_status=status_of(6))
    # 1 and 2 are legacy fixtures judged by settings at latest 2; 5 has no roster at all.
    assert (
        "6 scoring period(s) with no roster captured after the final scoring period: 1-6; "
    ) in details(audit(zone), Severity.WARN)


def test_ranges_fold_consecutive_periods_and_list_every_one():
    """Catches a period dropped from, or sampled out of, a listed range."""
    assert _ranges([7, 1, 2, 3, 9, 10]) == "1-3, 7, 9-10"
    assert _ranges([]) == ""


def test_a_season_in_progress_has_no_season_close_warning(zone):
    """Catches the season-close warning firing before the season is over (R6.4)."""
    land_settings(zone, latest=2, final=5, fetched_at="20260328T160000Z")
    assert "captured after the final scoring period:" not in details(audit(zone), Severity.WARN)


def test_a_2026_shaped_season_has_no_season_close_warning_and_two_periods_to_recheck(tmp_path):
    """Catches noise on the clean real season: 180 legacy rosters, evidence 186, final 180."""
    zone = LandingZone(root=tmp_path / "raw")
    land_settings(zone, latest=186, final=180)
    land_settings(zone, latest=188, final=180, fetched_at="20260928T160000Z")
    for period in range(1, 181):
        land_roster(zone, period)
    _, captures = check_landing(zone)
    findings = check_espn(captures, season=SEASON, opening_day=None)
    warnings = details(findings, Severity.WARN)
    assert "captured after the final scoring period:" not in warnings
    assert "shown final" not in warnings
    info = details(findings, Severity.INFO)
    assert "180 of 180 rosters captured after their period closed" in info
    assert "2 closed roster period(s) inside the 7-period re-check window" in info
    assert "e.g. 179, 180" in info


def test_league_snapshots_must_postdate_the_final_period(zone):
    late = "20260328T160000Z"
    land_settings(zone, latest=4, fetched_at=late)
    warnings = details(audit(zone), Severity.WARN)
    assert f"newest teams capture ({RUN}) is not shown to postdate" not in warnings
    # Settings moved on to a later run; teams did not, but RUN was already past period 2.
    land(zone, "espn", "teams", {"season": SEASON, "league_id": LEAGUE}, {}, fetched_at=late)
    assert "teams" not in details(audit(zone), Severity.WARN)


def test_league_snapshots_taken_before_the_season_ended_are_flagged(zone):
    early = "20260326T160000Z"
    land_settings(zone, latest=2, fetched_at=early)
    land(zone, "espn", "teams", {"season": SEASON, "league_id": LEAGUE}, {}, fetched_at=early)
    drop(zone, "espn/teams/**", RUN)
    assert f"newest teams capture ({early})" in details(audit(zone), Severity.WARN)


def clear_transactions(zone):
    drop(zone, "espn/transactions/**")


def test_a_topic_short_of_its_total_is_an_error(zone):
    clear_transactions(zone)
    land_transactions(zone, [topic(1, total=2)])
    assert "1 topic(s) do not hold exactly totalMessageCount messages" in details(
        audit(zone), Severity.ERROR
    )


def test_a_full_last_page_is_an_error(zone):
    clear_transactions(zone)
    land_transactions(zone, [topic(1, topic_id="a"), topic(1, topic_id="b")], limit=2)
    assert "the last page is full (2 topics)" in details(audit(zone), Severity.ERROR)


def test_a_topic_with_no_count_is_an_error(zone):
    clear_transactions(zone)
    land_transactions(zone, [{"id": "t", "messages": [{}]}])
    assert "1 topic(s) do not hold exactly totalMessageCount messages" in details(
        audit(zone), Severity.ERROR
    )


@pytest.mark.parametrize("payload", [{}, {"topics": None}, {"topics": [1]}])
def test_a_page_without_a_valid_topics_list_is_an_error(zone, payload):
    """The review's reproduction: a landed `{}` page read as 0 topics and passed as INFO."""
    clear_transactions(zone)
    params = {"view": "kona_league_communication", "limit": 2000, "offset": 0}
    partitions = {"season": SEASON, "league_id": LEAGUE, "offset": 0}
    land(zone, "espn", "transactions", partitions, payload, params=params)
    assert "1 page(s) carry no valid `topics` list" in details(audit(zone), Severity.ERROR)


def test_an_explicitly_empty_log_is_not_an_error(zone):
    clear_transactions(zone)
    land_transactions(zone, [])
    assert "transactions" not in details(audit(zone), Severity.ERROR)


def test_a_missing_middle_page_is_an_error(zone):
    """The review's probe: a full page 0 and a short page at offset 4; offset 2 missing."""
    clear_transactions(zone)
    land_transactions(zone, [topic(1, topic_id="a"), topic(1, topic_id="b")], limit=2)
    land_transactions(zone, [topic(1, topic_id="c")], offset=4, limit=2)
    assert "missing [2]" in details(audit(zone), Severity.ERROR)


def test_a_missing_first_page_is_an_error(zone):
    clear_transactions(zone)
    land_transactions(zone, [topic(1)], offset=2, limit=2)
    assert "missing [0]" in details(audit(zone), Severity.ERROR)


def test_pages_of_one_run_are_judged_together(zone):
    """A topic repeated across pages (activity between requests) is not a problem."""
    clear_transactions(zone)
    land_transactions(zone, [topic(1, topic_id="a"), topic(1, topic_id="b")], limit=2)
    land_transactions(zone, [topic(1, topic_id="b")], offset=2, limit=2)
    findings = audit(zone)
    assert "2 page(s), 2 topic(s) (1 repeated across pages)" in details(findings, Severity.INFO)
    assert problems(findings) == []


def test_a_filtered_legacy_capture_cannot_be_shown_complete(zone):
    clear_transactions(zone)
    land_transactions(zone, [topic(1)], paged=False)
    assert "predates the paged, unfiltered capture" in details(audit(zone), Severity.WARN)


# -- cli -------------------------------------------------------------------------------


def test_cli_exits_nonzero_only_on_errors(zone, tmp_path):
    db = tmp_path / "warehouse.duckdb"
    with duckdb.connect(str(db)) as con:
        load_landing_zone(con, zone)
    args = ["audit", "--season", "2026", "--raw-root", str(zone.root), "--db", str(db)]

    clean = CliRunner().invoke(app, [*args, "--today", "2026-04-12"])
    assert clean.exit_code == 0, clean.output
    assert "0 error(s), 0 warning(s)" in clean.output

    land_schedule(zone, [schedule_game(1, "2026-03-25"), schedule_game(2, "2026-03-26")])
    broken = CliRunner().invoke(app, [*args, "--today", "2026-04-12"])
    assert broken.exit_code == 1
    assert "played game(s) with no boxscore" in broken.output


def test_cli_without_a_warehouse_is_an_error(zone, tmp_path):
    missing = tmp_path / "absent.duckdb"
    result = CliRunner().invoke(
        app, ["audit", "--season", "2026", "--raw-root", str(zone.root), "--db", str(missing)]
    )
    assert result.exit_code == 1
    assert "no warehouse" in result.output
    assert not missing.exists()


def quarantine_warnings(zone):
    return [f for f in check_landing(zone)[0] if f.severity == Severity.WARN]


def test_a_quarantine_holding_only_an_empty_directory_is_a_warning(zone):
    """Catches counting files only: swept empty directories are quarantined items too."""
    zone.quarantine_root.mkdir()
    (zone.quarantine_root / ".gitignore").write_text("*\n")
    (zone.quarantine_root / "20260930T000000Z" / "mlb").mkdir(parents=True)
    (warnings,) = quarantine_warnings(zone)
    assert warnings.subject == "quarantine"
    assert "1 item(s)" in warnings.detail and "20260930T000000Z" in warnings.detail


def test_the_quarantine_counts_files_and_empty_directories(zone):
    """Catches an item count that skips either kind."""
    run = zone.quarantine_root / "20260930T000000Z"
    (run / "mlb").mkdir(parents=True)
    (run / "mlb" / "x.json").write_text("{}")
    (run / "espn").mkdir()
    (warnings,) = quarantine_warnings(zone)
    assert "2 item(s)" in warnings.detail


def test_the_quarantine_counts_anything_that_is_not_a_directory(zone):
    """Catches an item count that only sees regular files.

    A dangling symlink is neither a regular file nor a directory, and a run holding only
    that used to be reported as zero items (#64 review, round 2).
    """
    run = zone.quarantine_root / "20260930T000000Z"
    run.mkdir(parents=True)
    (run / "dangling").symlink_to(run / "nowhere")
    (warnings,) = quarantine_warnings(zone)
    assert "1 item(s)" in warnings.detail


def test_an_empty_run_directory_counts_as_one_item(zone):
    """Catches a run directory that exists but holds nothing passing unnoticed."""
    (zone.quarantine_root / "20260930T000000Z").mkdir(parents=True)
    (warnings,) = quarantine_warnings(zone)
    assert "1 item(s)" in warnings.detail


def test_an_absent_quarantine_or_one_holding_only_its_ignore_file_is_quiet(zone):
    """Catches a warning with nothing to look at."""
    assert quarantine_warnings(zone) == []
    zone.quarantine_root.mkdir()
    (zone.quarantine_root / ".gitignore").write_text("*\n")
    assert quarantine_warnings(zone) == []


def test_a_postponed_opener_is_dated_by_its_makeup_as_the_model_dates_it(zone):
    """Catches the audit taking opening day from a postponed entry's original date.

    stg_mlb__games keeps the played entry of a postponed game, so the model's opening day
    is the makeup's date. An in-progress capture that implies that date must not be an error.
    """
    land_schedule(
        zone,
        [
            schedule_game(1, "2026-03-24", detailed="Postponed"),
            schedule_game(1, "2026-03-25"),
        ],
    )
    drop(zone, "espn/settings/**")
    land_settings(zone, latest=3, final=180)
    findings = audit(zone)
    assert "period 1" not in details(findings, Severity.ERROR)
    assert "imply period 1 = 2026-03-25" in details(findings, Severity.INFO)


def test_a_postponed_opener_not_yet_made_up_is_dated_by_its_scheduled_makeup(zone):
    """Catches the played-entry preference being applied only to games already played."""
    land_schedule(
        zone,
        [
            schedule_game(1, "2026-03-24", detailed="Postponed"),
            schedule_game(1, "2026-03-25", detailed="Scheduled"),
        ],
    )
    drop(zone, "espn/settings/**")
    land_settings(zone, latest=1, final=180, fetched_at="20260325T160000Z")
    findings = audit(zone)
    assert "period 1" not in details(findings, Severity.ERROR)
    assert "imply period 1 = 2026-03-25" in details(findings, Severity.INFO)


@pytest.mark.parametrize(
    "status",
    [
        {"firstScoringPeriod": 1, "latestScoringPeriod": 3, "finalScoringPeriod": None},
        {"firstScoringPeriod": 1, "finalScoringPeriod": 2},
        None,
        "closed",
    ],
)
def test_an_unusable_newest_status_is_reported_and_does_not_crash_the_audit(zone, status):
    """Catches the roster-finality block converting the newest capture's counters blindly.

    The newest capture decides which periods exist. If its counters are unusable the audit
    warns of the capture, says finality is not checked, and does not raise.
    """
    land_status(zone, status, "20260328T160000Z")
    findings = audit(zone)
    assert "20260328T160000Z" in details(findings, Severity.WARN)
    errors = details(findings, Severity.ERROR)
    assert "newest settings capture (20260328T160000Z) has no usable period counters" in errors
    assert "roster finality and league snapshots are not checked" in errors


def test_transactions_are_still_checked_when_the_newest_status_is_unusable(zone):
    """Catches the unusable-status stop also dropping the transaction check, which does not
    depend on the league status."""
    before = [f.detail for f in audit(zone) if "transactions" in f.detail]
    assert before, "the clean world reports its transaction log"
    land_status(zone, {"firstScoringPeriod": 1, "finalScoringPeriod": None}, "20260328T160000Z")
    after = [f.detail for f in audit(zone) if "transactions" in f.detail]
    assert after == before


def test_a_season_with_a_schedule_and_no_player_list_warns(zone):
    """Catches a missing player-list capture going unreported (spec 0060, R5.5)."""
    drop(zone, "mlb/players/**")
    assert "no committed player-list capture" in details(audit(zone), Severity.WARN)


def test_a_season_with_a_player_list_does_not_warn(zone):
    """Catches the warning firing although a player-list capture is committed."""
    assert "player-list" not in details(audit(zone), Severity.WARN)
