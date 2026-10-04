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
    return sorted(root.rglob("*.meta.json"))


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
        if json.loads(p.read_text())["partitions"]["league_id"] == league
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
        payload = json.loads((path / f"fetched_at={settings['fetched_at']}.json").read_text())
        assert payload["seasonId"] == 2027 and payload["id"] == league
        assert payload["status"]["finalScoringPeriod"] == 1
        assert payload["status"]["latestScoringPeriod"] == 1


def roster_names(league: str, season: int, period: int) -> dict[int, str]:
    folder = COMMITTED / f"espn/roster/season={season}/league_id={league}/scoring_period={period}"
    payload = json.loads(next(p for p in folder.glob("*.json") if "meta" not in p.name).read_text())
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
