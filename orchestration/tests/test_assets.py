"""R2.1, R2.2, R2.4, R3.2, R3.3, R3.6: the hand-written assets, with `cli.run` faked.

Each test materializes the real assets in process; only the subprocess is faked, and a stand-in
for a dbt asset (`staging/a_model`, downstream of `raw_in_warehouse` as every dbt model with a
source is) records whether the build would have run.
"""

import subprocess
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest
from dagster import (
    AssetCheckSeverity,
    AssetKey,
    DagsterInstance,
    ExecuteInProcessResult,
    asset,
    materialize,
)

from front_office_pipeline import assets, cli, season

GUID = "{272E019C-48D5-42F3-B289-C48A1B163E19}"
SEVERAL = [
    assets.mlb_captures,
    assets.espn_captures,
    assets.espn_matchup_days,
    assets.raw_in_warehouse,
]


class Recorder:
    """A stand-in for `cli.run` that records each call and answers by command."""

    def __init__(self, exits: dict[str, int] | None = None) -> None:
        self.exits = exits or {}
        self.calls: list[tuple[list[str], tuple[str, ...]]] = []

    def __call__(
        self, args: Sequence[str], context: object, *, prefix: Sequence[str] = cli.FRONT_OFFICE
    ) -> cli.Result:
        self.calls.append((list(args), tuple(prefix)))
        code = self.exits.get(args[0] if args[0] != "backfill" else f"backfill {args[1]}", 0)
        return cli.Result(code, ("ESPN returned 401: cookies expired",) if code else ())

    @property
    def commands(self) -> list[list[str]]:
        return [args for args, _ in self.calls]


@pytest.fixture
def recorder(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Recorder:
    monkeypatch.setenv("FO_LANDING_ROOT", str(tmp_path / "raw"))
    monkeypatch.setenv("FO_DUCKDB_PATH", str(tmp_path / "w.duckdb"))
    monkeypatch.setenv("FO_SEASON", "2026")
    monkeypatch.delenv("FO_WAREHOUSE", raising=False)
    monkeypatch.delenv("FO_BQ_PROJECT", raising=False)
    fake = Recorder()
    monkeypatch.setattr(cli, "run", fake)
    monkeypatch.setattr(season, "is_over", lambda root, year: False)
    return fake


def build_ran() -> tuple[Any, list[str]]:
    ran: list[str] = []

    @asset(key=["staging", "a_model"], deps=["raw_in_warehouse"])
    def a_model() -> None:
        ran.append("staging/a_model")

    return a_model, ran


def run(
    selection: list[Any], instance: DagsterInstance | None = None
) -> tuple[ExecuteInProcessResult, list[str]]:
    model, ran = build_ran()
    result = materialize([*selection, model], raise_on_error=False, instance=instance)
    return result, ran


def checks(result: ExecuteInProcessResult) -> dict[str, Any]:
    return {e.asset_key.to_user_string(): e for e in result.get_asset_check_evaluations()}


def materialized(result: ExecuteInProcessResult) -> set[str]:
    return {
        e.asset_key.to_user_string()
        for e in result.get_asset_materialization_events()
        if e.asset_key
    }


def test_a_failed_fetch_fails_its_check_and_the_build_still_runs(recorder: Recorder) -> None:
    """R2.1. Catches a failed fetch that stops upload and build (the other feed left stale)."""
    recorder.exits = {"backfill mlb": 1, "backfill espn": 1}
    result, ran = run(SEVERAL)
    assert {"mlb_captures", "espn_captures", "raw_in_warehouse"} <= materialized(result)
    evaluated = checks(result)
    for key in ("mlb_captures", "espn_captures"):
        check = evaluated[key]
        assert check.check_name == "fetch_complete"
        assert check.passed is False
        assert check.severity == AssetCheckSeverity.ERROR
        assert check.metadata["exit_code"].value == 1
        assert "cookies expired" in check.metadata["stderr_tail"].value
    assert ran == ["staging/a_model"]
    assert [args[0] for args in recorder.commands][-1] == "load"


def test_a_passing_fetch_passes_its_check(recorder: Recorder) -> None:
    """Catches a check that fails regardless of the exit code."""
    result, _ = run(SEVERAL)
    assert result.success
    evaluated = checks(result)
    assert evaluated["mlb_captures"].passed and evaluated["espn_captures"].passed


def test_the_fetch_checks_are_not_blocking() -> None:
    """R2.1. Catches `blocking=True`, which would skip upload and build after a failed fetch."""
    for definition in (
        assets.mlb_captures,
        assets.espn_captures,
        assets.espn_matchup_days,
        assets.idmap_capture,
    ):
        specs = list(definition.check_specs)
        assert [spec.name for spec in specs] == ["fetch_complete"]
        assert all(spec.blocking is False for spec in specs)


def test_a_failed_check_is_visible_on_the_instance(recorder: Recorder) -> None:
    """R2.3. Catches a failure that is not recorded where GraphQL reads it."""
    recorder.exits = {"backfill espn": 1}
    instance = DagsterInstance.ephemeral()
    run(SEVERAL, instance)
    records = instance.event_log_storage.get_asset_check_summary_records(
        [check_key for definition in SEVERAL for check_key in definition.check_keys]
    )
    statuses = {
        key.asset_key.to_user_string(): r.last_check_execution_record for key, r in records.items()
    }
    espn, mlb = statuses["espn_captures"], statuses["mlb_captures"]
    assert espn is not None and mlb is not None
    assert espn.status.value == "FAILED"
    assert mlb.status.value == "SUCCEEDED"


def test_the_commands_carry_the_season_and_the_one_landing_root(
    recorder: Recorder, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R3.1, R3.6. Catches a CLI, a load and the gate reading different landing zones."""
    root = str(tmp_path / "raw")
    gate: list[tuple[Path, int]] = []

    def is_over(landing_root: Path, year: int) -> bool:
        gate.append((landing_root, year))
        return True

    monkeypatch.setattr(season, "is_over", is_over)
    monkeypatch.setenv("FO_SEASON", "2025")
    run(SEVERAL)
    assert recorder.commands == [
        ["backfill", "mlb", "--season", "2025", "--raw-root", root],
        ["backfill", "espn", "--season", "2025", "--raw-root", root],
        ["backfill", "espn", "--season", "2025", "--only", "matchup-days", "--raw-root", root],
        ["load", "--raw-root", root, "--db", str(tmp_path / "w.duckdb")],
    ]
    assert gate == [(Path(root), 2025)]


def test_matchup_days_are_skipped_without_a_command_while_the_season_runs(
    recorder: Recorder,
) -> None:
    """R3.3. Catches matchup-day requests for scoring periods that have not happened."""
    result, _ = run(SEVERAL)
    assert recorder.commands[1][:2] == ["backfill", "espn"]
    assert not any("matchup-days" in args for args in recorder.commands)
    events = [
        e
        for e in result.get_asset_materialization_events()
        if e.asset_key == AssetKey("espn_matchup_days")
    ]
    assert len(events) == 1
    assert events[0].materialization.metadata["skipped"].value is True
    assert checks(result)["espn_matchup_days"].passed


def test_idmap_has_its_own_command(recorder: Recorder, tmp_path: Path) -> None:
    result = materialize([assets.idmap_capture], raise_on_error=False)
    assert result.success
    assert recorder.commands == [["backfill", "idmap", "--raw-root", str(tmp_path / "raw")]]


def test_bigquery_uploads_through_the_bigquery_group(
    recorder: Recorder, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R3.2. Catches an upload run without the BigQuery dependencies or without the project."""
    monkeypatch.setenv("FO_WAREHOUSE", "bigquery")
    monkeypatch.setenv("FO_BQ_PROJECT", "my-project")
    run([assets.raw_in_warehouse])
    assert recorder.calls == [
        (
            ["upload", "--project", "my-project", "--raw-root", str(tmp_path / "raw")],
            ("uv", "run", "--group", "bigquery", "front-office"),
        )
    ]


def test_a_failed_upload_fails_the_asset_and_skips_the_build(
    recorder: Recorder, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R2.2. Catches a build on top of a failed upload."""
    monkeypatch.setenv("FO_WAREHOUSE", "bigquery")
    monkeypatch.setenv("FO_BQ_PROJECT", "my-project")
    recorder.exits = {"upload": 1}
    result, ran = run(SEVERAL)
    assert not result.success
    assert "raw_in_warehouse" not in materialized(result)
    assert ran == []


def test_a_failed_load_fails_the_asset_and_skips_the_build(recorder: Recorder) -> None:
    """R2.2, DuckDB. Catches a build on top of a failed load."""
    recorder.exits = {"load": 1}
    result, ran = run(SEVERAL)
    assert not result.success
    assert ran == []


def test_bigquery_without_a_project_fails_before_any_command(
    recorder: Recorder, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R3.2. Catches a fetch that lands data, then an upload into no project."""
    monkeypatch.setenv("FO_WAREHOUSE", "bigquery")
    result, ran = run(SEVERAL)
    assert not result.success
    assert recorder.calls == []
    assert ran == []


def test_dagster_records_no_credential_guid_or_member_key_from_a_command(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """R2.4. Catches a cookie, an account id or a member key in the events, the logs or the
    check's metadata that the SQLite instance keeps. The subprocess is faked, the filter is not."""
    monkeypatch.setenv("FO_LANDING_ROOT", str(tmp_path / "raw"))
    monkeypatch.setenv("FO_SEASON", "2026")
    stdout = f"boxscores: fetched=1 skipped=0 failed=0\nESPN_S2=abc123secret\n{GUID}\n"
    stderr = (
        "ESPN returned 401: cookies expired — refresh ESPN_S2/SWID in .env "
        "from a logged-in browser session\n"
        f'{{"members": [{{"displayName": "Someone", "id": "{GUID}"}}]}}\n'
        "ESPN_S2=abc123secret\nauthor: Someone\n"
    )

    def fake_run(command: Sequence[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(command, 1, stdout, stderr)

    monkeypatch.setattr("front_office_pipeline.cli.subprocess.run", fake_run)
    instance = DagsterInstance.ephemeral()
    result = materialize([assets.mlb_captures], instance=instance, raise_on_error=False)
    everything = repr(
        [
            [str(event) for event in result.all_events],
            [str(entry) for entry in instance.all_logs(result.run_id)],
            [str(e.metadata) for e in result.get_asset_check_evaluations()],
        ]
    )
    for forbidden in ("abc123secret", GUID, "Someone", "displayName", "members", "author"):
        assert forbidden not in everything
    evaluation = result.get_asset_check_evaluations()[0]
    assert evaluation.passed is False
    tail = str(evaluation.metadata["stderr_tail"].value)
    assert "cookies expired" in tail
    assert cli.WITHHELD in tail


def test_the_hand_written_asset_keys() -> None:
    """R1.2. Catches an asset renamed or dropped."""
    keys: set[AssetKey] = set()
    for definition in (*SEVERAL, assets.idmap_capture):
        keys |= set(definition.keys)
    assert {k.to_user_string() for k in keys} == {
        "mlb_captures",
        "espn_captures",
        "espn_matchup_days",
        "idmap_capture",
        "raw_in_warehouse",
    }


def test_the_fetches_run_in_the_declared_order() -> None:
    """R1.4. Catches steps that could run together (two writers of the landing zone)."""

    def deps(definition: Any) -> set[str]:
        return {
            key.to_user_string()
            for spec in definition.specs
            for key in (dep.asset_key for dep in spec.deps)
        }

    assert deps(assets.mlb_captures) == set()
    assert deps(assets.espn_captures) == {"mlb_captures"}
    assert deps(assets.espn_matchup_days) == {"espn_captures"}
    assert {"espn_matchup_days"} <= deps(assets.raw_in_warehouse)
