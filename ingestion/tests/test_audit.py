"""Tests for the landing-zone audit: the gate before landed data is trusted as evidence.

Each test builds a small world that audits clean, breaks one thing, and checks that the
audit names it. The clean world: one MLB game on opening day (2026-03-25), boxscore
captured well after its settle window; one ESPN league whose two scoring periods closed
before the run that captured them.
"""

import datetime as dt
import json
import shutil

import duckdb
import pytest
from typer.testing import CliRunner

from front_office.audit import Severity, check_espn, check_landing, eastern_date, run_audit
from front_office.cli import app
from front_office.landing import LandingZone
from front_office.load import load_landing_zone

SEASON = 2026
LEAGUE = "1"
RUN = "20260327T160000Z"  # noon Eastern, 2026-03-27: period 3 is current
TODAY = dt.date(2026, 5, 1)


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
    land_settings(zone, latest=3)
    for period in (1, 2):
        land_roster(zone, period)
    for endpoint in ("teams", "matchups"):
        land(zone, "espn", endpoint, {"season": SEASON, "league_id": LEAGUE}, {})
    land_transactions(zone, [topic(1)])
    return zone


def audit(zone, *, load=True, today=TODAY):
    con = duckdb.connect()
    if load:
        load_landing_zone(con, zone)
    return run_audit(zone, con, season=SEASON, today=today)


def problems(findings):
    return [(f.severity, f.check, f.detail) for f in findings if f.severity != Severity.INFO]


def details(findings, severity):
    return " | ".join(f.detail for f in findings if f.severity == severity)


def test_the_clean_world_audits_clean(zone):
    findings = audit(zone)
    assert problems(findings) == []
    info = details(findings, Severity.INFO)
    assert "all 8 committed capture(s) loaded" in info
    assert "period 1 = 2026-03-25" in info
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
    assert "8 capture(s) checksum-verified, 0 with no recorded checksum" in info


def test_a_capture_with_no_recorded_checksum_is_counted_not_failed(zone):
    directory = captures_of(zone, "mlb/boxscore/**")[0]
    meta_path = directory / "meta.json"
    meta = json.loads(meta_path.read_text())
    meta.pop("payload_sha256")
    meta.pop("payload_bytes")
    meta_path.write_text(json.dumps(meta))
    findings, _ = check_landing(zone)
    assert problems(findings) == []
    assert "7 capture(s) checksum-verified, 1 with no recorded checksum" in details(
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
    findings = run_audit(zone, con, season=SEASON, today=TODAY)
    assert "1 committed capture(s) not in raw.api_responses" in details(findings, Severity.ERROR)


def test_a_warehouse_without_the_raw_table_is_an_error(zone):
    assert "table missing" in details(audit(zone, load=False), Severity.ERROR)


def test_captures_that_share_a_raw_key_are_an_error(zone):
    """Two leagues, same URL and parameters, same second: the loader now refuses to load
    them, so the audit sees them against a table loaded before the second one landed."""
    con = duckdb.connect()
    load_landing_zone(con, zone)
    land_settings(zone, latest=3, league="2")
    findings = run_audit(zone, con, season=SEASON, today=TODAY)
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
    findings = run_audit(zone, con, season=SEASON, today=TODAY)
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
    findings = run_audit(zone, con, season=SEASON, today=TODAY)
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


@pytest.mark.parametrize(
    ("captured", "today", "expected"),
    [
        # Day 7 is the window's last day: a capture then may predate a correction.
        ("20260401T160000Z", dt.date(2026, 4, 2), "captured only inside their settle window"),
        ("20260402T160000Z", dt.date(2026, 4, 3), None),
        ("20260326T160000Z", dt.date(2026, 3, 30), "1 game(s) still in settle window"),
    ],
)
def test_settle_evidence_needs_a_capture_after_the_window(zone, captured, today, expected):
    drop(zone, "mlb/boxscore/**")
    land_boxscore(zone, 1, captured)
    findings = audit(zone, today=today)
    reported = details(findings, Severity.WARN) + details(findings, Severity.INFO)
    if expected is None:
        assert "settle window" not in reported
    else:
        assert expected in reported


def test_a_resumed_game_settles_from_its_resume_date(zone):
    """Captured eight days after the official date, but only seven after resumption."""
    land_schedule(zone, [schedule_game(1, "2026-03-25", resumeGameDate="2026-03-26")])
    drop(zone, "mlb/boxscore/**")
    land_boxscore(zone, 1, "20260402T160000Z")
    findings = audit(zone)
    assert "captured only inside their settle window" in details(findings, Severity.WARN)
    assert "1 resumed game(s)" in details(findings, Severity.INFO)


# -- espn ------------------------------------------------------------------------------


def test_settings_snapshots_that_disagree_on_period_one_are_an_error(zone):
    """A later snapshot whose latest period stopped advancing shifts the whole calendar."""
    land_settings(zone, latest=3, fetched_at="20260329T160000Z")
    assert "imply different dates for period 1" in details(audit(zone), Severity.ERROR)


def test_period_one_must_be_mlb_opening_day(zone):
    land_schedule(zone, [schedule_game(1, "2026-03-26")])
    errors = details(audit(zone), Severity.ERROR)
    assert "period 1 = 2026-03-25 per settings, but MLB opening day is 2026-03-26" in errors


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


def test_a_finished_season_warns_of_a_roster_never_captured_after_the_final_period(zone):
    """Catches a finished season left without its closing refresh unnoticed (R6.4)."""
    # Period 1 is closed by a capture that records latest 2, which is not past the final period 2.
    drop(zone, "espn/roster/**/scoring_period=1")
    land_roster(zone, 1, fetched_at="20260401T160000Z", source_status=status_of(2))
    findings = audit(zone)
    assert (
        "1 roster(s) never captured after the final scoring period; "
        "run backfill-espn --refresh to close the season; e.g. 1"
    ) in details(findings, Severity.WARN)


def test_a_roster_with_no_capture_is_not_repeated_in_the_season_close_warning(zone):
    """Catches a missing roster reported twice (R6.4)."""
    drop(zone, "espn/roster/**/scoring_period=2")
    assert "never captured after the final" not in details(audit(zone), Severity.WARN)


def test_a_season_in_progress_has_no_season_close_warning(zone):
    """Catches the season-close warning firing before the season is over (R6.4)."""
    land_settings(zone, latest=2, final=5, fetched_at="20260328T160000Z")
    assert "never captured after the final" not in details(audit(zone), Severity.WARN)


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
    assert "never captured after the final" not in warnings
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

    clean = CliRunner().invoke(app, [*args, "--today", "2026-05-01"])
    assert clean.exit_code == 0, clean.output
    assert "0 error(s), 0 warning(s)" in clean.output

    land_schedule(zone, [schedule_game(1, "2026-03-25"), schedule_game(2, "2026-03-26")])
    broken = CliRunner().invoke(app, [*args, "--today", "2026-05-01"])
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
