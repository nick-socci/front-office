"""R1.3, R1.4, R1.5 (spec 0218): the Dagster instance's settings and workspace, as files.

`deploy/dagster.yaml` is loaded through Dagster's own instance (so its schema validates it), in
a temporary DAGSTER_HOME holding a copy. A run that really outlives `max_runtime_seconds` is not
tested: the smallest honest limit is a minute of sleeping; this checks the instance reads the
limit and the monitor is on, and Dagster's own tests hold the monitor.
"""

import shutil
from pathlib import Path

import yaml
from dagster import DagsterInstance

from front_office_pipeline import settings

DEPLOY = settings.REPO_ROOT / "deploy"


def load_instance(tmp_path: Path) -> DagsterInstance:
    shutil.copy(DEPLOY / "dagster.yaml", tmp_path / "dagster.yaml")
    return DagsterInstance.from_config(str(tmp_path))


def test_the_instance_allows_one_run_at_a_time(tmp_path: Path) -> None:
    """R1.3. Catches the default of ten: a second `daily` would start beside the first and
    its fetch would fail on the landing zone's writer lock (C3)."""
    with load_instance(tmp_path) as instance:
        # What the queued-run daemon reads when it decides how many runs to dequeue.
        queue = instance.get_concurrency_config().run_queue_config
        assert queue is not None
        assert queue.max_concurrent_runs == 1


def test_the_instance_ends_a_run_after_two_hours(tmp_path: Path) -> None:
    """R1.4. Catches run monitoring off, or a limit other than 7200 seconds."""
    with load_instance(tmp_path) as instance:
        assert instance.run_monitoring_enabled
        assert instance.run_monitoring_max_runtime_seconds == 7200


def test_the_instance_file_validates_and_turns_telemetry_off(tmp_path: Path) -> None:
    """R1.3. Catches a key Dagster rejects (loading raises) and telemetry left on."""
    with load_instance(tmp_path) as instance:
        assert not instance.telemetry_enabled


def test_the_instance_sets_nothing_for_catching_up() -> None:
    """R1.5 (C2). Catches a `max_catchup_runs`: it applies to partitioned schedules only, so
    it would claim a behaviour the schedules do not have."""
    text = (DEPLOY / "dagster.yaml").read_text()
    assert "max_catchup_runs" not in text
    assert "scheduler" not in yaml.safe_load(text)


def test_the_instance_keeps_dagsters_default_sqlite_storage() -> None:
    """R1.3. Catches a configured storage (a Postgres, or a path outside DAGSTER_HOME)."""
    config = yaml.safe_load((DEPLOY / "dagster.yaml").read_text())
    assert not {"storage", "run_storage", "event_log_storage", "schedule_storage"} & set(config)


def test_the_workspace_loads_the_code_location_from_the_shared_code_server() -> None:
    """R1.3, ADR 0138. Catches a workspace that loads its own module (a code server per process, on
    a unix socket the other process cannot reach), or one that names another host or location."""
    workspace = yaml.safe_load((DEPLOY / "workspace.yaml").read_text())
    assert workspace == {
        "load_from": [
            {
                "grpc_server": {
                    "host": "127.0.0.1",
                    "port": 4266,
                    "location_name": "front_office_pipeline",
                }
            }
        ]
    }
