"""Tests for what the isolation check builds (spec 0057 R5.1-R5.3, ADR 0028).

The dbt builds are exercised by the gate itself. These tests cover the part that decides
what a single build holds, which is where a later season or another league would get in.
"""

from pathlib import Path

import pytest
import yaml

import check_tenant_isolation as iso

MULTI = Path(__file__).resolve().parents[2] / "fixtures/landing_multi"


def paths(root: Path) -> set[str]:
    return {str(p.relative_to(root)) for p in root.rglob("*")}


@pytest.mark.parametrize(
    ("season", "available", "expected"),
    [
        (2027, [2025, 2026, 2027], [2025, 2026, 2027]),
        (2026, [2025, 2026, 2027], [2025, 2026]),
        (2026, [2026, 2027], [2026]),
        (2025, [2025, 2026, 2027], [2025]),
    ],
)
def test_a_single_build_takes_the_season_and_every_earlier_one(season, available, expected):
    """Catches a later season being copied, or an earlier one being left out."""
    assert iso.seasons_to_copy(season, available) == expected


def test_the_seasons_a_league_has_come_from_the_tree():
    """Catches 222222 being credited with 2025, which only 111111 has."""
    assert iso.league_seasons(MULTI, "111111") == [2025, 2026, 2027]
    assert iso.league_seasons(MULTI, "222222") == [2026, 2027]


def test_a_folder_that_is_not_a_capture_is_not_a_season_the_league_has(tmp_path):
    """Catches a season read from a directory name: an unfinished league folder for 2024
    holds no capture, so the league does not have that season (#90 review, F1)."""
    (tmp_path / "espn/settings/season=2024/league_id=111111/fetched_at=20240401T000000Z").mkdir(
        parents=True
    )
    assert iso.league_seasons(tmp_path, "111111") == []


def test_copy_single_holds_the_league_up_to_the_season_and_nothing_else(tmp_path):
    """Catches another league, a later season, or a missing MLB or pro-schedule folder in a
    single build of (111111, 2026)."""
    iso.copy_single("111111", 2026, tmp_path)
    found = paths(tmp_path)

    assert not any("league_id=222222" in p for p in found)
    assert not any("season=2027" in p for p in found)

    for season in (2025, 2026):
        assert f"espn/matchups/season={season}/league_id=111111" in found
        assert f"espn/settings/season={season}/league_id=111111" in found
        # Season-level captures have no league_id level and come whole.
        assert any(p.startswith(f"espn/pro_schedule/season={season}/fetched_at=") for p in found), (
            season
        )
        assert any(p.startswith(f"mlb/schedule/season={season}/") for p in found), season
    assert any(p.startswith("mlb/boxscore/season=2026/") for p in found)
    assert any(p.startswith("idmap/player_id_map/") for p in found)

    # Everything copied is a copy of the multi tree, nothing is invented.
    assert found <= paths(MULTI)


def test_copy_single_for_a_league_without_history_copies_only_its_season(tmp_path):
    """Catches the fallback league-season (222222, 2026) being given 111111's 2025."""
    iso.copy_single("222222", 2026, tmp_path)
    found = paths(tmp_path)

    assert "espn/matchups/season=2026/league_id=222222" in found
    assert not any("season=2025" in p and "pro_schedule" not in p for p in found)
    assert not any("league_id=111111" in p for p in found)
    assert not any("season=2027" in p for p in found)


def test_every_build_sets_the_scale_threshold_to_two_and_anonymizes():
    """Catches a build of the check run at the default threshold of 100, where nothing
    blends and the check would say nothing about the new dependency."""
    assert iso.DBT_VARS[:2] == ["--target", "ci"]
    assert iso.DBT_VARS[2] == "--vars"
    assert yaml.safe_load(iso.DBT_VARS[3]) == {
        "anonymize": True,
        "fantasy_scale_prior_matchups": 2,
    }
