"""When the daily run and the id map's run start (spec 0218, ADRs 0134 and 0136).

Why a cron with a month range: the pipeline runs only in season (ADR 0130), and ESPN fails
every winter day, so no tick fires from November to the end of February. March 1 to October 31
holds spring training's end, the regular season, the seven-day settle tail and the postseason.
`execution_timezone` makes Dagster evaluate the cron in New York, so 06:00 holds when the clocks
change. Both schedules start `RUNNING` (Dagster's default is `STOPPED`), so a new instance needs
no click.

Neither schedule has a partition set: after an outage an unpartitioned schedule launches its
latest tick only, which is the catch-up wanted. Each builder takes the cron so a test can use any
expression; `FO_DAILY_CRON`, when set and not empty, replaces `DAILY_CRON` for rehearsals only
(R1.7), and the id map's schedule has no override.
"""

from __future__ import annotations

from collections.abc import Mapping

from dagster import DefaultScheduleStatus, ScheduleDefinition

from front_office_pipeline import settings

DAILY_CRON = "0 6 * 3-10 *"
IDMAP_CRON = "0 5 * 3-10 1"
TIMEZONE = "America/New_York"


def daily_cron(*, environ: Mapping[str, str] | None = None) -> str:
    """`FO_DAILY_CRON` when set and not empty, else `DAILY_CRON`."""
    return settings.daily_cron_override(environ=environ) or DAILY_CRON


def daily_schedule(cron: str) -> ScheduleDefinition:
    return ScheduleDefinition(
        name="daily_schedule",
        job_name="daily",
        cron_schedule=cron,
        execution_timezone=TIMEZONE,
        default_status=DefaultScheduleStatus.RUNNING,
    )


def idmap_schedule(cron: str) -> ScheduleDefinition:
    return ScheduleDefinition(
        name="idmap_schedule",
        job_name="idmap",
        cron_schedule=cron,
        execution_timezone=TIMEZONE,
        default_status=DefaultScheduleStatus.RUNNING,
    )
