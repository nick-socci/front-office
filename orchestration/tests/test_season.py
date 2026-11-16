"""R3.1 and R3.3: which season a run fetches, and whether matchup days are due.

Catches: a rollover that follows UTC instead of New York; matchup-day requests for a season
still running (future scoring periods); a settings capture of another season or league read
as this one's.
"""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from front_office.landing import LandingZone
from front_office_pipeline import season


def test_current_season_is_the_new_york_year_before_midnight() -> None:
    # 2027-01-01 04:00 UTC is still 2026-12-31 23:00 in New York.
    assert season.current(now=datetime(2027, 1, 1, 4, 0, tzinfo=UTC), environ={}) == 2026


def test_current_season_rolls_over_at_new_york_midnight() -> None:
    # 2027-01-01 10:00 UTC is 05:00 ET.
    assert season.current(now=datetime(2027, 1, 1, 10, 0, tzinfo=UTC), environ={}) == 2027


def test_fo_season_overrides_the_clock() -> None:
    now = datetime(2027, 1, 1, 10, 0, tzinfo=UTC)
    assert season.current(now=now, environ={"FO_SEASON": "2025"}) == 2025


def test_fo_season_that_is_not_a_year_is_refused() -> None:
    with pytest.raises(ValueError, match="FO_SEASON"):
        season.current(environ={"FO_SEASON": "last year"})


def _land_settings(
    root: Path, *, year: int, league: str, stamp: str, latest: int | None, final: int | None
) -> None:
    status: dict[str, int] = {}
    if latest is not None:
        status["latestScoringPeriod"] = latest
    if final is not None:
        status["finalScoringPeriod"] = final
    zone = LandingZone(root)
    zone.write(
        source="espn",
        endpoint="settings",
        partitions={"season": year, "league_id": league},
        name=f"fetched_at={stamp}",
        payload={"status": status},
        request={
            "url": f"https://example.invalid/seasons/{year}/leagues/{league}?view=mStatus",
            "params": {"view": "mStatus"},
        },
        fetched_at=stamp,
    )


def test_over_when_latest_period_passes_the_final_one(tmp_path: Path) -> None:
    _land_settings(tmp_path, year=2026, league="1", stamp="20261110T034033Z", latest=188, final=180)
    assert season.is_over(tmp_path, 2026) is True


def test_not_over_while_latest_is_inside_the_season(tmp_path: Path) -> None:
    _land_settings(tmp_path, year=2026, league="1", stamp="20260601T120000Z", latest=120, final=180)
    assert season.is_over(tmp_path, 2026) is False


def test_not_over_without_a_settings_capture(tmp_path: Path) -> None:
    assert season.is_over(tmp_path, 2026) is False


def test_the_newest_capture_decides(tmp_path: Path) -> None:
    _land_settings(tmp_path, year=2026, league="1", stamp="20260601T120000Z", latest=120, final=180)
    _land_settings(tmp_path, year=2026, league="1", stamp="20261110T034033Z", latest=188, final=180)
    assert season.is_over(tmp_path, 2026) is True


def test_another_season_is_not_this_one(tmp_path: Path) -> None:
    _land_settings(tmp_path, year=2025, league="1", stamp="20261012T013731Z", latest=196, final=188)
    assert season.is_over(tmp_path, 2026) is False


def test_a_status_without_the_two_periods_is_not_over(tmp_path: Path) -> None:
    _land_settings(
        tmp_path, year=2026, league="1", stamp="20260601T120000Z", latest=None, final=180
    )
    assert season.is_over(tmp_path, 2026) is False


def test_two_leagues_in_one_season_are_refused(tmp_path: Path) -> None:
    _land_settings(tmp_path, year=2026, league="1", stamp="20261110T034033Z", latest=188, final=180)
    _land_settings(tmp_path, year=2026, league="2", stamp="20261110T034033Z", latest=120, final=180)
    with pytest.raises(season.AmbiguousLeague):
        season.is_over(tmp_path, 2026)
