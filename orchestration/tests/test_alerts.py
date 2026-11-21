"""R1.1, R1.2, R1.5, R2.1, R2.2, R2.5, R3.1 to R3.3: the alert's outcome, report and ping.

The outcome is read from real runs on an ephemeral Dagster instance (small jobs shaped like the
daily run's failures); `send` is held with a fake opener, so nothing leaves the machine.

Catches: a `SUCCESS` run with a failed fetch reported as good; a `WARN` failing the ping; a
cancelled run left unreported; a key in a log line, a report, an outcome or an exception; a ping
that raises into the sensor, or a URL in what it returns; a report cut mid-line, over 10,000
bytes, or without the count of what it left out; a path, the league's id or a URL reaching the
report through a stderr line.
"""

import datetime
import io
import logging
import re
import urllib.error
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from dagster import (
    AssetCheckResult,
    AssetCheckSeverity,
    AssetCheckSpec,
    AssetKey,
    AssetObservation,
    AssetSelection,
    AssetSpec,
    DagsterInstance,
    Definitions,
    Failure,
    JobDefinition,
    MaterializeResult,
    MetadataValue,
    Output,
    asset,
    define_asset_job,
    in_process_executor,
    multi_asset,
)

from front_office_pipeline import alerts, cli

KEY = "k3y_SECRET-0123456789abcdef"
COOKIE_LINE = (
    "ESPN returned 401: cookies expired — refresh ESPN_S2/SWID in .env "
    "from a logged-in browser session"
)
LEAGUE_URL = "https://lm-api-reads.fantasy.espn.com/x?league_id=123&view=mRoster"


@pytest.fixture
def instance() -> Iterator[DagsterInstance]:
    with DagsterInstance.ephemeral() as ephemeral:
        yield ephemeral


def _fetch(
    severity: AssetCheckSeverity, passed: bool, metadata: dict[str, Any]
) -> Any:  # a multi_asset definition
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
            severity=severity,
            metadata=metadata,
        )

    return fetch


def _job(*definitions: Any, name: str = "daily") -> JobDefinition:
    job = define_asset_job(name, selection=AssetSelection.all(), executor_def=in_process_executor)
    return Definitions(assets=list(definitions), jobs=[job]).resolve_job_def(name)


def _run(instance: DagsterInstance, job: JobDefinition) -> alerts.Outcome:
    result = job.execute_in_process(instance=instance, raise_on_error=False)
    run = instance.get_run_by_id(result.run_id)
    assert run is not None
    return alerts.outcome(instance, run)


def _stderr(*lines: str) -> dict[str, Any]:
    return {"stderr_tail": MetadataValue.text("\n".join(lines)), "exit_code": 1}


# ---------------------------------------------------------------- outcome and failed (R1.2, R2)


def test_a_failed_error_check_fails_the_ping_though_the_run_succeeded(
    instance: DagsterInstance,
) -> None:
    tail = _stderr(COOKIE_LINE, "landed teams -> data/raw/espn/teams/league_id=123/x", "noise")
    got = _run(instance, _job(_fetch(AssetCheckSeverity.ERROR, False, tail)))
    assert got.status == "SUCCESS"
    assert got.job == "daily"
    assert alerts.failed(got)
    [failure] = got.failures
    assert (failure.kind, failure.name) == ("check", "fetch: fetch_complete")
    assert COOKIE_LINE in failure.lines
    assert "exit code 1" in failure.lines
    assert not any("league_id" in line or "noise" in line for line in failure.lines)
    assert got.warnings == []
    assert alerts.report(got).splitlines()[0] == "front-office daily: FAILED"


def test_a_failed_warn_check_is_reported_and_does_not_fail_the_ping(
    instance: DagsterInstance,
) -> None:
    meta = {"status": "warn", "age_hours": 40.5}
    got = _run(instance, _job(_fetch(AssetCheckSeverity.WARN, False, meta)))
    assert not alerts.failed(got)
    assert got.failures == []
    [warning] = got.warnings
    assert warning.name == "fetch: fetch_complete"
    assert "status warn" in warning.lines
    assert "age 40.5 h" in warning.lines
    assert alerts.report(got).splitlines()[0] == "front-office daily: OK with warnings"


def test_a_passed_check_is_not_listed(instance: DagsterInstance) -> None:
    got = _run(instance, _job(_fetch(AssetCheckSeverity.ERROR, True, _stderr())))
    assert not alerts.failed(got)
    assert (got.failures, got.warnings) == ([], [])
    assert alerts.report(got).splitlines()[0] == "front-office daily: OK"


def test_a_raising_step_is_named_with_its_class_and_failed_nodes_but_not_its_message(
    instance: DagsterInstance,
) -> None:
    @asset
    def build() -> None:
        raise Failure(
            description="tie for place 1 in (league 123, user secret-name)",
            metadata={"failed_nodes": MetadataValue.text("model.fo.a: error\ntest.fo.b: fail")},
        )

    got = _run(instance, _job(build))
    assert got.status == "FAILURE"
    assert alerts.failed(got)
    [failure] = got.failures
    assert (failure.kind, failure.name) == ("step", "build (Failure)")
    assert list(failure.lines) == ["model.fo.a: error", "test.fo.b: fail"]
    text = alerts.report(got)
    assert text.splitlines()[0] == "front-office daily: FAILED"
    assert "secret-name" not in text
    assert "league 123" not in text


def test_failed_nodes_lines_that_are_not_a_node_and_a_status_are_dropped(
    instance: DagsterInstance,
) -> None:
    value = "\n".join(
        [
            "model.front_office.a: error",
            "model.front_office.x: error rows tie for place 1 in (123)",
            "data/raw/espn/teams/league_id=123/x",
            "test.front_office.not_null_a_id.abc123: fail",
            "model.front_office.b: skipped",
            "unit_test.front_office.m.t: fail",
            "source.front_office.raw.captures: error",
        ]
    )

    @asset
    def build() -> None:
        raise Failure(description="x", metadata={"failed_nodes": MetadataValue.text(value)})

    [failure] = _run(instance, _job(build)).failures
    assert list(failure.lines) == [
        "model.front_office.a: error",
        "test.front_office.not_null_a_id.abc123: fail",
        "unit_test.front_office.m.t: fail",
        "source.front_office.raw.captures: error",
    ]


def test_a_failing_dbt_test_is_listed_once_by_its_unique_id(instance: DagsterInstance) -> None:
    @multi_asset(
        specs=[AssetSpec("x")],
        check_specs=[
            AssetCheckSpec("not_null_x_id", asset="x", blocking=False),
            AssetCheckSpec("other_check", asset="x", blocking=False),
            AssetCheckSpec("warned_test", asset="x", blocking=False),
        ],
    )
    def dbt_like() -> Any:
        yield MaterializeResult(asset_key="x")
        for name, severity in (
            ("not_null_x_id", AssetCheckSeverity.ERROR),
            ("other_check", AssetCheckSeverity.ERROR),
            ("warned_test", AssetCheckSeverity.WARN),
        ):
            yield AssetCheckResult(
                asset_key=AssetKey("x"), check_name=name, passed=False, severity=severity
            )

    @asset(deps=["x"])
    def front_office_dbt() -> None:
        raise Failure(
            description="x",
            metadata={
                "failed_nodes": MetadataValue.text(
                    "test.front_office.not_null_x_id.abc123: fail\n"
                    "test.front_office.warned_test: fail"
                )
            },
        )

    got = _run(instance, _job(dbt_like, front_office_dbt))
    names = [item.name for item in got.failures]
    assert "x: not_null_x_id" not in names
    assert "x: other_check" in names
    assert [item.name for item in got.warnings] == []
    [step] = [item for item in got.failures if item.kind == "step"]
    assert "test.front_office.not_null_x_id.abc123: fail" in step.lines
    assert "test.front_office.warned_test: fail" in step.lines


def _observing(*observations: tuple[Any, Any]) -> Any:
    """An asset yielding one `AssetObservation` per (unique_id, status), as dagster-dbt does for
    a singular test with several parents (a `None` unique_id or status leaves the key out)."""

    @asset
    def observed() -> Any:
        for unique_id, status in observations:
            metadata = {
                key: value
                for key, value in (("unique_id", unique_id), ("status", status))
                if value is not None
            }
            metadata["description"] = "dagster-dbt's message: /home/x/secret_path"
            yield AssetObservation(asset_key="observed", metadata=metadata)
        yield Output(None)

    return observed


TEST_ID = "test.front_office.a_singular_test"


def test_a_warn_observation_is_one_warning_though_it_repeats_per_parent(
    instance: DagsterInstance,
) -> None:
    """Catches: a warn from a multi-parent singular test (an observation, no check) reported OK,
    or listed once per parent, or carrying dagster-dbt's description."""
    got = _run(instance, _job(_observing((TEST_ID, "warn"), (TEST_ID, "warn"))))
    assert got.failures == []
    assert got.warnings == [alerts.Item("check", TEST_ID, ("status warn",))]
    assert not alerts.failed(got)
    assert alerts.report(got).splitlines()[0] == "front-office daily: OK with warnings"
    assert "secret_path" not in alerts.report(got)


@pytest.mark.parametrize(
    ("unique_id", "status"),
    [
        (TEST_ID, "pass"),
        (TEST_ID, None),
        (TEST_ID, "skipped"),
        (None, "warn"),
        ("model.front_office.not_a_test", "fail"),
        ("test.front_office", "fail"),
        ("test.front_office.bad name: fail", "warn"),
        ("test.front_office.x\nmodel.a.b", "error"),
        (7, "warn"),
    ],
)
def test_an_observation_that_is_not_a_failing_test_of_the_fixed_shape_is_ignored(
    instance: DagsterInstance, unique_id: Any, status: Any
) -> None:
    got = _run(instance, _job(_observing((unique_id, status))))
    assert (got.failures, got.warnings) == ([], [])


def test_a_fail_observation_named_by_a_step_is_listed_once_in_the_step(
    instance: DagsterInstance,
) -> None:
    @asset(deps=["observed"])
    def front_office_dbt() -> None:
        raise Failure(
            description="x",
            metadata={"failed_nodes": MetadataValue.text(f"{TEST_ID}: fail")},
        )

    got = _run(instance, _job(_observing((TEST_ID, "fail"), (TEST_ID, "fail")), front_office_dbt))
    [step] = got.failures
    assert step.kind == "step"
    assert step.lines == (f"{TEST_ID}: fail",)


def test_a_fail_observation_no_step_names_is_a_failure(instance: DagsterInstance) -> None:
    got = _run(instance, _job(_observing((TEST_ID, "fail"), (TEST_ID, "error"))))
    assert got.failures == [alerts.Item("check", TEST_ID, ("status fail",))]
    assert alerts.failed(got)


def test_a_step_that_raises_with_a_stderr_tail_keeps_only_the_alert_lines(
    instance: DagsterInstance,
) -> None:
    @asset
    def upload() -> None:
        raise Failure(
            description="x",
            metadata=_stderr("raw.mlb_schedule: 12 committed, 10 stored, 2 to send", "other"),
        )

    [failure] = _run(instance, _job(upload)).failures
    assert list(failure.lines) == ["raw.mlb_schedule: 12 committed, 10 stored, 2 to send"]


def test_a_clean_run_has_no_items(instance: DagsterInstance) -> None:
    @asset
    def fine() -> None:
        return None

    got = _run(instance, _job(fine))
    assert (got.status, got.failures, got.warnings) == ("SUCCESS", [], [])
    assert not alerts.failed(got)


def test_a_cancelled_run_with_no_step_failure_is_one_run_item(
    instance: DagsterInstance,
) -> None:
    # An ephemeral instance has no daemon to cancel a live run, so the run is created and
    # reported cancelled, as the instance does when a queued run is terminated (it never started).
    job = _job(_fetch(AssetCheckSeverity.ERROR, True, _stderr()))
    run = instance.create_run_for_job(job)
    instance.report_run_canceled(run)
    cancelled = instance.get_run_by_id(run.run_id)
    assert cancelled is not None
    got = alerts.outcome(instance, cancelled)
    assert got.status == "CANCELED"
    assert alerts.failed(got)
    [failure] = got.failures
    assert (failure.kind, failure.name) == ("run", "run ended CANCELED")
    assert got.start is None
    text = alerts.report(got)
    assert text.splitlines()[0] == "front-office daily: FAILED"
    assert "CANCELED" in text


# ------------------------------------------------------------------------------ the report


def test_the_report_names_the_run_times_in_new_york_and_where_to_look(
    instance: DagsterInstance,
) -> None:
    got = _run(instance, _job(_fetch(AssetCheckSeverity.ERROR, False, _stderr(COOKIE_LINE))))
    text = alerts.report(got)
    assert f"run: {got.run_id}" in text
    assert "status: SUCCESS" in text
    assert got.start is not None
    assert got.start.utcoffset() in (datetime.timedelta(hours=-5), datetime.timedelta(hours=-4))
    assert re.search(r"started: \d{4}-\d\d-\d\d \d\d:\d\d:\d\d E[SD]T", text)
    assert re.search(r"ended: \d{4}-\d\d-\d\d \d\d:\d\d:\d\d E[SD]T", text)
    assert "docs/runbook/daily-run.md" in text
    assert "When an alert arrives" in text
    assert f"/runs/{got.run_id}" in text
    assert "ssh -L 3000:127.0.0.1:3000 mothership" in text
    assert text.index("FAILED check fetch: fetch_complete") < text.index("docs/runbook")


def test_failures_are_listed_before_warnings() -> None:
    out = alerts.Outcome(
        run_id="r",
        job="daily",
        status="SUCCESS",
        start=None,
        end=None,
        failures=[alerts.Item("check", "a: x", ("exit code 1",))],
        warnings=[alerts.Item("check", "b: y", ())],
    )
    lines = alerts.report(out).splitlines()
    assert lines.index("FAILED check a: x") < lines.index("WARNING check b: y")


def test_a_report_of_500_failed_nodes_is_cut_at_a_line_with_the_count_left_out() -> None:
    nodes = tuple(f"model.front_office.node_{n}: error" for n in range(500))
    out = alerts.Outcome(
        run_id="abc",
        job="daily",
        status="FAILURE",
        start=None,
        end=None,
        failures=[alerts.Item("step", "front_office_dbt (Failure)", nodes)],
        warnings=[],
    )
    text = alerts.report(out)
    assert len(text.encode("utf-8")) <= 10_000
    lines = text.splitlines()
    assert "FAILED step front_office_dbt (Failure)" in lines
    kept = [line.strip() for line in lines if "model.front_office.node_" in line]
    assert 0 < len(kept) < 500
    assert kept == [f"model.front_office.node_{n}: error" for n in range(len(kept))]
    more = [line for line in lines if line.startswith("… and ")]
    assert more == [f"… and {500 - len(kept)} more"]
    # The runbook section still follows the cut list.
    assert lines.index(more[0]) < next(i for i, line in enumerate(lines) if "runbook" in line)


def test_a_report_that_fits_has_no_more_line() -> None:
    out = alerts.Outcome(
        "r", "idmap", "FAILURE", None, None, [alerts.Item("step", "s (Failure)", ("a: error",))], []
    )
    assert "… and" not in alerts.report(out)


# -------------------------------------------------------------------- the alert's own patterns

# One sample for each entry of ALERT_PATTERNS, in order: the line the CLI prints.
SAMPLES = [
    COOKIE_LINE,
    "mlb returned 403: credentials rejected",
    "boxscores: fetched=12 skipped=2400 failed=0",
    "failed game_pks: [745001, 745002]",
    "failed scoring periods: [3, 4]",
    "unproven scoring periods: [7]",
    "transactions: the page at offset 50 has no valid `topics` list; page landed, but "
    "the log is not shown complete",
    "transactions: transaction log still full after 50 pages of 100; stopped",
    "2 privacy hit(s). Nothing was sent.",
    "raw.mlb_schedule: 12 committed, 10 stored, 2 to send",
    "player list: mlb: gave up on https://statsapi.mlb.com/x after 4 attempts "
    "(last failure: status 500)",
]
EXTRA_KEPT = [
    "rosters: fetched=1 skipped=187 failed=0",
    "matchup days: fetched=0 skipped=1469 failed=0",
    "failed game_pks: []",
    "pro schedule: espn: gave up on https://x/y after 4 attempts (last failure: ReadTimeout)",
]
# Lines the CLI's allowlist keeps and the report must not carry.
DROPPED = [
    "landed teams -> data/raw/espn/teams/season=2026/league_id=123/fetched_at=20261110T034033Z",
    "landed 2503 id-map rows -> data/raw/idmap/fetched_at=20261110T034033Z",
    "no settings captured for season 2026, league 123: run data/raw/x",
    "another writer holds data/raw/.lock; wait for it to finish",
    "quarantined 3 item(s) to data/raw/_quarantine/20261110T034033Z",
    "listed 22 new capture(s) in /tmp/x/w.duckdb",
    "scoring periods: latest=188 final=180",
    "nothing to send",
    "warning: a backfill is in progress; the result may be incomplete",
    cli.WITHHELD,
    "league_id=123",
    "Traceback (most recent call last):",
    "",
]


def test_there_is_one_sample_for_each_pattern() -> None:
    assert len(SAMPLES) == len(alerts.ALERT_PATTERNS)
    for sample, pattern in zip(SAMPLES, alerts.ALERT_PATTERNS, strict=True):
        assert pattern.fullmatch(sample), sample


@pytest.mark.parametrize("line", [*SAMPLES, *EXTRA_KEPT])
def test_a_line_the_cli_keeps_and_the_alert_allows_is_kept(line: str) -> None:
    assert cli.filter_line(line) == line
    [kept] = alerts.alert_lines([line])
    if "gave up" in line:
        assert "https://" not in kept
        assert re.fullmatch(
            r"(player list|pro schedule): [a-z]+: gave up after 4 attempts \(last failure: .+\)",
            kept,
        )
    else:
        assert kept == line


@pytest.mark.parametrize("line", DROPPED)
def test_a_line_outside_the_alert_patterns_is_dropped_not_marked(line: str) -> None:
    assert alerts.alert_lines([line]) == ()


def test_no_pattern_holds_a_path_and_each_is_anchored_by_use() -> None:
    for pattern in alerts.ALERT_PATTERNS:
        assert "[^\\x00-\\x1f]+" not in pattern.pattern  # `cli._PATH`
        assert "_PATH" not in pattern.pattern
        assert not pattern.fullmatch(f"{pattern.pattern} league_id=1")


def test_the_give_up_line_comes_out_without_its_url_whatever_the_url_holds() -> None:
    line = f"player list: espn: gave up on {LEAGUE_URL} after 3 attempts (last failure: none)"
    assert cli.filter_line(line) == line
    assert alerts.alert_lines([line]) == (
        "player list: espn: gave up after 3 attempts (last failure: none)",
    )
    assert alerts.alert_lines(line + "\n" + COOKIE_LINE) == (
        "player list: espn: gave up after 3 attempts (last failure: none)",
        COOKIE_LINE,
    )


def test_a_tail_of_mixed_lines_yields_only_the_allowed_ones_in_order() -> None:
    tail = "\n".join(DROPPED + [SAMPLES[2], "x", SAMPLES[3]])
    assert alerts.alert_lines(tail) == (SAMPLES[2], SAMPLES[3])


# ---------------------------------------------------------------------- the key (R1.5)


def _key_file(tmp_path: Path, text: str) -> dict[str, str]:
    path = tmp_path / "key"
    path.write_text(text)
    return {alerts.PING_KEY_FILE_VARIABLE: str(path)}


def test_no_variable_means_no_key() -> None:
    assert alerts.ping_key(environ={}) is None
    assert alerts.ping_key(environ={alerts.PING_KEY_FILE_VARIABLE: ""}) is None


def test_the_key_is_read_from_the_named_file_trailing_newline_allowed(tmp_path: Path) -> None:
    assert alerts.ping_key(environ=_key_file(tmp_path, KEY + "\n")) == KEY
    assert alerts.ping_key(environ=_key_file(tmp_path, KEY)) == KEY


def test_the_environment_is_read_when_none_is_given(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(
        alerts.PING_KEY_FILE_VARIABLE, _key_file(tmp_path, KEY)[alerts.PING_KEY_FILE_VARIABLE]
    )
    assert alerts.ping_key() == KEY


@pytest.mark.parametrize(
    "text",
    [KEY + "\n" + KEY + "\n", KEY + "\nsecond", "", "\n", "bad key with spaces", KEY + "/x", "ké"],
)
def test_an_unreadable_key_file_raises_without_its_content(tmp_path: Path, text: str) -> None:
    with pytest.raises(alerts.PingKeyUnreadable) as caught:
        alerts.ping_key(environ=_key_file(tmp_path, text))
    message = str(caught.value)
    assert alerts.PING_KEY_FILE_VARIABLE in message
    assert KEY not in message
    assert text.strip() not in message or text.strip() == ""


def test_a_missing_key_file_raises(tmp_path: Path) -> None:
    with pytest.raises(alerts.PingKeyUnreadable, match=alerts.PING_KEY_FILE_VARIABLE):
        alerts.ping_key(environ={alerts.PING_KEY_FILE_VARIABLE: str(tmp_path / "absent")})


def test_the_key_appears_in_no_log_line_report_outcome_or_message(
    tmp_path: Path, instance: DagsterInstance, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    key = alerts.ping_key(environ=_key_file(tmp_path, KEY + "\n"))
    assert key is not None
    result = _run(instance, _job(_fetch(AssetCheckSeverity.ERROR, False, _stderr(COOKIE_LINE))))
    seen: list[str] = []

    def opener(request: Any, timeout: float) -> Any:
        seen.append(request.full_url)
        raise urllib.error.URLError(request.full_url)

    sent = alerts.send(
        "front-office-daily", alerts.report(result), True, key, opener=opener, sleep=Sleeper()
    )
    assert seen  # the key did reach the URL, the one place it belongs
    events = [
        str(record.event_log_entry.user_message)
        for record in instance.get_records_for_run(result.run_id).records
    ]
    everything = [repr(result), alerts.report(result), sent, caplog.text, *events]
    assert not any(KEY in text for text in everything)
    with pytest.raises(alerts.PingKeyUnreadable) as caught:
        alerts.ping_key(environ=_key_file(tmp_path, KEY + "\n" + KEY))
    assert KEY not in str(caught.value) and KEY not in repr(caught.value)


# ----------------------------------------------------------------------- send (R2.5)


class Response:
    def __init__(self, status: int) -> None:
        self.status = status

    def __enter__(self) -> "Response":
        return self

    def __exit__(self, *exc: object) -> None:
        return None


class Opener:
    """A fake `urlopen`: answers from a script, one item per try (a status or an exception)."""

    def __init__(self, *script: int | Exception) -> None:
        self.script = list(script)
        self.requests: list[Any] = []
        self.timeouts: list[float] = []

    def __call__(self, request: Any, timeout: float) -> Response:
        self.requests.append(request)
        self.timeouts.append(timeout)
        step = self.script.pop(0)
        if isinstance(step, Exception):
            raise step
        if step != 200:
            raise urllib.error.HTTPError(request.full_url, step, "x", None, io.BytesIO(b""))  # type: ignore[arg-type]
        return Response(step)


class Sleeper:
    """A fake `time.sleep` that records the pauses instead of taking them."""

    def __init__(self) -> None:
        self.pauses: list[float] = []

    def __call__(self, seconds: float) -> None:
        self.pauses.append(seconds)


def test_a_200_is_sent_once_to_the_plain_url_with_the_body() -> None:
    opener, sleeper = Opener(200), Sleeper()
    got = alerts.send("front-office-daily", "héllo", False, KEY, opener=opener, sleep=sleeper)
    assert got == "sent"
    assert sleeper.pauses == []  # no pause after a success
    [request] = opener.requests
    assert request.full_url == f"https://hc-ping.com/{KEY}/front-office-daily"
    assert request.get_method() == "POST"
    assert request.data == "héllo".encode()
    assert request.get_header("Content-type") == "text/plain; charset=utf-8"
    assert opener.timeouts == [10]


def test_a_failed_run_pings_the_fail_url() -> None:
    opener = Opener(200)
    alerts.send("front-office-idmap", "b", True, KEY, opener=opener)
    assert opener.requests[0].full_url == f"https://hc-ping.com/{KEY}/front-office-idmap/fail"


def test_a_404_is_retried_and_reported_with_its_code() -> None:
    opener, sleeper = Opener(404, 404, 404), Sleeper()
    got = alerts.send("s", "b", False, KEY, opener=opener, sleep=sleeper)
    assert sleeper.pauses == [alerts.PING_PAUSE_SECONDS] * 2  # between tries, not after the last
    assert got == "not sent: HTTP 404"
    assert len(opener.requests) == 3
    assert KEY not in got


def test_a_429_then_a_200_is_sent_on_the_second_try() -> None:
    opener, sleeper = Opener(429, 200), Sleeper()
    assert alerts.send("s", "b", False, KEY, opener=opener, sleep=sleeper) == "sent"
    assert sleeper.pauses == [alerts.PING_PAUSE_SECONDS]
    assert len(opener.requests) == 2


def test_three_timeouts_give_up_without_raising_and_without_the_url() -> None:
    opener = Opener(TimeoutError(KEY), TimeoutError(KEY), TimeoutError(KEY))
    sleeper = Sleeper()
    got = alerts.send("s", "b", True, KEY, opener=opener, sleep=sleeper)
    assert len(sleeper.pauses) == 2
    assert got == "not sent: TimeoutError"
    assert len(opener.requests) == 3
    assert KEY not in got and "hc-ping" not in got


def test_a_url_error_is_named_by_its_class_only() -> None:
    opener = Opener(*[urllib.error.URLError(f"https://hc-ping.com/{KEY}")] * 3)
    got = alerts.send("s", "b", False, KEY, opener=opener, sleep=Sleeper())
    assert got == "not sent: URLError"


def test_a_non_200_success_status_is_not_a_success() -> None:
    class Odd(Opener):
        def __call__(self, request: Any, timeout: float) -> Response:
            self.requests.append(request)
            return Response(204)

    opener = Odd()
    got = alerts.send("s", "b", False, KEY, opener=opener, sleep=Sleeper())
    assert got == "not sent: HTTP 204"
    assert len(opener.requests) == 3
