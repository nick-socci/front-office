"""R1.3, R1.4, R1.5 (spec 0218): the Dagster instance's settings and workspace, as files.

`deploy/dagster.yaml` is loaded through Dagster's own instance (so its schema validates it), in
a temporary DAGSTER_HOME holding a copy. One test also starts a real daemon on a scratch instance
built from that file with the limit cut to 10 seconds, and shows a run that outlives it ends failed.
"""

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import yaml
from dagster import DagsterInstance, DagsterRunStatus

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


SLEEPY = """
import time
from dagster import Definitions, job, op

@op
def sleep_a_while():
    time.sleep(300)

@job
def sleepy():
    sleep_a_while()

defs = Definitions(jobs=[sleepy])
"""


def test_a_run_that_outlives_the_limit_ends_failed(tmp_path: Path) -> None:
    """R1.5. Catches run monitoring that is configured but does not end a run: a stuck fetch would
    hold the next morning's run behind it (the instance runs one at a time).

    The committed instance file with only the limit and the poll interval cut, a daemon, and a job
    that sleeps for five minutes: the monitor must end it as FAILURE within the minute.
    """
    home = tmp_path / "home"
    home.mkdir()
    config = yaml.safe_load((DEPLOY / "dagster.yaml").read_text())
    config["run_monitoring"]["max_runtime_seconds"] = 10
    config["run_monitoring"]["poll_interval_seconds"] = 2
    (home / "dagster.yaml").write_text(yaml.safe_dump(config))
    module_dir = tmp_path / "code"
    module_dir.mkdir()
    (module_dir / "sleepy_pipeline.py").write_text(SLEEPY)
    env = {**os.environ, "DAGSTER_HOME": str(home), "PYTHONPATH": str(module_dir)}
    bin_dir = Path(sys.executable).parent
    # Create the SQLite tables first: the daemon and `job launch` both initialise a new instance,
    # and racing on its migration made `job launch` exit 2 about half the time.
    with DagsterInstance.from_config(str(home)) as instance:
        instance.get_runs()
    daemon_log = tmp_path / "daemon.log"
    daemon = subprocess.Popen(
        [str(bin_dir / "dagster-daemon"), "run", "-m", "sleepy_pipeline"],
        env=env,
        cwd=tmp_path,
        stdout=daemon_log.open("w"),
        stderr=subprocess.STDOUT,
    )
    try:
        launched = subprocess.run(
            [str(bin_dir / "dagster"), "job", "launch", "-m", "sleepy_pipeline", "-j", "sleepy"],
            env=env,
            cwd=tmp_path,  # not the repository root: Dagster would load its `.env` (0217 C14)
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert launched.returncode == 0, launched.stderr[-600:]
        deadline = time.monotonic() + 90
        status = None
        with DagsterInstance.from_config(str(home)) as instance:
            while time.monotonic() < deadline:
                runs = instance.get_runs()
                status = runs[0].status if runs else None
                if status in (DagsterRunStatus.FAILURE, DagsterRunStatus.SUCCESS):
                    break
                time.sleep(2)
            assert status == DagsterRunStatus.FAILURE, daemon_log.read_text()[-1500:]
            messages = [
                (event.get_dagster_event().message or "")
                for event in instance.all_logs(instance.get_runs()[0].run_id)
                if event.is_dagster_event
            ]
        assert any("Exceeded maximum runtime of 10 seconds" in m for m in messages)
    finally:
        daemon.terminate()
        try:
            daemon.wait(timeout=30)
        except subprocess.TimeoutExpired:
            daemon.kill()
