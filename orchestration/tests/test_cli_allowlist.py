"""R2.4: what of a command's output reaches a Dagster log, event or metadata.

Catches: an allowlist that drifts from the CLI's own messages (a shape the CLI prints that
is withheld, or one the allowlist invents); a cookie value, GUID or member key in an error
line reaching the Dagster instance; raw output stored; a command run outside the repository
root or without the environment; a command's tail that is not the last stderr lines.
"""

import subprocess
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

from front_office_pipeline import cli, settings

REPO_ROOT = settings.REPO_ROOT
GUID = "{272E019C-48D5-42F3-B289-C48A1B163E19}"


class Logs:
    def __init__(self) -> None:
        self.lines: list[str] = []

    def info(self, message: str, /) -> None:
        self.lines.append(message)

    warning = info


class Context:
    def __init__(self) -> None:
        self.log = Logs()


# One line of each shape the CLI prints (cli.py's typer.echo calls, http_client.py's
# `_auth_message`, upload.py's `say` calls), written from those f-strings.
CLI_LINES = [
    "landed schedule -> data/raw/mlb/schedule/season=2026/fetched_at=20261110T034033Z",
    "landed players -> /srv/raw/mlb/players/season=2026/fetched_at=20261110T034033Z",
    "landed settings -> data/raw/espn/settings/league=1/season=2026/fetched_at=20261110T034033Z",
    "landed teams -> data/raw/espn/teams/league=1/season=2026/fetched_at=20261110T034033Z",
    "landed matchups -> data/raw/espn/matchups/league=1/season=2026/fetched_at=20261110T034033Z",
    "landed pro schedule -> data/raw/espn/pro_schedule/season=2026/fetched_at=20261110T034033Z",
    "landed 2503 id-map rows -> data/raw/idmap/fetched_at=20261110T034033Z",
    "landed transactions: 3 page(s), complete",
    "boxscores: fetched=12 skipped=2400 failed=0",
    "rosters: fetched=1 skipped=187 failed=0",
    "matchup days: fetched=0 skipped=1469 failed=0",
    "scoring periods: latest=188 final=180",
    "scoring periods: latest=None final=None",
    "failed game_pks: [745001, 745002]",
    "failed game_pks: []",
    "failed scoring periods: [3, 4]",
    "unproven scoring periods: [7]",
    "listed 22 new capture(s) in /tmp/x/w.duckdb",
    "player list: mlb: gave up on https://statsapi.mlb.com/x after 4 attempts (last failure: 500)",
    "pro schedule: espn: gave up on https://x/y after 4 attempts (last failure: 503)",
    "transactions: the log is incomplete: 2 page(s) missing",
    "warning: a backfill is in progress; the result may be incomplete",
    "ESPN returned 401: cookies expired — refresh ESPN_S2/SWID in .env "
    "from a logged-in browser session",
    "mlb returned 403: credentials rejected",
    "another writer holds data/raw/.lock; wait for it to finish",
    "quarantined 3 item(s) to data/raw/_quarantine/20261110T034033Z",
    "quarantined tmp     data/raw/x.tmp-12",
    "created raw.mlb_schedule",
    "appended raw.mlb_schedule: 12 rows",
    "replaced raw.captures: 3000 rows",
    "nothing to send",
    "no --project: the remote checks (schemas, stored keys) did not run",
    "2 privacy hit(s). Nothing was sent.",
    "dry run: nothing sent",
    "raw.mlb_schedule: 12 committed, 10 stored, 2 to send",
    "known account ids: 12; exempt transaction ids checked: 3",
    "every table holds each committed capture once, and the manifest names each",
]


@pytest.mark.parametrize("line", CLI_LINES)
def test_each_shape_the_cli_prints_is_kept(line: str) -> None:
    assert cli.filter_line(line) == line


@pytest.mark.parametrize(
    "line",
    [
        "ESPN_S2=abc123",
        "SWID={not-a-real-guid}",
        "export ESPN_S2=abc",
        f"landed teams -> data/raw/espn/teams/{GUID}",
        f"scoring periods: latest=1 final=2 {GUID}",
        "landed teams -> x with firstName in it",
        "transactions: displayName=Someone",
        "player list: ESPN_S2=abc",
        "player list: members",
        "primaryOwner: x",
        "Traceback (most recent call last):",
        '  File "x.py", line 1, in <module>',
        "boxscores: fetched=1 skipped=2 failed=3 and more",
        "landed settings",
        "",
        "   ",
    ],
)
def test_a_line_outside_the_allowlist_or_matching_a_privacy_pattern_is_withheld(
    line: str,
) -> None:
    assert cli.filter_line(line) == cli.WITHHELD


def test_every_forbidden_key_is_withheld_even_inside_an_allowed_shape() -> None:
    from front_office import privacy

    for key in privacy.FORBIDDEN_KEYS:
        assert cli.filter_line(f"player list: saw {key} in the body") == cli.WITHHELD


def _fake_subprocess(
    monkeypatch: pytest.MonkeyPatch, *, code: int, stdout: str, stderr: str
) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    def fake_run(command: Sequence[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append({"command": list(command), **kwargs})
        return subprocess.CompletedProcess(command, code, stdout, stderr)

    monkeypatch.setattr("front_office_pipeline.cli.subprocess.run", fake_run)
    return calls


def test_run_logs_and_returns_only_filtered_lines(monkeypatch: pytest.MonkeyPatch) -> None:
    """The hostile lines never reach the log or the tail, whichever stream they came on."""
    stdout = f"boxscores: fetched=1 skipped=0 failed=0\nESPN_S2=abc\n{GUID}\n"
    stderr = "warning: a backfill is in progress; the result may be incomplete\nauthor: x\n"
    _fake_subprocess(monkeypatch, code=1, stdout=stdout, stderr=stderr)
    context = Context()
    result = cli.run(["backfill", "mlb", "--season", "2026"], context)
    assert result.exit_code == 1
    assert result.tail == (
        "warning: a backfill is in progress; the result may be incomplete",
        cli.WITHHELD,
    )
    logged = "\n".join(context.log.lines)
    for secret in ("ESPN_S2=abc", GUID, "author"):
        assert secret not in logged
        assert secret not in "\n".join(result.tail)
    assert "boxscores: fetched=1 skipped=0 failed=0" in logged
    # The arguments are recorded.
    assert "backfill mlb --season 2026" in logged


def test_the_tail_is_the_last_twenty_stderr_lines(monkeypatch: pytest.MonkeyPatch) -> None:
    stderr = "".join(f"failed scoring periods: [{n}]\n" for n in range(30))
    _fake_subprocess(monkeypatch, code=1, stdout="", stderr=stderr)
    result = cli.run(["x"], Context())
    assert len(result.tail) == 20
    assert result.tail[0] == "failed scoring periods: [10]"
    assert result.tail[-1] == "failed scoring periods: [29]"


def test_run_uses_the_repository_root_the_environment_and_the_prefix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _fake_subprocess(monkeypatch, code=0, stdout="", stderr="")
    cli.run(["load", "--raw-root", "/r"], Context())
    cli.run(["upload"], Context(), prefix=("uv", "run", "--group", "bigquery", "front-office"))
    first, second = calls
    assert first["command"] == ["front-office", "load", "--raw-root", "/r"]
    assert second["command"] == ["uv", "run", "--group", "bigquery", "front-office", "upload"]
    for call in calls:
        assert Path(call["cwd"]) == REPO_ROOT
        # The environment is passed through (None means "inherit"); nothing is read here.
        assert call.get("env") is None
        assert call["capture_output"] is True


def test_the_real_cli_output_on_the_fixtures_is_kept_not_withheld(tmp_path: Path) -> None:
    """Runs the real `load` and `upload --dry-run` over the committed fixtures.

    Catches an allowlist that withholds the CLI's own success lines (drift), seen only on
    real output, not on lines written from the f-strings.
    """
    context = Context()
    db = tmp_path / "w.duckdb"
    result = cli.run(
        ["load", "--raw-root", str(REPO_ROOT / "fixtures" / "landing"), "--db", str(db)],
        context,
    )
    assert result.exit_code == 0
    kept = [line for line in context.log.lines if line.startswith("listed ")]
    assert kept and all(cli.WITHHELD not in line for line in kept)

    context = Context()
    result = cli.run(
        [
            "upload",
            "--dry-run",
            "--raw-root",
            str(REPO_ROOT / "fixtures" / "landing"),
            "--work-dir",
            str(tmp_path),
        ],
        context,
    )
    # The fixtures hold a transaction topic the upload's own privacy check refuses (exit 1).
    # The line saying so is the CLI's, and stays legible; the line naming the hit is not on
    # the allowlist and is withheld.
    assert result.exit_code == 1
    assert "no --project: the remote checks (schemas, stored keys) did not run" in context.log.lines
    assert "1 privacy hit(s). Nothing was sent." in result.tail
    assert cli.WITHHELD in result.tail
