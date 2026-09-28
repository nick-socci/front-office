"""Tests for the landing-zone audit: the gate before landed data is trusted as evidence.

Each test builds a small world that audits clean, breaks one thing, and checks that the
audit names it. The clean world: one MLB game on opening day (2026-03-25), boxscore
captured well after its settle window; one ESPN league whose two scoring periods closed
before the run that captured them.
"""

import datetime as dt

import duckdb
import pytest
from typer.testing import CliRunner

from front_office.audit import Severity, check_landing, eastern_date, run_audit
from front_office.cli import app
from front_office.landing import LandingZone
from front_office.load import load_landing_zone

SEASON = 2026
LEAGUE = "1"
RUN = "20260327T160000Z"  # noon Eastern, 2026-03-27: period 3 is current
TODAY = dt.date(2026, 5, 1)


def land(zone, source, endpoint, partitions, payload, *, fetched_at=RUN, params=None):
    return zone.write(
        source=source,
        endpoint=endpoint,
        partitions=partitions,
        name=f"fetched_at={fetched_at}",
        payload=payload,
        request={"url": f"https://example.test/{endpoint}", "params": params or {}},
        fetched_at=fetched_at,
    )


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
    land(
        zone,
        "mlb",
        "schedule",
        {"season": SEASON, "game_type": "R"},
        {"dates": [{"games": games}]},
        params={"season": SEASON},
    )


def land_boxscore(zone, pk, fetched_at):
    land(
        zone,
        "mlb",
        "boxscore",
        {"season": SEASON, "game_pk": pk},
        {},
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


def land_roster(zone, period, fetched_at=RUN):
    land(
        zone,
        "espn",
        "roster",
        {"season": SEASON, "league_id": LEAGUE, "scoring_period": period},
        {"teams": []},
        fetched_at=fetched_at,
        params={"view": "mRoster", "scoringPeriodId": period},
    )


def land_transactions(zone, topics):
    land(
        zone,
        "espn",
        "transactions",
        {"season": SEASON, "league_id": LEAGUE},
        {"topics": topics},
        params={"view": "kona_league_communication", "limit": 2000},
    )


def topic(messages, total=None):
    return {"id": "t", "messages": [{}] * messages, "totalMessageCount": total or messages}


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
    orphan = zone.root / "espn/roster_matchup/season=2026/fetched_at=20260321T000000Z.json"
    orphan.parent.mkdir(parents=True)
    orphan.write_text("{}")
    findings, _ = check_landing(zone)
    assert "1 payload(s) with no sidecar" in details(findings, Severity.ERROR)


def test_a_sidecar_without_a_payload_is_an_error(zone):
    payload = next(zone.root.glob("mlb/boxscore/**/*Z.json"))
    payload.unlink()
    findings, captures = check_landing(zone)
    assert "1 sidecar(s) whose payload is missing" in details(findings, Severity.ERROR)
    assert all(capture.endpoint != "boxscore" for capture in captures)


def test_a_leftover_temp_file_is_an_error(zone):
    (zone.root / "mlb/boxscore/fetched_at=x.json.tmp-123").write_text("{")
    findings, _ = check_landing(zone)
    assert "1 temporary file(s)" in details(findings, Severity.ERROR)


def test_an_unreadable_payload_is_an_error_and_not_a_capture(zone):
    payload = next(zone.root.glob("mlb/boxscore/**/*Z.json"))
    payload.write_text('{"truncated": ')
    findings, captures = check_landing(zone)
    assert "1 capture(s) whose payload or sidecar is not valid JSON" in details(
        findings, Severity.ERROR
    )
    assert all(capture.endpoint != "boxscore" for capture in captures)


def test_a_sidecar_that_disagrees_with_its_path_is_an_error(zone):
    payload = next(zone.root.glob("mlb/boxscore/**/*Z.json"))
    moved = payload.parent.parent / "game_pk=2" / payload.name
    moved.parent.mkdir()
    payload.rename(moved)
    payload.with_suffix(".meta.json").rename(moved.with_suffix(".meta.json"))
    findings, _ = check_landing(zone)
    assert "sidecar describes mlb/boxscore/season=2026/game_pk=1/" in details(
        findings, Severity.ERROR
    )


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
    """Two leagues, same request parameters, same second: the loader keeps only one."""
    land_settings(zone, latest=3, league="2")
    assert "2 captures share raw key" in details(audit(zone), Severity.ERROR)


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
    next(zone.root.glob("mlb/boxscore/**/*Z.json")).unlink()
    next(zone.root.glob("mlb/boxscore/**/*.meta.json")).unlink()
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
    for path in zone.root.glob("mlb/boxscore/**/*.json"):
        path.unlink()
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
    for path in zone.root.glob("espn/roster/**/scoring_period=2/*"):
        path.unlink()
    assert "1 scoring period(s) with no roster; e.g. 2" in details(audit(zone), Severity.ERROR)


def test_a_roster_captured_while_its_period_was_current_is_unproven(zone):
    """Period 2 was the latest period in the earlier run, so its lineup could still change."""
    early = "20260326T160000Z"
    land_settings(zone, latest=2, fetched_at=early)
    for path in zone.root.glob("espn/roster/**/scoring_period=2/*"):
        path.unlink()
    land_roster(zone, 2, fetched_at=early)
    assert "1 roster(s) with no capture shown final" in details(audit(zone), Severity.WARN)


def test_a_roster_with_no_same_run_settings_is_unproven(zone):
    land_roster(zone, 2, fetched_at="20260401T160000Z")
    for path in zone.root.glob(f"espn/roster/**/scoring_period=2/fetched_at={RUN}*"):
        path.unlink()
    assert "1 roster(s) with no capture shown final" in details(audit(zone), Severity.WARN)


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
    for path in zone.root.glob(f"espn/teams/**/fetched_at={RUN}*"):
        path.unlink()
    assert f"newest teams capture ({early})" in details(audit(zone), Severity.WARN)


@pytest.mark.parametrize(
    ("topics", "expected"),
    [
        ([topic(25)], "hit a request cap"),
        ([topic(1, total=2)], "1 topic(s) returned fewer messages than totalMessageCount"),
    ],
)
def test_a_possibly_incomplete_transaction_log_is_flagged(zone, topics, expected):
    for path in zone.root.glob("espn/transactions/**/*"):
        if path.is_file():
            path.unlink()
    land_transactions(zone, topics)
    assert expected in details(audit(zone), Severity.WARN)


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
