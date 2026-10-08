"""Tests for the combined fixture generator (spec 0028, R5.1).

The combined tree is committed, so these tests are what keeps it honest: a hand edit, a
stale tree, or a generator that quietly reads the real season all fail here.
"""

import json
import shutil
from pathlib import Path

import duckdb
import pytest

from front_office.landing import LandingZone
from front_office.load import RawKeyCollision, load_landing_zone
from make_multi_fixtures import RESPELLED_SUFFIX, generate

REPO = Path(__file__).resolve().parents[2]
SINGLE = REPO / "fixtures/landing"
COMMITTED = REPO / "fixtures/landing_multi"
LEAGUE_SEASONS = [("111111", 2026), ("222222", 2026), ("111111", 2027), ("222222", 2027)]


def tree(root: Path) -> dict[str, bytes]:
    return {
        str(p.relative_to(root)): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()
    }


def sidecars(root: Path) -> list[Path]:
    return sorted(root.rglob("meta.json"))


def test_generator_reproduces_the_committed_tree_byte_for_byte(tmp_path):
    """Catches a hand edit of landing_multi, or a generator change with no regeneration."""
    out = tmp_path / "out"
    generate(SINGLE, out)
    assert tree(out) == tree(COMMITTED)


def test_generator_is_idempotent_and_clears_stale_files(tmp_path):
    """Catches a rerun that leaves an old file behind or changes a byte."""
    out = tmp_path / "out"
    generate(SINGLE, out)
    (out / "stale.json").write_text("{}")
    generate(SINGLE, out)
    assert tree(out) == tree(COMMITTED)


def test_generator_reads_only_its_input_root(tmp_path):
    """Catches a read of data/ or anything else outside the committed fixture: the input
    is a lone copy of fixtures/landing, with no data/ beside it."""
    copy = tmp_path / "isolated/landing"
    shutil.copytree(SINGLE, copy)
    out = tmp_path / "out"
    generate(copy, out)
    assert tree(out) == tree(COMMITTED)


def espn_meta(root: Path, league: str, season: int) -> list[dict]:
    return [
        json.loads(p.read_text())
        for p in sidecars(root / "espn")
        if json.loads(p.read_text())["partitions"].get("league_id") == league
        and json.loads(p.read_text())["partitions"]["season"] == season
    ]


def test_four_league_seasons_are_present():
    """Catches a missing tenant."""
    for league, season in LEAGUE_SEASONS:
        endpoints = {m["endpoint"] for m in espn_meta(COMMITTED, league, season)}
        assert endpoints == {"settings", "teams", "roster", "matchups", "transactions"}


def test_leagues_of_a_season_share_every_fetch_stamp():
    """Catches leagues that no longer collide on timestamps, which is the point of them."""
    for season in (2026, 2027):
        stamps = {
            league: {(m["endpoint"], m["fetched_at"]) for m in espn_meta(COMMITTED, league, season)}
            for league in ("111111", "222222")
        }
        assert stamps["111111"] == stamps["222222"]


def test_2027_has_one_roster_period_per_league_and_a_one_period_season():
    """Catches a 2027 as long as 2026: the seasons must have different lengths."""
    for league in ("111111", "222222"):
        rosters = [m for m in espn_meta(COMMITTED, league, 2027) if m["endpoint"] == "roster"]
        assert [m["partitions"]["scoring_period"] for m in rosters] == [1]
        settings = next(
            m for m in espn_meta(COMMITTED, league, 2027) if m["endpoint"] == "settings"
        )
        path = COMMITTED / "espn/settings/season=2027" / f"league_id={league}"
        payload = json.loads(
            (path / f"fetched_at={settings['fetched_at']}" / "payload.json").read_text()
        )
        assert payload["seasonId"] == 2027 and payload["id"] == league
        assert payload["status"]["finalScoringPeriod"] == 1
        assert payload["status"]["latestScoringPeriod"] == 1


def roster_names(league: str, season: int, period: int) -> dict[int, str]:
    folder = COMMITTED / f"espn/roster/season={season}/league_id={league}/scoring_period={period}"
    payload = json.loads(next(folder.glob("*/payload.json")).read_text())
    return {
        e["playerId"]: e["playerPoolEntry"]["player"]["fullName"]
        for t in payload["teams"]
        for e in t["roster"]["entries"]
    }


def test_one_player_is_spelled_differently_in_the_two_2026_leagues():
    """Catches a combined fixture where the conformed dimension has no choice to make."""
    differing = set()
    for period in (1, 2):
        a, b = roster_names("111111", 2026, period), roster_names("222222", 2026, period)
        assert a.keys() == b.keys()
        differing |= {k for k in a if a[k] != b[k]}
        assert all(b[k] == a[k] + RESPELLED_SUFFIX for k in a if a[k] != b[k])
    assert len(differing) == 1


def test_2027_leagues_keep_the_original_spelling():
    """Catches the respelling leaking into 2027."""
    assert roster_names("111111", 2027, 1) == roster_names("222222", 2027, 1)


def test_combined_tree_loads_with_no_collision_and_every_capture():
    """Catches two captures sharing a raw key, and a sidecar that does not load."""
    con = duckdb.connect(":memory:")
    try:
        load_landing_zone(con, LandingZone(COMMITTED))
    except RawKeyCollision as err:  # pragma: no cover - failure path
        pytest.fail(str(err))
    rows = con.execute("select count(*) from raw.api_responses").fetchone()[0]
    assert rows == len(sidecars(COMMITTED))


def test_generator_ignores_a_stray_directory_that_is_not_a_capture(tmp_path):
    """Catches pairing meta.json and payload.json by hand: a directory that merely holds a
    sidecar-shaped file is not a committed capture, so no tenant may be derived from it.
    (The verbatim copy of the base tree still carries the stray files across.)"""
    copy = tmp_path / "landing"
    shutil.copytree(SINGLE, copy)
    source = next(copy.glob("espn/roster/season=2026/league_id=111111/scoring_period=1/*"))
    stray = source.parent / "stray"
    stray.mkdir()
    meta = json.loads((source / "meta.json").read_text())
    meta["partitions"]["scoring_period"] = 99
    meta["fetched_at"] = "20260101T000000Z"
    (stray / "meta.json").write_text(json.dumps(meta))
    (stray / "payload.json").write_bytes((source / "payload.json").read_bytes())

    out = tmp_path / "out"
    generate(copy, out)

    expected = tree(COMMITTED)
    for name in ("meta.json", "payload.json"):
        expected[str((stray / name).relative_to(copy))] = (stray / name).read_bytes()
    assert tree(out) == expected


def pro_schedule(season: int) -> tuple[dict, dict]:
    (capture,) = LandingZone(COMMITTED).committed(
        source="espn", endpoint="pro_schedule", partitions={"season": season}
    )
    return capture.meta, capture.payload


def test_pro_schedule_is_season_level_and_2027_is_one_period_on_the_2027_day():
    """Catches a pro schedule relabelled per league (it has no league), a 2027 schedule
    that still has period 2 or unshifted dates, and one whose period 1 is not the day the
    rest of 2027 calls period 1."""
    from datetime import UTC, datetime
    from zoneinfo import ZoneInfo

    assert not list(COMMITTED.glob("espn/pro_schedule/**/league_id=*"))
    meta_2026, payload_2026 = pro_schedule(2026)
    assert payload_2026 == json.loads(
        (next((SINGLE / "espn/pro_schedule/season=2026").glob("*/payload.json"))).read_text()
    )
    meta, payload = pro_schedule(2027)
    assert meta["partitions"] == {"season": 2027}
    assert meta["url"].endswith("/seasons/2027")
    schedule = json.loads(
        next((COMMITTED / "mlb/schedule/season=2027").rglob("payload.json")).read_text()
    )
    day = schedule["dates"][0]["date"]
    periods = set()
    games = 0
    for team in payload["settings"]["proTeams"]:
        for period, listed in team.get("proGamesByScoringPeriod", {}).items():
            periods.add(period)
            for game in listed:
                games += 1
                local = (
                    datetime.fromtimestamp(game["date"] / 1000, UTC)
                    .astimezone(ZoneInfo("America/New_York"))
                    .date()
                )
                assert local.isoformat() == day
    assert periods == {"1"} and games > 0


def test_2027_roster_lines_are_period_1_games_of_the_2027_pro_schedule():
    """Catches the 2027 roster keeping lines of the 2026 fixture days (period 2, or games
    that are not in the 2027 pro schedule's period 1) after the cut to one period."""
    (roster,) = (
        c
        for c in LandingZone(COMMITTED).committed(source="espn", endpoint="roster")
        if c.meta["partitions"]["season"] == 2027 and c.meta["partitions"]["league_id"] == "111111"
    )
    games = {
        str(game["id"])
        for team in pro_schedule(2027)[1]["settings"]["proTeams"]
        for game in team.get("proGamesByScoringPeriod", {}).get("1", [])
    }
    lines = [
        line
        for team in roster.payload["teams"]
        for entry in team["roster"]["entries"]
        for line in entry["playerPoolEntry"]["player"].get("stats", [])
    ]
    assert lines
    assert {line["scoringPeriodId"] for line in lines} == {1}
    assert {line["externalId"] for line in lines} <= games
