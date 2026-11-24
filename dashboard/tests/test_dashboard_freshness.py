"""The stale-extract rule (spec 0232 R6.2): in season only, more than 36 hours."""

import datetime as dt
from zoneinfo import ZoneInfo

from front_office_dashboard.freshness import is_stale

UTC = dt.UTC
NY = ZoneInfo("America/New_York")


def test_37_hours_old_in_may_is_stale() -> None:
    """Catches a stale extract in season shown without its warning."""
    now = dt.datetime(2026, 5, 20, 12, 0, tzinfo=UTC)
    assert is_stale(now - dt.timedelta(hours=37), now)


def test_35_hours_old_in_may_is_not_stale() -> None:
    now = dt.datetime(2026, 5, 20, 12, 0, tzinfo=UTC)
    assert not is_stale(now - dt.timedelta(hours=35), now)


def test_37_hours_old_in_december_is_not_stale() -> None:
    """Catches a warning in the off-season, when no daily run is expected."""
    now = dt.datetime(2026, 12, 20, 12, 0, tzinfo=UTC)
    assert not is_stale(now - dt.timedelta(hours=37), now)


def test_the_season_is_march_to_october_in_new_york() -> None:
    old = dt.timedelta(hours=40)
    for month, stale in [(2, False), (3, True), (10, True), (11, False)]:
        now = dt.datetime(2026, month, 15, 12, 0, tzinfo=NY)
        assert is_stale(now - old, now) is stale, month


def test_the_month_is_new_york_s_not_utc() -> None:
    """Catches the month read in UTC: 23:30 on 31 October in New York is November in UTC."""
    old = dt.timedelta(hours=40)
    now = dt.datetime(2026, 10, 31, 23, 30, tzinfo=NY)
    assert is_stale(now - old, now)
