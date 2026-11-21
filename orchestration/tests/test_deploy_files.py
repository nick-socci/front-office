"""R2.1, R2.3, R2.4, R4.2, R5.1: the deployment files keep credentials out and the pull additive.

Catches: a credential in the build context (a `.containerignore` that is not at the root, or that
lost `.env`); a writable or missing credential mount; the UI container seeing a credential; a unit
key that Podman 4.9's Quadlet rejects (`Memory=`, a pod, systemd's `WorkingDirectory=`: spec C19);
a port published beyond the host's loopback; a pull that deletes or that marks a failed run good.

The generator itself runs on `mothership` (task 3 and 6); these tests hold the files to what it
accepted there.
"""

import os
import re
import stat
import subprocess
from pathlib import Path

import pytest
import yaml

from front_office_pipeline import settings

ROOT = settings.REPO_ROOT
DEPLOY = ROOT / "deploy"
UNITS = DEPLOY / "quadlet"
CODE = UNITS / "front-office-code.container"
DAEMON = UNITS / "front-office-daemon.container"
UI = UNITS / "front-office-ui.container"
ALL_UNITS = (CODE, DAEMON, UI)

# The [Container] keys Podman 4.9.3's Quadlet accepted on `mothership` (spec C19) or documents
# since 4.4. `Memory` and the `[Pod]` group are not among them.
ACCEPTED_CONTAINER_KEYS = {
    "Image",
    "ContainerName",
    "WorkingDir",
    "Exec",
    "Environment",
    "EnvironmentFile",
    "Volume",
    "Network",
    "PodmanArgs",
}
# `front-office.env` (the non-secret EnvironmentFile) is allowed; the ESPN `.env` is not.
CREDENTIAL_WORDS = ("secrets", "/app/.env", "google-key", "GOOGLE_APPLICATION_CREDENTIALS")


def unit_lines(path: Path) -> list[tuple[str, str, str]]:
    """(group, key, value) for each assignment, comments and blank lines dropped."""
    group = ""
    found = []
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            group = line[1:-1]
            continue
        key, _, value = line.partition("=")
        found.append((group, key, value))
    return found


def values(path: Path, group: str, key: str) -> list[str]:
    return [v for g, k, v in unit_lines(path) if g == group and k == key]


def ignore_patterns() -> set[str]:
    return {
        line.strip()
        for line in (ROOT / ".containerignore").read_text().splitlines()
        if line.strip() and not line.startswith("#")
    }


def test_containerignore_is_at_the_root_and_keeps_credentials_and_data_out() -> None:
    """Podman reads `.containerignore` from the build context, the repository root (F3)."""
    assert not (DEPLOY / ".containerignore").exists()
    patterns = ignore_patterns()
    for needed in (
        ".env",
        "**/.env",
        "*.env",
        "secrets",
        "data",
        ".git",
        ".review",
        "**/*.duckdb",
    ):
        assert needed in patterns, f".containerignore must exclude {needed}"
    assert any("google-key" in p or "key" in p for p in patterns)


def test_containerignore_never_re_includes_a_path() -> None:
    """A `!pattern` line puts back what an earlier line left out: `!.env` would undo the credential
    exclusion without any other line changing."""
    lines = (ROOT / ".containerignore").read_text().splitlines()
    assert not [line for line in lines if line.strip().startswith("!")]


def test_containerfile_copies_no_credential_and_labels_its_commit() -> None:
    text = (DEPLOY / "Containerfile").read_text()
    instructions = [
        line
        for line in text.splitlines()
        if re.match(r"\s*(COPY|ADD|ENV|ARG)\b", line) and not line.strip().startswith("#")
    ]
    joined = "\n".join(instructions)
    assert ".env" not in joined.replace("UV_PROJECT_ENVIRONMENT", "")
    for cookie_name in ("ESPN_S2", "SWID", "GOOGLE_APPLICATION_CREDENTIALS"):
        assert cookie_name not in joined
    assert "ARG GIT_COMMIT" in text and "org.opencontainers.image.revision" in text
    assert "--locked" in text
    assert 'ENTRYPOINT ["/app/deploy/entrypoint.sh"]' in text


def test_units_only_use_keys_podman_4_9_accepts() -> None:
    for unit in ALL_UNITS:
        groups = {g for g, _, _ in unit_lines(unit)}
        assert groups <= {"Unit", "Container", "Service", "Install"}, "Quadlet 4.9 has no [Pod]"
        keys = {k for g, k, _ in unit_lines(unit) if g == "Container"}
        assert keys <= ACCEPTED_CONTAINER_KEYS, keys - ACCEPTED_CONTAINER_KEYS
        assert not any(k == "WorkingDirectory" for g, k, _ in unit_lines(unit) if g == "Container")
        assert values(unit, "Container", "WorkingDir") == ["/dagster_home"]


def test_each_unit_has_a_memory_limit_a_restart_and_starts_at_boot() -> None:
    for unit in ALL_UNITS:
        limits = [v for v in values(unit, "Container", "PodmanArgs") if v.startswith("--memory=")]
        assert len(limits) == 1
        # dagster-daemon as PID 1 does not reap children: the first rehearsal on `mothership`
        # showed 27 <defunct> processes after a few runs, against a 2,048-process limit
        assert "--init" in values(unit, "Container", "PodmanArgs")
        assert values(unit, "Service", "Restart") == ["always"]
        assert values(unit, "Install", "WantedBy") == ["default.target"]


def test_the_code_server_mounts_the_credentials_read_only() -> None:
    """Runs execute in the code server's container (ADR 0138), so it is the one that holds them."""
    mounts = values(CODE, "Container", "Volume")
    for needle in ("/app/.env", "/run/secrets/google-key.json"):
        matching = [m for m in mounts if m.split(":")[1] == needle]
        assert len(matching) == 1, needle
        assert matching[0].endswith(":ro"), f"{needle} must be mounted read-only"
    environment = values(CODE, "Container", "Environment")
    assert "GOOGLE_APPLICATION_CREDENTIALS=/run/secrets/google-key.json" in environment
    assert "FO_LANDING_ROOT=/data/raw" in environment
    # the landing zone is mounted one level above its root: the writer lock sits beside it
    assert any(m.startswith("%h/data:/data:") for m in mounts)


def test_the_ping_key_reaches_the_code_server_only_and_read_only() -> None:
    """R5.1. Catches a writable mount, a wrong path or variable, or the key leaking into the
    daemon or the UI."""
    mount = "%h/secrets/healthchecks-ping-key:/run/secrets/healthchecks-ping-key:ro"
    assert values(CODE, "Container", "Volume").count(mount) == 1
    assert "FO_HEALTHCHECKS_PING_KEY_FILE=/run/secrets/healthchecks-ping-key" in values(
        CODE, "Container", "Environment"
    )
    for unit in (DAEMON, UI):
        assert "healthchecks" not in unit.read_text().lower(), unit.name


def test_the_daemon_and_the_ui_see_no_credential_and_listen_on_loopback_only() -> None:
    for unit in (DAEMON, UI):
        code = "\n".join(
            line
            for line in unit.read_text().splitlines()
            if line.strip() and not line.strip().startswith("#")
        )
        for word in CREDENTIAL_WORDS:
            assert word not in code, f"{unit.name} must not mention {word}"
        assert "FO_LANDING_ROOT" not in code and "/data" not in code
    # on the host's network, the bind address is what keeps a process off every other address
    assert "-h 127.0.0.1" in values(UI, "Container", "Exec")[0]
    assert "-h 127.0.0.1" in values(CODE, "Container", "Exec")[0]
    assert "PublishPort" not in "".join(u.read_text() for u in ALL_UNITS)


def test_the_three_units_share_the_hosts_loopback_and_the_code_servers_port() -> None:
    """ADR 0138. Catches a daemon or UI that loads its own code (code servers on unix sockets that
    cannot reach each other's runs), or a port that differs between the server and the workspace."""
    for unit in ALL_UNITS:
        assert values(unit, "Container", "Network") == ["host"]
    workspace = yaml.safe_load((DEPLOY / "workspace.yaml").read_text())
    server = workspace["load_from"][0]["grpc_server"]
    exec_line = values(CODE, "Container", "Exec")[0]
    assert f"-p {server['port']}" in exec_line
    assert f"--location-name {server['location_name']}" in exec_line
    for unit in (DAEMON, UI):
        assert "-w /app/deploy/workspace.yaml" in values(unit, "Container", "Exec")[0]
        assert "front-office-code.service" in values(unit, "Unit", "After")[0]


def test_no_unit_holds_a_cookie_value_or_a_project() -> None:
    for unit in ALL_UNITS:
        for _, key, value in unit_lines(unit):
            if key == "Environment":
                assert not re.match(r"(ESPN_S2|SWID|LEAGUE_ID|FO_BQ_PROJECT)=", value), value


def test_the_entrypoint_copies_the_images_instance_file_then_execs() -> None:
    script = DEPLOY / "entrypoint.sh"
    assert os.access(script, os.X_OK)
    text = script.read_text()
    assert 'cp /app/deploy/dagster.yaml "$DAGSTER_HOME/dagster.yaml"' in text
    assert 'exec "$@"' in text


# --- the pull ---------------------------------------------------------------------------------


@pytest.fixture
def fake_rsync(tmp_path: Path) -> tuple[dict[str, str], Path]:
    """A `rsync` first on PATH that records its arguments and exits as FAKE_RSYNC_EXIT says."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    record = tmp_path / "rsync.args"
    stub = bin_dir / "rsync"
    stub.write_text(
        '#!/bin/sh\nprintf "%s\\n" "$@" > "$FAKE_RSYNC_RECORD"\nexit "${FAKE_RSYNC_EXIT:-0}"\n'
    )
    stub.chmod(stub.stat().st_mode | stat.S_IXUSR)
    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "FAKE_RSYNC_RECORD": str(record),
    }
    return env, record


def pull(env: dict[str, str], *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(DEPLOY / "pull_landing.sh"), *args], env=env, capture_output=True, text=True
    )


def test_the_pull_adds_and_never_deletes(
    fake_rsync: tuple[dict[str, str], Path], tmp_path: Path
) -> None:
    env, record = fake_rsync
    result = pull(env, "front-office@mothership:./", str(tmp_path / "copy" / "raw"))
    assert result.returncode == 0, result.stderr
    args = record.read_text().splitlines()
    assert "--archive" in args and "--ignore-existing" in args
    assert "--exclude" in args and "*.tmp-*" in args
    assert not any(a.startswith("--delete") for a in args)
    assert args[-2:] == ["front-office@mothership:./", str(tmp_path / "copy" / "raw") + "/"]


def test_the_pull_refuses_an_option_that_deletes(
    fake_rsync: tuple[dict[str, str], Path], tmp_path: Path
) -> None:
    env, record = fake_rsync
    for option in ("--delete", "--delete-after", "--remove-source-files"):
        result = pull(env, "src:./", str(tmp_path / "raw"), option)
        assert result.returncode == 2, option
        assert not record.exists(), "rsync must not run"


def test_last_pull_ok_is_written_after_a_good_run_and_not_after_a_failed_one(
    fake_rsync: tuple[dict[str, str], Path], tmp_path: Path
) -> None:
    env, _ = fake_rsync
    marker = tmp_path / "last_pull_ok"
    failed = pull({**env, "FAKE_RSYNC_EXIT": "23"}, "src:./", str(tmp_path / "raw"))
    assert failed.returncode == 23
    assert not marker.exists()
    good = pull(env, "src:./", str(tmp_path / "raw"))
    assert good.returncode == 0
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ\n", marker.read_text())


@pytest.mark.parametrize("option", ["-n", "--dry-run", "-an", "-nv", "-vvn"])
def test_a_dry_run_leaves_no_marker(
    fake_rsync: tuple[dict[str, str], Path], tmp_path: Path, option: str
) -> None:
    """Catches a marker written after a run that copied nothing, whichever way `-n` is spelled."""
    env, _ = fake_rsync
    assert pull(env, "src:./", str(tmp_path / "raw"), option).returncode == 0
    assert not (tmp_path / "last_pull_ok").exists()


@pytest.mark.parametrize("option", ["-v", "-av", "--progress", "--bwlimit=100"])
def test_other_options_still_mark_a_good_pull(
    fake_rsync: tuple[dict[str, str], Path], tmp_path: Path, option: str
) -> None:
    """No `n` among the short options, or an `n` only inside a long option, is not a dry run."""
    env, _ = fake_rsync
    assert pull(env, "src:./", str(tmp_path / "raw"), option).returncode == 0
    assert (tmp_path / "last_pull_ok").exists()


def test_the_pull_needs_a_source_and_a_destination(
    fake_rsync: tuple[dict[str, str], Path], tmp_path: Path
) -> None:
    env, record = fake_rsync
    for args in ((), ("only-a-source:./",)):
        result = pull(env, *args)
        assert result.returncode == 2, args
        assert "usage" in result.stderr
        assert not record.exists(), "rsync must not run without a destination"
