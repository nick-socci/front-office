"""The run-status sensors that ping healthchecks.io when `daily` or `idmap` ends (spec 0219).

A run-status sensor is a Dagster function the daemon calls when a monitored job's run reaches a
given status. Three of them share one body, `notify`, one each for `SUCCESS`, `FAILURE` and
`CANCELED` (R1.1, R1.3). They start `RUNNING`: Dagster's default is `STOPPED`, which would leave
a freshly deployed code location silent.

Without a ping key, `notify` skips with a reason that says so and sends nothing, so the laptop
and CI load the same definitions and stay silent (R1.4). A key file that cannot be used raises
`alerts.PingKeyUnreadable`: the sensor's tick shows it, and a ping that never arrives becomes
healthchecks.io's own missed-run alert. The log line names the slug and the result, never the
key or the URL (R1.5).
"""

from collections.abc import Callable, Sequence
from typing import Any

from dagster import (
    DagsterRunStatus,
    DefaultSensorStatus,
    RunStatusSensorContext,
    RunStatusSensorDefinition,
    SkipReason,
    run_status_sensor,
)

from front_office_pipeline import alerts

NO_KEY = "no FO_HEALTHCHECKS_PING_KEY_FILE: nothing sent"
SENSORS = {
    "ping_success": DagsterRunStatus.SUCCESS,
    "ping_failure": DagsterRunStatus.FAILURE,
    "ping_canceled": DagsterRunStatus.CANCELED,
}


def notify(
    context: RunStatusSensorContext,
    *,
    send: Callable[[str, str, bool, str], str] = alerts.send,
) -> SkipReason | None:
    """Ping healthchecks.io with the finished run's report; `send` is injectable for tests."""
    key = alerts.ping_key()
    if key is None:
        return SkipReason(NO_KEY)
    result = alerts.outcome(context.instance, context.dagster_run)
    slug = alerts.SLUGS[context.dagster_run.job_name]
    is_failed = alerts.failed(result)
    sent = send(slug, alerts.report(result), is_failed, key)
    context.log.info(f"ping {slug}: {'fail' if is_failed else 'ok'} {sent}")
    return None


def run_sensors(jobs: Sequence[Any]) -> list[RunStatusSensorDefinition]:
    """One sensor per end state, each monitoring exactly `jobs` (`daily` and `idmap`)."""
    made = []
    for name, status in SENSORS.items():

        @run_status_sensor(
            name=name,
            run_status=status,
            monitored_jobs=list(jobs),
            default_status=DefaultSensorStatus.RUNNING,
        )
        def sensor(context: RunStatusSensorContext) -> SkipReason | None:
            return notify(context)

        made.append(sensor)
    return made
