"""What the owner is told about a `daily` or `idmap` run, and the ping that carries it (spec 0219).

Why this module exists: a failed fetch fails a non-blocking check and the run still ends
`SUCCESS` (ADR 0129), so the run's status alone cannot say how it went. The outcome is read
from the run's own events (the failed steps, and each asset check's result and severity), turned
into a short plain-text report, and sent as the body of one healthchecks.io ping (ADR 0139). An
`ERROR` check or a failed run fails the ping; a `WARN` is reported only (ADR 0140).

Why a report of fixed-shape parts: it leaves the host, for healthchecks.io and the owner's
email, so it is built from names, keys, statuses, exit codes, ages, dbt unique ids, exception
class names and the stderr lines that fully match `ALERT_PATTERNS`, and never from an
exception's message (ADR 0141). `ALERT_PATTERNS` is narrower than `cli.ALLOWLIST`: no path, no
league id, and the HTTP give-up line is rewritten without its URL.

Why the key is read here and nowhere else: the ping key can mark a check up or down, so it is a
credential (AGENTS.md rule 3, ADR 0142). `ping_key` is the only function that opens its file,
`send` is the only one that builds a URL with it, and neither logs, returns or raises it.

This module logs nothing and holds no Dagster state: the sensors call it.
"""

from __future__ import annotations

import os
import re
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from dagster import AssetCheckSeverity, DagsterEventType, DagsterInstance, DagsterRun

SLUGS = {"daily": "front-office-daily", "idmap": "front-office-idmap"}
PING_KEY_FILE_VARIABLE = "FO_HEALTHCHECKS_PING_KEY_FILE"

NEW_YORK = ZoneInfo("America/New_York")
MAX_BYTES = 10_000  # what healthchecks.io's alert email shows of a body (spec 0219 C3)
PING_TRIES = 3
PING_TIMEOUT_SECONDS = 10
# healthchecks.io answers 429 above five pings a minute, so a retry waits; three tries and two
# pauses take at most 3 x 10 + 2 x 5 seconds.
PING_PAUSE_SECONDS = 5
PING_HOST = "https://hc-ping.com"
RUNBOOK = "docs/runbook/daily-run.md"
RUNBOOK_SECTION = "When an alert arrives"
UI_TUNNEL = "ssh -L 3000:127.0.0.1:3000 mothership"

# A failed dbt node as the dbt step records it: a unique id and `error` or `fail`, nothing else.
_FAILED_NODE = re.compile(
    r"(?:model|seed|snapshot|test|unit_test|source)\.[A-Za-z0-9_]+\.[A-Za-z0-9_.]+: (?:error|fail)"
)
# A dbt test's unique id, as an observation's metadata carries it: the id part of `_FAILED_NODE`.
_TEST_ID = re.compile(r"test\.[A-Za-z0-9_]+\.[A-Za-z0-9_.]+")
_KEY_SHAPE = re.compile(r"[A-Za-z0-9_-]+")
_LIST = r"\[[\d, ]*\]"

# Each pattern is anchored by `fullmatch` and written from a line of the CLI (see
# `cli.ALLOWLIST`), narrowed: a fixed text or a count, never a path, a URL or free text. The
# give-up line is the one with groups: `alert_lines` rewrites it from them, so its URL (which
# can hold anything a caller prints) is dropped whatever it holds.
_GIVE_UP = re.compile(
    r"(?P<what>player list|pro schedule): (?P<source>[a-z]+): gave up on [^\s\x00-\x1f]+ "
    r"after (?P<attempts>\d+) attempts "
    r"\(last failure: (?P<last>none|status \d{3}|[A-Za-z_][A-Za-z0-9_]*)\)"
)
ALERT_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"ESPN returned \d{3}: cookies expired — refresh ESPN_S2/SWID in \.env "
        r"from a logged-in browser session"
    ),
    re.compile(r"[a-z]+ returned \d{3}: credentials rejected"),
    re.compile(r"(?:boxscores|rosters|matchup days): fetched=\d+ skipped=\d+ failed=\d+"),
    re.compile(rf"failed game_pks: {_LIST}"),
    re.compile(rf"failed scoring periods: {_LIST}"),
    re.compile(rf"unproven scoring periods: {_LIST}"),
    re.compile(
        r"transactions: the page at offset \d+ has no valid `topics` list; page landed, but "
        r"the log is not shown complete"
    ),
    re.compile(r"transactions: transaction log still full after \d+ pages of \d+; stopped"),
    re.compile(r"\d+ privacy hit\(s\)\. Nothing was sent\."),
    re.compile(r"\w+\.\w+: \d+ committed, \d+ stored, \d+ to send"),
    _GIVE_UP,
)


class PingKeyUnreadable(Exception):
    """The file named by `FO_HEALTHCHECKS_PING_KEY_FILE` cannot be used. Never holds its content."""


@dataclass(frozen=True)
class Item:
    """One failure or warning: `kind` is `step`, `check` or `run`; `lines` are its kept details."""

    kind: str
    name: str
    lines: tuple[str, ...]


@dataclass(frozen=True)
class Outcome:
    run_id: str
    job: str
    status: str
    start: datetime | None
    end: datetime | None
    failures: list[Item]
    warnings: list[Item]


def ping_key(*, environ: Mapping[str, str] | None = None) -> str | None:
    """The ping key from the file the variable names; `None` when the variable is unset or empty.

    A file that is missing, empty or not exactly one line of `[A-Za-z0-9_-]+` (a trailing
    newline is allowed) raises `PingKeyUnreadable`, whose message names the variable only.
    """
    env = os.environ if environ is None else environ
    name = env.get(PING_KEY_FILE_VARIABLE, "")
    if not name:
        return None
    unreadable = PingKeyUnreadable(
        f"{PING_KEY_FILE_VARIABLE} names a file that is missing or is not one line of "
        "letters, digits, `_` and `-`"
    )
    try:
        text = Path(name).read_text(encoding="utf-8")
    except (OSError, ValueError):
        raise unreadable from None
    key = text.removesuffix("\n")
    if not _KEY_SHAPE.fullmatch(key):
        raise unreadable
    return key


def alert_lines(tail: str | Iterable[str]) -> tuple[str, ...]:
    """The lines of a stderr tail that may leave the host, in order; every other line is dropped.

    A line is kept if it fully matches an entry of `ALERT_PATTERNS`. The HTTP give-up line is
    kept rewritten as `<what>: <source>: gave up after <n> attempts (last failure: <x>)`.
    """
    lines = tail.splitlines() if isinstance(tail, str) else tail
    kept: list[str] = []
    for raw in lines:
        line = raw.rstrip("\r\n")
        for pattern in ALERT_PATTERNS:
            found = pattern.fullmatch(line)
            if not found:
                continue
            if pattern is _GIVE_UP:
                line = (
                    f"{found['what']}: {found['source']}: gave up after {found['attempts']} "
                    f"attempts (last failure: {found['last']})"
                )
            kept.append(line)
            break
    return tuple(kept)


def _meta(metadata: Mapping[str, Any] | None, key: str) -> Any:
    """The plain value of one metadata entry, or `None` when it is absent."""
    if not metadata or key not in metadata:
        return None
    return getattr(metadata[key], "value", None)


def _failed_nodes(value: Any) -> tuple[str, ...]:
    """The lines of a `failed_nodes` value that are a unique id and a status; others are dropped."""
    lines = str(value).splitlines() if value else []
    return tuple(line for line in lines if _FAILED_NODE.fullmatch(line))


def _when(timestamp: float | None) -> datetime | None:
    return None if timestamp is None else datetime.fromtimestamp(timestamp, NEW_YORK)


def outcome(instance: DagsterInstance, run: DagsterRun) -> Outcome:
    """The run's outcome, built only from its step failures, failed checks and observed dbt tests.

    A step failure gives the step key, the error's class name and the `failed_nodes` and
    `stderr_tail` metadata; its message is never read (ADR 0141). A failed check gives its asset
    key, name and the `stderr_tail`, `exit_code`, `status` and `age_hours` metadata: `ERROR`
    goes to `failures`, `WARN` to `warnings`. A dbt test that dagster-dbt records as an
    observation instead of a check (a singular test with several parents) gives its `unique_id`
    and `status`, once however many parents repeat it: `warn` to `warnings`, `fail` or `error` to
    `failures` unless a step already names it; its description is never read (spec 0219
    *Amendments*, 2026-11-21).
    """
    failures: list[Item] = []
    warnings: list[Item] = []
    steps = instance.get_records_for_run(run.run_id, of_type=DagsterEventType.STEP_FAILURE)
    for record in steps.records:
        event = record.event_log_entry.dagster_event
        if event is None:
            continue
        data = event.step_failure_data
        metadata = data.user_failure_data.metadata if data.user_failure_data else None
        cls_name = data.error.cls_name if data.error else None
        failures.append(
            Item(
                "step",
                f"{event.step_key} ({cls_name or 'unknown error'})",
                _failed_nodes(_meta(metadata, "failed_nodes"))
                + alert_lines(str(_meta(metadata, "stderr_tail") or "")),
            )
        )
    # dagster-dbt names a test's check by the test node's name, the third part of its unique id
    # (`test.<project>.<name>[.<hash>]`). A test that failed is listed once, by unique id (R3.4).
    listed_tests = {
        line.split(": ")[0].split(".")[2]
        for item in failures
        for line in item.lines
        if line.startswith("test.")
    }
    checks = instance.get_records_for_run(
        run.run_id, of_type=DagsterEventType.ASSET_CHECK_EVALUATION
    )
    for record in checks.records:
        event = record.event_log_entry.dagster_event
        if event is None:
            continue
        evaluation = event.asset_check_evaluation_data
        if evaluation.passed or evaluation.check_name in listed_tests:
            continue
        metadata = evaluation.metadata
        details = list(alert_lines(str(_meta(metadata, "stderr_tail") or "")))
        if (exit_code := _meta(metadata, "exit_code")) is not None:
            details.append(f"exit code {exit_code}")
        if (status := _meta(metadata, "status")) is not None:
            details.append(f"status {status}")
        if (age := _meta(metadata, "age_hours")) is not None:
            details.append(f"age {float(age):.1f} h")
        item = Item(
            "check",
            f"{evaluation.asset_key.to_user_string()}: {evaluation.check_name}",
            tuple(details),
        )
        if evaluation.severity == AssetCheckSeverity.ERROR:
            failures.append(item)
        else:
            warnings.append(item)
    # dagster-dbt records a singular test with several parents as an observation per parent, not
    # as an asset check; its metadata holds the test's `unique_id` and `status`. The observation's
    # description is dagster-dbt's message and is never read (ADR 0141).
    step_nodes = {
        line.split(": ")[0] for item in failures if item.kind == "step" for line in item.lines
    }
    observed: set[str] = set()
    observations = instance.get_records_for_run(
        run.run_id, of_type=DagsterEventType.ASSET_OBSERVATION
    )
    for record in observations.records:
        event = record.event_log_entry.dagster_event
        if event is None:
            continue
        metadata = event.asset_observation_data.asset_observation.metadata
        unique_id = _meta(metadata, "unique_id")
        test_status = _meta(metadata, "status")
        if (
            not isinstance(unique_id, str)
            or not _TEST_ID.fullmatch(unique_id)
            or test_status not in ("warn", "fail", "error")
            or unique_id in observed
        ):
            continue
        observed.add(unique_id)
        item = Item("check", unique_id, (f"status {test_status}",))
        if test_status == "warn":
            warnings.append(item)
        elif unique_id not in step_nodes:
            failures.append(item)
    status_name = run.status.value
    if status_name in ("FAILURE", "CANCELED") and not any(i.kind == "step" for i in failures):
        failures.append(Item("run", f"run ended {status_name}", ()))
    record_of_run = instance.get_run_record_by_id(run.run_id)
    return Outcome(
        run_id=run.run_id,
        job=run.job_name,
        status=status_name,
        start=_when(record_of_run.start_time if record_of_run else None),
        end=_when(record_of_run.end_time if record_of_run else None),
        failures=failures,
        warnings=warnings,
    )


def failed(result: Outcome) -> bool:
    """True when the ping must go to `/fail`: the run did not succeed, or an `ERROR` failed."""
    return result.status != "SUCCESS" or bool(result.failures)


def _stamp(moment: datetime | None) -> str:
    return "n/a" if moment is None else moment.strftime("%Y-%m-%d %H:%M:%S %Z")


def _item_lines(label: str, item: Item) -> list[str]:
    title = f"{label} {item.name}" if item.kind == "run" else f"{label} {item.kind} {item.name}"
    return [title, *(f"  {line}" for line in item.lines)]


def report(result: Outcome) -> str:
    """The plain-text body of the ping, at most `MAX_BYTES` of UTF-8, cut at a line boundary.

    When the failures and warnings do not fit, the lines that do are kept (inside an item too:
    one failed dbt step can name hundreds of nodes) and `… and <n> more` counts the rest.
    """
    verdict = "FAILED" if failed(result) else ("OK with warnings" if result.warnings else "OK")
    head = [
        f"front-office {result.job}: {verdict}",
        f"run: {result.run_id}",
        f"started: {_stamp(result.start)}",
        f"ended: {_stamp(result.end)}",
        f"status: {result.status}",
        "",
    ]
    listed = [
        line
        for label, items in (("FAILED", result.failures), ("WARNING", result.warnings))
        for item in items
        for line in _item_lines(label, item)
    ]
    tail = [
        "",
        f"Next: {RUNBOOK}, section '{RUNBOOK_SECTION}'.",
        f"Run page: /runs/{result.run_id}, through `{UI_TUNNEL}`.",
    ]

    def size(lines: list[str]) -> int:
        return len("\n".join(lines).encode("utf-8")) + 1

    kept = len(listed)
    while kept and size([*head, *listed[:kept], *_more(len(listed) - kept), *tail]) > MAX_BYTES:
        kept -= 1
    body = [*head, *listed[:kept], *_more(len(listed) - kept), *tail]
    return "\n".join(body) + "\n"


def _more(left_out: int) -> list[str]:
    return [f"… and {left_out} more"] if left_out else []


def send(
    slug: str,
    body: str,
    failed: bool,
    key: str,
    *,
    opener: Callable[..., Any] = urllib.request.urlopen,
    sleep: Callable[[float], None] = time.sleep,
) -> str:
    """POST the report to healthchecks.io.

    Returns `sent`, `not sent: HTTP <code>` or `not sent: <exception class>`.
    Up to `PING_TRIES` tries in all, `PING_TIMEOUT_SECONDS` each, `PING_PAUSE_SECONDS` apart;
    only an HTTP 200 is a success.
    It never raises, and the URL (which holds the key) never leaves it: not in the result, not
    in a log, not in an exception's text.
    """
    url = f"{PING_HOST}/{key}/{slug}" + ("/fail" if failed else "")
    outcome_text = "not sent: no try made"
    for attempt in range(PING_TRIES):
        if attempt:
            sleep(PING_PAUSE_SECONDS)
        try:
            request = urllib.request.Request(
                url,
                data=body.encode("utf-8"),
                headers={"Content-Type": "text/plain; charset=utf-8"},
                method="POST",
            )
            with opener(request, timeout=PING_TIMEOUT_SECONDS) as response:
                code = response.status
            if code == 200:
                return "sent"
            outcome_text = f"not sent: HTTP {code}"
        except urllib.error.HTTPError as error:
            outcome_text = f"not sent: HTTP {error.code}"
        except Exception as error:  # noqa: BLE001 - a ping must never raise into a sensor
            outcome_text = f"not sent: {type(error).__name__}"
    return outcome_text
