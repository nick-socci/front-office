"""The one place the orchestration calls the `front-office` CLI (R1.1, R2.4).

Why a subprocess: the CLI owns fetching, retrying, settling and the writer lock; the
orchestration only calls it and reads the exit code, so the pipeline is described once, here
and in the CLI, and nothing is re-implemented in Dagster (ADR 0127).

Why a filter: the CLI's output can name things that must never reach a Dagster log, event or
metadata, which the SQLite instance keeps (AGENTS.md rules 2 and 3): a cookie in an error
line, an ESPN account id, a member's name. So a line is kept only if it matches an allowlist
of the CLI's own line shapes (anchored, tested against the CLI's real output), and only if no
pattern of `front_office.privacy` (the GUID, the forbidden keys) matches it as well. The
privacy patterns are the second filter, not the only one: they do not cover a cookie value,
which the allowlist withholds because no allowed shape contains one. Every other line is
replaced by `<line withheld>`; no raw output is stored.

This module reads no file and no credential: the CLI reads `.env` itself, and the environment
is passed through unchanged.
"""

from __future__ import annotations

import re
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from front_office import privacy
from front_office_pipeline import settings

WITHHELD = "<line withheld>"
TAIL_LINES = 20
FRONT_OFFICE = ("front-office",)

# Each pattern is anchored (`fullmatch`) and written from an f-string of the CLI: `cli.py`'s
# `typer.echo` calls, `http_client.py`'s `_auth_message`, `upload.py`'s `say` calls and the
# messages of `LandingLocked` and `SettingsNotLanded`. `_PATH` is what a path or a free message
# may hold after a fixed prefix: no control characters.
_PATH = r"[^\x00-\x1f]+"
_LIST = r"\[[\d, ]*\]"
_COUNTS = r"fetched=\d+ skipped=\d+ failed=\d+"

ALLOWLIST: tuple[re.Pattern[str], ...] = tuple(
    re.compile(pattern)
    for pattern in (
        rf"landed (?:schedule|players|settings|teams|matchups|pro schedule) -> {_PATH}",
        rf"landed \d+ id-map rows -> {_PATH}",
        r"landed transactions: \d+ page\(s\), complete",
        rf"(?:boxscores|rosters|matchup days): {_COUNTS}",
        r"scoring periods: latest=\S+ final=\S+",
        rf"failed game_pks: {_LIST}",
        rf"failed scoring periods: {_LIST}",
        rf"unproven scoring periods: {_LIST}",
        rf"listed \d+ new capture\(s\) in {_PATH}",
        rf"(?:player list|pro schedule|transactions): {_PATH}",
        r"warning: a backfill is in progress; the result may be incomplete",
        # `ESPN returned 401: cookies expired — refresh ESPN_S2/SWID in .env …` names the
        # variables, never a value; the other sources' line is `<source> returned …`.
        r"ESPN returned \d{3}: cookies expired — refresh ESPN_S2/SWID in \.env "
        r"from a logged-in browser session",
        r"[a-z]+ returned \d{3}: credentials rejected",
        rf"another writer holds {_PATH}; wait for it to finish",
        rf"no settings captured for season \d+, league \S+: run {_PATH}",
        rf"quarantined (?:\d+ item\(s\) to |\w+ +){_PATH}",
        r"no --project: the remote checks \(schemas, stored keys\) did not run",
        r"\d+ privacy hit\(s\)\. Nothing was sent\.",
        r"dry run: nothing sent",
        r"nothing to send",
        r"created \w+\.\w+",
        r"(?:appended|replaced) \w+\.\w+: \d+ rows",
        r"\w+\.\w+: \d+ committed, \d+ stored, \d+ to send",
        r"known account ids: \d+; exempt transaction ids checked: \d+",
        r"every table holds each committed capture once, and the manifest names each",
        r"verify: every row of every table equals what would be sent",
        r"verify \w+\.\w+: \d+ equal, \d+ differ, \d+ missing, \d+ only stored",
    )
)

# The allowlist's free-text tails (`player list: …`) could in principle carry a pasted
# credential, so a cookie variable followed by a value is refused whatever the prefix.
_CREDENTIAL_ASSIGNMENT = re.compile(r"(?:ESPN_S2|SWID)\s*[=:]\s*\S")


class _Log(Protocol):
    def info(self, message: str, /) -> None: ...


class HasLog(Protocol):
    """What `run` needs of a Dagster context: somewhere to log to."""

    @property
    def log(self) -> _Log: ...


@dataclass(frozen=True)
class Result:
    exit_code: int
    tail: tuple[str, ...]


def filter_line(line: str) -> str:
    """The line itself if the allowlist matches it and no privacy pattern does, else `WITHHELD`."""
    text = line.rstrip("\r\n")
    if not any(pattern.fullmatch(text) for pattern in ALLOWLIST):
        return WITHHELD
    if privacy.GUID.search(text) or _CREDENTIAL_ASSIGNMENT.search(text):
        return WITHHELD
    if any(key in text for key in privacy.FORBIDDEN_KEYS):
        return WITHHELD
    return text


def _filtered(stream: str) -> list[str]:
    return [filter_line(line) for line in stream.splitlines() if line.strip()]


def run(args: Sequence[str], context: HasLog, *, prefix: Sequence[str] = FRONT_OFFICE) -> Result:
    """Run `<prefix> <args>` in the repository root; log and return only filtered lines.

    `prefix` is `front-office`, or `uv run --group bigquery front-office` for `upload`. The
    exit code is returned, not raised on: a fetch asset turns it into its check (R2.1), an
    upload into an exception (R2.2). A line withheld on stdout is withheld on stderr too; the
    tail is the last `TAIL_LINES` filtered stderr lines.
    """
    command = [*prefix, *args]
    context.log.info(f"running: {' '.join(command)}")
    completed = subprocess.run(
        command,
        cwd=settings.REPO_ROOT,
        capture_output=True,
        text=True,
        errors="replace",
        check=False,
    )
    stdout, stderr = _filtered(completed.stdout), _filtered(completed.stderr)
    for line in (*stdout, *stderr):
        context.log.info(line)
    context.log.info(f"exit code {completed.returncode}")
    return Result(exit_code=completed.returncode, tail=tuple(stderr[-TAIL_LINES:]))
