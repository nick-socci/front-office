"""R1.1, R1.2, R1.6, R1.7 (spec 0218): when the daily run and the id map's run start.

The ticks are computed with Dagster's own cron iterator (the one the daemon uses), in the
schedule's time zone, so a test of "06:00 holds across the clocks changing" runs the same
arithmetic production does. Nothing is executed.
"""

import datetime
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from dagster import AssetKey, DefaultScheduleStatus, Definitions, ScheduleDefinition
from dagster._utils.schedules import cron_string_iterator

import front_office_pipeline
from front_office_pipeline import dbt_assets, schedules

NEW_YORK = ZoneInfo("America/New_York")


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("FO_WAREHOUSE", "FO_BQ_PROJECT", "FO_DAILY_CRON"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def dev_manifest(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    manifest = dbt_assets.load_manifest("dev")
    monkeypatch.setattr(dbt_assets, "load_manifest", lambda target: manifest)
    return manifest


def schedules_of(defs: Definitions) -> dict[str, ScheduleDefinition]:
    found: dict[str, ScheduleDefinition] = {}
    for schedule in defs.schedules or []:
        assert isinstance(schedule, ScheduleDefinition)
        found[schedule.name] = schedule
    return found


def ticks(cron: str, start: datetime.datetime, end: datetime.datetime) -> list[datetime.datetime]:
    """The ticks of `cron` in New York from `start` up to, not including, `end`."""
    found: list[datetime.datetime] = []
    for tick in cron_string_iterator(start.timestamp(), cron, "America/New_York"):
        if tick >= end:
            return found
        found.append(tick.astimezone(NEW_YORK))
    raise AssertionError("the iterator ended")


def at(year: int, month: int, day: int, hour: int = 0) -> datetime.datetime:
    return datetime.datetime(year, month, day, hour, tzinfo=NEW_YORK)


def test_the_daily_cron_fires_at_six_new_york_time_from_march_first_to_october_31() -> None:
    """R1.1. Catches a month range that misses March 1 or October 31, an hour that drifts
    when the clocks change (a UTC cron would move to 05:00 or 07:00), and a tick in winter."""
    found = ticks(schedules.DAILY_CRON, at(2027, 2, 28), at(2027, 11, 2))
    assert found[0].isoformat() == "2027-03-01T06:00:00-05:00"
    # The clocks went forward on 2027-03-14: the first tick after is still 06:00 local.
    after_change = next(t for t in found if t.date() >= datetime.date(2027, 3, 14))
    assert after_change.isoformat() == "2027-03-14T06:00:00-04:00"
    assert found[-1].isoformat() == "2027-10-31T06:00:00-04:00"
    # Every day, weekends included: 245 days from March 1 to October 31.
    assert len(found) == 245
    assert all(t.hour == 6 and t.minute == 0 for t in found)


def test_the_daily_cron_is_quiet_from_november_to_the_end_of_february() -> None:
    """R1.1. Catches a year-round schedule: ESPN fails every winter day (ADR 0130)."""
    winter = ticks(schedules.DAILY_CRON, at(2027, 11, 1), at(2028, 3, 1))
    assert winter == []


def test_the_id_map_cron_fires_on_mondays_at_five_in_season() -> None:
    """R1.6. Catches a day of week that is not Monday, an hour that is not 05:00, and a
    tick outside the daily window."""
    found = ticks(schedules.IDMAP_CRON, at(2027, 1, 1), at(2028, 1, 1))
    assert found, "no tick in a year"
    assert {t.weekday() for t in found} == {0}
    assert {(t.hour, t.minute) for t in found} == {(5, 0)}
    assert {t.month for t in found} == set(range(3, 11))


def test_both_schedules_start_running_in_new_york_time() -> None:
    """R1.1, R1.6 (C1). Catches a schedule that starts STOPPED: a fresh instance would never
    fire it, and nobody would see why."""
    for schedule in (
        schedules.daily_schedule(schedules.DAILY_CRON),
        schedules.idmap_schedule(schedules.IDMAP_CRON),
    ):
        assert schedule.default_status == DefaultScheduleStatus.RUNNING
        assert schedule.execution_timezone == "America/New_York"


def test_the_builders_take_any_cron() -> None:
    """R1.7. Catches a builder that ignores its argument (a test could not use its own)."""
    assert schedules.daily_schedule("*/5 * * * *").cron_schedule == "*/5 * * * *"
    assert schedules.idmap_schedule("0 0 * * *").cron_schedule == "0 0 * * *"


def test_the_schedules_have_no_partition_set(dev_manifest: dict[str, Any]) -> None:
    """R1.2 (C2). An unpartitioned schedule launches its latest tick only after an outage;
    a partition set would replay up to five. Catches a partitioned job behind a schedule."""
    defs = front_office_pipeline.build_defs()
    for job in ("daily", "idmap"):
        assert defs.resolve_job_def(job).partitions_def is None
    assert {s.job_name for s in schedules_of(defs).values()} == {"daily", "idmap"}


def test_the_daily_cron_is_the_default_when_fo_daily_cron_is_unset_or_empty() -> None:
    """R1.7. Catches an empty variable (a unit file's `FO_DAILY_CRON=`) becoming an
    invalid empty cron."""
    assert schedules.daily_cron(environ={}) == schedules.DAILY_CRON
    assert schedules.daily_cron(environ={"FO_DAILY_CRON": ""}) == schedules.DAILY_CRON


def test_fo_daily_cron_replaces_the_daily_cron_only(
    monkeypatch: pytest.MonkeyPatch, dev_manifest: dict[str, Any]
) -> None:
    """R1.7. Catches an override that does not reach the schedule, or one that moves the id
    map's schedule too."""
    assert schedules.daily_cron(environ={"FO_DAILY_CRON": "*/10 * * * *"}) == "*/10 * * * *"
    monkeypatch.setenv("FO_DAILY_CRON", "*/10 * * * *")
    by_name = schedules_of(front_office_pipeline.build_defs())
    assert by_name["daily_schedule"].cron_schedule == "*/10 * * * *"
    assert by_name["idmap_schedule"].cron_schedule == schedules.IDMAP_CRON


def test_the_definitions_hold_both_schedules_and_their_jobs(
    dev_manifest: dict[str, Any],
) -> None:
    """R1.1, R1.6. Catches a schedule not registered, or aimed at the wrong job."""
    defs = front_office_pipeline.build_defs()
    assert isinstance(defs, Definitions)
    by_name = schedules_of(defs)
    assert set(by_name) == {"daily_schedule", "idmap_schedule"}
    assert by_name["daily_schedule"].job_name == "daily"
    assert by_name["idmap_schedule"].job_name == "idmap"


def keys_of(defs: Definitions, job: str) -> set[str]:
    job_def = defs.resolve_job_def(job)
    return {k.to_user_string() for k in job_def.asset_layer.executable_asset_keys}


def test_idmap_job_selects_only_the_id_map_and_daily_still_leaves_it_out(
    dev_manifest: dict[str, Any],
) -> None:
    """R1.6, R4.2. Catches an `idmap` job that also builds the warehouse, and a `daily` that
    gained the id map."""
    defs = front_office_pipeline.build_defs()
    assert keys_of(defs, "idmap") == {"idmap_capture"}
    daily = keys_of(defs, "daily")
    assert "idmap_capture" not in daily
    assert AssetKey("mlb_captures").to_user_string() in daily
    assert "source_freshness" in daily
    assert defs.resolve_job_def("idmap").executor_def.name == "in_process"


def test_daily_still_leaves_out_source_freshness_on_bigquery(
    monkeypatch: pytest.MonkeyPatch, dev_manifest: dict[str, Any]
) -> None:
    """R3.5 (0217). Catches the new job changing what `daily` selects on BigQuery."""
    monkeypatch.setenv("FO_WAREHOUSE", "bigquery")
    monkeypatch.setenv("FO_BQ_PROJECT", "p")
    daily = keys_of(front_office_pipeline.build_defs(), "daily")
    assert "source_freshness" not in daily
    assert "idmap_capture" not in daily
