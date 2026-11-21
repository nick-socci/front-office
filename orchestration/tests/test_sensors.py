"""R1.3, R1.4, R1.5: the run-status sensors and the body they share.

Runs are real, on an ephemeral Dagster instance; `send` is a fake, so nothing leaves the machine.

Catches: a sensor that pings without a key (the laptop and CI must stay silent); a ping that
goes to the wrong slug or to `/fail` for a clean run (or to the plain URL for a failed check); a
key in a log line; a missing key file swallowed instead of shown; a sensor that is stopped by
default, monitors another job, or is missing for one of the three end states.
"""

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from dagster import (
    AssetCheckResult,
    AssetCheckSeverity,
    AssetCheckSpec,
    AssetKey,
    AssetSelection,
    AssetSpec,
    DagsterInstance,
    DagsterRunStatus,
    DefaultSensorStatus,
    Definitions,
    JobDefinition,
    MaterializeResult,
    SkipReason,
    build_run_status_sensor_context,
    define_asset_job,
    in_process_executor,
    multi_asset,
)

from front_office_pipeline import alerts, sensors

KEY = "k3y_SECRET-0123456789abcdef"


@pytest.fixture
def instance() -> Iterator[DagsterInstance]:
    with DagsterInstance.ephemeral() as ephemeral:
        yield ephemeral


@pytest.fixture(autouse=True)
def no_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(alerts.PING_KEY_FILE_VARIABLE, raising=False)


class FakeSend:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, bool, str]] = []

    def __call__(self, slug: str, body: str, failed: bool, key: str) -> str:
        self.calls.append((slug, body, failed, key))
        return "sent"


def _job(name: str, passed: bool) -> JobDefinition:
    @multi_asset(
        specs=[AssetSpec("fetch")],
        check_specs=[AssetCheckSpec("fetch_complete", asset="fetch", blocking=False)],
    )
    def fetch() -> Any:
        yield MaterializeResult(asset_key="fetch")
        yield AssetCheckResult(
            asset_key=AssetKey("fetch"),
            check_name="fetch_complete",
            passed=passed,
            severity=AssetCheckSeverity.ERROR,
        )

    job = define_asset_job(name, selection=AssetSelection.all(), executor_def=in_process_executor)
    return Definitions(assets=[fetch], jobs=[job]).resolve_job_def(name)


def _context(instance: DagsterInstance, job: JobDefinition) -> Any:
    result = job.execute_in_process(instance=instance, raise_on_error=False)
    run = instance.get_run_by_id(result.run_id)
    assert run is not None
    return build_run_status_sensor_context(
        sensor_name="ping_success",
        dagster_instance=instance,
        dagster_run=run,
        dagster_event=result.all_events[-1],
    )


def _key_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    file = tmp_path / "key"
    file.write_text(KEY + "\n", encoding="utf-8")
    monkeypatch.setenv(alerts.PING_KEY_FILE_VARIABLE, str(file))


def test_without_a_key_the_sensor_skips_and_sends_nothing(instance: DagsterInstance) -> None:
    fake = FakeSend()
    got = sensors.notify(_context(instance, _job("daily", True)), send=fake)
    assert isinstance(got, SkipReason)
    assert got.skip_message == "no FO_HEALTHCHECKS_PING_KEY_FILE: nothing sent"
    assert fake.calls == []


def test_a_clean_run_pings_the_plain_url_of_its_job(
    instance: DagsterInstance, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _key_file(tmp_path, monkeypatch)
    fake = FakeSend()
    sensors.notify(_context(instance, _job("idmap", True)), send=fake)
    [(slug, body, failed, key)] = fake.calls
    assert (slug, failed, key) == ("front-office-idmap", False, KEY)
    assert body.splitlines()[0] == "front-office idmap: OK"


def test_a_failed_error_check_pings_fail_and_the_log_line_has_no_key(
    instance: DagsterInstance, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _key_file(tmp_path, monkeypatch)
    fake = FakeSend()
    context = _context(instance, _job("daily", False))
    sensors.notify(context, send=fake)
    [(slug, _body, failed, _key)] = fake.calls
    assert (slug, failed) == ("front-office-daily", True)
    logged = [
        entry.dagster_event.message if entry.dagster_event else entry.user_message
        for entry in instance.all_logs(context.dagster_run.run_id)
    ]
    assert not any(KEY in str(line) for line in logged)


def test_the_log_line_names_the_slug_and_result_never_the_key(
    instance: DagsterInstance, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _key_file(tmp_path, monkeypatch)
    lines: list[str] = []
    context = _context(instance, _job("daily", False))
    monkeypatch.setattr(
        type(context.log), "info", lambda self, message, *a, **k: lines.append(message)
    )
    sensors.notify(context, send=FakeSend())
    assert lines == ["ping front-office-daily: fail sent"]


def test_an_unreadable_key_file_raises_so_the_tick_shows_it(
    instance: DagsterInstance, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv(alerts.PING_KEY_FILE_VARIABLE, str(tmp_path / "absent"))
    fake = FakeSend()
    with pytest.raises(alerts.PingKeyUnreadable):
        sensors.notify(_context(instance, _job("daily", True)), send=fake)
    assert fake.calls == []


def test_one_sensor_per_end_state_running_by_default_on_the_two_jobs() -> None:
    made: list[Any] = sensors.run_sensors([_job("daily", True), _job("idmap", True)])
    assert {s.name for s in made} == {"ping_success", "ping_failure", "ping_canceled"}
    # Dagster keeps the status and the monitored jobs private; these are the only way to see them.
    assert {s._run_status for s in made} == {
        DagsterRunStatus.SUCCESS,
        DagsterRunStatus.FAILURE,
        DagsterRunStatus.CANCELED,
    }
    for sensor in made:
        assert sensor.default_status == DefaultSensorStatus.RUNNING
        assert sorted(job.name for job in sensor._monitored_jobs or []) == ["daily", "idmap"]
