"""The upload run against a fake BigQuery (spec 0140, R1, R3, R4, R6.3 to R6.7, R7).

The fake holds tables as lists of the rows each load job was given, read back from the job's
own file, so the run is exercised up to the client call. What BigQuery itself does with the
file is task 8's real run.
"""

from __future__ import annotations

import copy
import json
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from front_office import upload
from front_office.capture_structures import Column, read_structures
from front_office.landing import LandingZone
from front_office.upload import (
    KEY_COLUMNS,
    MANIFEST,
    UploadFailed,
    UploadRefused,
    upload_lock,
)

# Made-up ids in an account's form; no real account.
GUID = "{272E019C-48D5-42F3-B289-C48A1B163E19}"
TOPIC_ID = "5b1c0f3e-0a8e-4d2c-9e57-0c5f6a1b2d3e"
STRUCTURES = read_structures()


class FakeWarehouse:
    """Tables as (columns, rows). Each load job's rows are read from the file it was given."""

    def __init__(self, *, billing: bool = True) -> None:
        self.project = "test-project"
        self.billing = billing
        self.tables: dict[str, tuple[list[Column], list[dict[str, Any]]]] = {}
        self.jobs: list[tuple[str, str]] = []
        self.reads: list[str] = []
        self.fail_on: str | None = None  # the job raises
        self.short_on: str | None = None  # the job writes one row fewer, and says so
        self.lose_on: str | None = None  # the job writes one row fewer, and says it wrote all
        self.double_on: str | None = None  # the job writes its first row twice

    def billing_enabled(self) -> bool:
        self.reads.append("billing")
        return self.billing

    def columns(self, table: str) -> list[Column] | None:
        self.reads.append(f"columns {table}")
        return list(self.tables[table][0]) if table in self.tables else None

    def stored(self, table: str) -> list[tuple[str, ...]]:
        self.reads.append(f"stored {table}")
        rows = self.tables[table][1] if table in self.tables else []
        return [(*(row[name] for name in KEY_COLUMNS), row["file_path"]) for row in rows]

    def create(self, table: str, columns: list[Column]) -> None:
        self.jobs.append(("create", table))
        self.tables[table] = (list(columns), [])

    def load(self, table: str, columns: list[Column], rows: Path, *, replace: bool) -> int:
        self.jobs.append(("replace" if replace else "append", table))
        if table == self.fail_on:
            raise RuntimeError("the job failed")
        lines = [json.loads(line) for line in rows.read_text().splitlines()]
        said = len(lines)
        if table == self.short_on:
            lines, said = lines[:-1], said - 1
        if table == self.lose_on:
            lines = lines[:-1]
        if table == self.double_on:
            lines = [lines[0], *lines]
        if replace or table not in self.tables:
            self.tables[table] = (list(columns), lines)
        else:
            self.tables[table][1].extend(lines)
        return said

    def rows(self, table: str) -> Iterator[dict[str, Any]]:
        yield from copy.deepcopy(self.tables[table][1])

    def snapshot(self) -> dict[str, list[str]]:
        """Every table's rows as sorted JSON text, to compare two runs' results."""
        return {
            table: sorted(json.dumps(row, sort_keys=True) for row in rows)
            for table, (_, rows) in self.tables.items()
        }


def payloads(number: int = 0) -> dict[tuple[str, str], Any]:
    """One payload per uploaded endpoint but `espn/pro_schedule`, which has no captures, so
    that its table is created empty (R1.5). `number` makes a new capture of each."""
    return {
        ("espn", "teams"): {
            "id": 111,
            "seasonId": 2026,
            "members": [{"id": GUID, "firstName": "A", "lastName": "Member"}],
            "teams": [{"id": 1, "abbrev": "T", "owners": [GUID], "primaryOwner": GUID}],
        },
        ("espn", "transactions"): {
            "topics": [
                {
                    "id": TOPIC_ID,
                    "date": 1,
                    "author": GUID,
                    "messages": [{"id": "m-1", "author": GUID, "messageTypeId": 178}],
                }
            ]
        },
        ("espn", "roster"): {
            "id": 111,
            "seasonId": 2026,
            "members": [{"displayName": "A Member"}],
            "teams": [
                {
                    "id": 1,
                    "roster": {
                        "entries": [
                            {
                                "playerId": 5 + number,
                                "playerPoolEntry": {
                                    "player": {
                                        "fullName": "Ball Player",
                                        "firstName": "Ball",
                                        "stats": [{"scoringPeriodId": 1, "stats": {"20": 1.5}}],
                                    }
                                },
                            }
                        ]
                    },
                }
            ],
        },
        ("espn", "matchup_days"): {
            "id": 111,
            "seasonId": 2026,
            "scoringPeriodId": 1,
            "teams": [{"owners": [GUID]}],
            "schedule": [
                {
                    "id": 1,
                    "matchupPeriodId": 1,
                    "home": {
                        "teamId": 1,
                        "rosterForCurrentScoringPeriod": {"entries": [{"lineupSlotId": 0}]},
                    },
                    "away": {},
                }
            ],
        },
        ("mlb", "boxscore"): {
            "gamePk": 1 + number,
            "teams": {
                "home": {
                    "team": {"id": 1},
                    "players": {
                        "ID1": {"person": {"id": 1}, "stats": {"batting": {"hits": 1}}},
                        "ID2": {"person": {"id": 2}, "seasonStats": {"batting": {}}},
                    },
                },
                "away": {"team": {"id": 2}, "players": {}},
            },
        },
        ("mlb", "schedule"): {"dates": [{"games": [{"gamePk": 1 + number}]}]},
        ("mlb", "players"): {"people": [{"id": 1, "firstName": "Ball", "lastName": "Player"}]},
        ("espn", "matchups"): {"schedule": [{"id": number}]},
        ("espn", "settings"): {"settings": {"name": "x"}},
        ("idmap", "player_id_map"): {"rows": [number]},
    }


def land(
    zone: LandingZone,
    found: dict[tuple[str, str], Any],
    *,
    stamp: str = "20260926T162300Z",
    season: int = 2026,
) -> None:
    for (source, endpoint), payload in found.items():
        zone.write(
            source=source,
            endpoint=endpoint,
            partitions={"season": season},
            name=f"fetched_at={stamp}",
            payload=payload,
            request={"url": f"https://x.test/{endpoint}", "params": {"season": season}},
            fetched_at=stamp,
        )


@pytest.fixture
def zone(tmp_path: Path) -> LandingZone:
    zone = LandingZone(tmp_path / "raw")
    land(zone, payloads())
    return zone


def run(zone: LandingZone, warehouse: FakeWarehouse | None, **options: Any) -> list[str]:
    said: list[str] = []
    upload.upload(
        zone,
        warehouse,
        work_dir=zone.root.parent / "work",
        structures=STRUCTURES,
        say=said.append,
        **options,
    )
    return said


def rows_of(warehouse: FakeWarehouse, table: str) -> list[dict[str, Any]]:
    return warehouse.tables[table][1]


# -- a first upload, and a second ------------------------------------------------------------


def test_a_first_upload_creates_every_table_and_appends_the_manifest_last(
    zone: LandingZone,
) -> None:
    """Catches a table missing for an endpoint with no captures (its view would fail, R1.5),
    and a manifest appended before the table it names (R3.4)."""
    warehouse = FakeWarehouse()
    run(zone, warehouse)
    tables = {upload.table_name(pair) for pair in upload.UPLOADED} | {MANIFEST}
    assert {table for kind, table in warehouse.jobs if kind == "create"} == tables
    assert rows_of(warehouse, "espn_pro_schedule") == []
    appended = [table for kind, table in warehouse.jobs if kind == "append"]
    assert appended[-1] == MANIFEST
    assert sorted(appended[:-1]) == sorted(tables - {MANIFEST, "espn_pro_schedule"})
    assert len(rows_of(warehouse, MANIFEST)) == 10


def test_a_typed_endpoint_goes_up_as_its_declared_structure(zone: LandingZone) -> None:
    """Catches a heavy endpoint sent whole or as JSON text, a map not as key-value rows, the
    league id not as text, and an undeclared field going up (R1.2, R5.2, R5.4)."""
    warehouse = FakeWarehouse()
    run(zone, warehouse)
    (box,) = rows_of(warehouse, "mlb_boxscore")
    assert "payload" not in box and "gamePk" not in box
    home = box["teams"]["home"]
    assert [entry["key"] for entry in home["players"]] == ["ID1", "ID2"]
    assert home["players"][1]["value"] == {
        "person": {"id": 2},
        "position": None,
        "battingOrder": None,
        "gameStatus": None,
        "stats": None,
    }
    assert box["teams"]["away"]["players"] == []
    (roster,) = rows_of(warehouse, "espn_roster")
    assert roster["id"] == "111"
    assert "members" not in roster
    player = roster["teams"][0]["roster"]["entries"][0]["playerPoolEntry"]["player"]
    assert "firstName" not in player
    assert player["stats"][0]["stats"] == [{"key": "20", "value": 1.5}]
    assert set(box) == {
        column.name for column in upload.table_columns(("mlb", "boxscore"), STRUCTURES)
    }


def test_a_matchup_day_is_projected_before_its_structure_so_the_marker_is_empty(
    zone: LandingZone,
) -> None:
    """Catches the roster inside the marker going up: the structure keeps the marker as JSON,
    so only the projection empties it (R1.6, ADR 0061)."""
    warehouse = FakeWarehouse()
    run(zone, warehouse)
    (day,) = rows_of(warehouse, "espn_matchup_days")
    assert day["schedule"][0]["home"]["rosterForCurrentScoringPeriod"] == {}
    assert day["schedule"][0]["away"] is None
    assert day["id"] == "111"


def test_a_json_endpoint_goes_up_as_a_payload_and_teams_as_its_projection(
    zone: LandingZone,
) -> None:
    """Catches a small endpoint typed, or a member's data in the teams payload (R1.3)."""
    warehouse = FakeWarehouse()
    run(zone, warehouse)
    (teams,) = rows_of(warehouse, "espn_teams")
    assert teams["payload"] == {"id": 111, "seasonId": 2026, "teams": [{"id": 1, "abbrev": "T"}]}
    (settings,) = rows_of(warehouse, "espn_settings")
    assert settings["payload"] == {"settings": {"name": "x"}}
    assert settings["partitions"] == {"season": 2026}


def test_a_second_upload_with_nothing_new_runs_no_job(zone: LandingZone) -> None:
    """Catches a rerun that sends again (R3.1, and the expected values' last row)."""
    warehouse = FakeWarehouse()
    run(zone, warehouse)
    jobs = list(warehouse.jobs)
    said = run(zone, warehouse)
    assert warehouse.jobs == jobs
    assert "nothing to send" in said


def test_a_new_capture_is_appended_alone(zone: LandingZone) -> None:
    """Catches an append that resends what a table holds."""
    warehouse = FakeWarehouse()
    run(zone, warehouse)
    jobs = len(warehouse.jobs)
    land(zone, {("mlb", "boxscore"): payloads(1)[("mlb", "boxscore")]}, stamp="20260927T162300Z")
    run(zone, warehouse)
    assert warehouse.jobs[jobs:] == [("append", "mlb_boxscore"), ("append", MANIFEST)]
    assert len(rows_of(warehouse, "mlb_boxscore")) == 2
    assert len(rows_of(warehouse, MANIFEST)) == 11


# -- stopping partway -------------------------------------------------------------------------


@pytest.mark.parametrize("failing", ["espn_matchup_days", "mlb_boxscore", "mlb_schedule", MANIFEST])
def test_a_run_stopped_at_any_job_ends_as_a_whole_run_does_when_run_again(
    zone: LandingZone, failing: str
) -> None:
    """Catches a duplicate or a lost capture after a crash (R3.3), and a manifest that names a
    capture its endpoint's table lacks (R3.4)."""
    whole = FakeWarehouse()
    run(zone, whole)
    warehouse = FakeWarehouse()
    warehouse.fail_on = failing
    with pytest.raises(UploadFailed, match="the load job failed"):
        run(zone, warehouse)
    named = {(row["source"], row["endpoint"]) for row in rows_of(warehouse, MANIFEST)}
    held = {
        (row["source"], row["endpoint"])
        for table, (_, rows) in warehouse.tables.items()
        if table != MANIFEST
        for row in rows
    }
    assert named <= held
    if failing != MANIFEST:
        assert tuple(failing.split("_", 1)) not in named
    warehouse.fail_on = None
    run(zone, warehouse)
    assert warehouse.snapshot() == whole.snapshot()


# -- the lock ----------------------------------------------------------------------------------


def test_a_second_upload_stops_on_the_lock_having_read_and_sent_nothing(zone: LandingZone) -> None:
    """Catches two runs appending the same rows (R3.8)."""
    warehouse = FakeWarehouse()
    with upload_lock(zone), pytest.raises(UploadRefused, match="another upload holds"):
        run(zone, warehouse)
    assert warehouse.reads == [] and warehouse.jobs == []


def test_a_fetch_holding_the_writer_lock_does_not_block_an_upload(zone: LandingZone) -> None:
    """Catches the upload taking the landing zone's writer lock, which would stop fetching."""
    warehouse = FakeWarehouse()
    with zone.writer_lock():
        run(zone, warehouse)
    assert ("append", MANIFEST) in warehouse.jobs


# -- refusals before anything is sent -----------------------------------------------------------


def test_two_files_with_one_key_in_the_zone_are_refused_naming_both(zone: LandingZone) -> None:
    """Catches a silent first-wins (R3.5, ADR 0011): two partitions, one request and stamp."""
    payload = payloads()[("espn", "settings")]
    zone.write(
        source="espn",
        endpoint="settings",
        partitions={"season": 2026, "copy": 2},
        name="fetched_at=20260926T162300Z",
        payload=payload,
        request={"url": "https://x.test/settings", "params": {"season": 2026}},
        fetched_at="20260926T162300Z",
    )
    warehouse = FakeWarehouse()
    with pytest.raises(UploadRefused) as refused:
        run(zone, warehouse)
    assert "season=2026/fetched_at" in str(refused.value)
    assert "copy=2/fetched_at" in str(refused.value)
    assert warehouse.jobs == [] and warehouse.reads == []


def test_a_key_stored_with_another_file_is_refused_naming_both(zone: LandingZone) -> None:
    """Catches a capture whose stored row came from a different file (R3.5)."""
    warehouse = FakeWarehouse()
    run(zone, warehouse)
    row = rows_of(warehouse, "espn_settings")[0]
    row["file_path"] = "espn/settings/season=2026/other/payload.json"
    jobs = list(warehouse.jobs)
    with pytest.raises(UploadRefused) as refused:
        run(zone, warehouse)
    assert "other/payload.json" in str(refused.value)
    assert "fetched_at=20260926T162300Z/payload.json" in str(refused.value)
    assert warehouse.jobs == jobs


def test_a_stored_row_the_zone_lacks_is_refused(zone: LandingZone) -> None:
    warehouse = FakeWarehouse()
    run(zone, warehouse)
    extra = dict(rows_of(warehouse, "espn_settings")[0], fetched_at="20250101T000000Z")
    rows_of(warehouse, "espn_settings").append(extra)
    with pytest.raises(UploadRefused, match="has not committed"):
        run(zone, warehouse)


def test_a_malformed_stamp_is_refused(zone: LandingZone) -> None:
    """Catches a stamp dbt cannot parse reaching BigQuery (R3.6)."""
    land(zone, {("espn", "settings"): {"x": 1}}, stamp="20260926T1623Z")
    warehouse = FakeWarehouse()
    with pytest.raises(UploadRefused, match="has a fetched_at not of the form"):
        run(zone, warehouse)
    assert warehouse.jobs == []


def test_a_payload_that_does_not_fit_is_refused_naming_the_capture_and_path(
    zone: LandingZone,
) -> None:
    """Catches a capture's rows lost to a default, or the value in the message (R5.3)."""
    box = payloads(1)[("mlb", "boxscore")]
    box["teams"]["home"]["team"]["id"] = "A Member"
    land(zone, {("mlb", "boxscore"): box}, stamp="20260927T162300Z")
    warehouse = FakeWarehouse()
    with pytest.raises(UploadRefused) as refused:
        run(zone, warehouse)
    message = str(refused.value)
    assert "fetched_at=20260927T162300Z" in message and "$.teams.home.team.id" in message
    assert "A Member" not in message
    assert warehouse.jobs == []


def test_a_forbidden_key_as_a_maps_key_is_a_hit(zone: LandingZone) -> None:
    """Catches the check reading the row after a map's keys became `key` values (R6.3)."""
    roster = payloads(1)[("espn", "roster")]
    player = roster["teams"][0]["roster"]["entries"][0]["playerPoolEntry"]["player"]
    player["stats"][0]["stats"] = {"displayName": 1}
    land(zone, {("espn", "roster"): roster}, stamp="20260927T162300Z")
    warehouse = FakeWarehouse()
    with pytest.raises(UploadRefused, match="key displayName at"):
        run(zone, warehouse)
    assert warehouse.jobs == []


def test_a_project_is_required_unless_a_dry_run(zone: LandingZone) -> None:
    with pytest.raises(UploadRefused, match="--project is required"):
        run(zone, None)


def test_no_billing_means_no_job(zone: LandingZone) -> None:
    """Catches a job run on a project with no billing (R6.5)."""
    warehouse = FakeWarehouse(billing=False)
    with pytest.raises(UploadRefused, match="billing is not enabled"):
        run(zone, warehouse)
    assert warehouse.jobs == []


def test_a_dry_run_with_a_project_reads_and_sends_nothing(zone: LandingZone) -> None:
    warehouse = FakeWarehouse()
    said = run(zone, warehouse, dry_run=True)
    assert warehouse.jobs == []
    assert "raw.mlb_boxscore: 1 committed, 0 stored, 1 to send" in said
    assert "dry run: nothing sent" in said


def test_a_dry_run_without_a_project_imports_no_google_and_says_what_it_did_not_check(
    zone: LandingZone, tmp_path: Path
) -> None:
    """Catches a job by accident, a dry run that needs the bigquery group, and the upload
    reading an ESPN credential (R6.5, R6.6, R7.1): run in a fresh interpreter."""
    script = (
        "import sys\n"
        "from pathlib import Path\n"
        "from front_office import upload\n"
        "from front_office.landing import LandingZone\n"
        f"upload.upload(LandingZone(Path({str(zone.root)!r})), None, dry_run=True,\n"
        f"              work_dir=Path({str(tmp_path / 'work')!r}))\n"
        "credentials = 'front_office.espn.client'\n"
        "loaded = [m for m in sys.modules if m.startswith('google') or m == credentials]\n"
        "print('loaded:', loaded)\n"
    )
    done = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, check=True
    )
    assert "loaded: []" in done.stdout
    assert "the remote checks (schemas, stored keys) did not run" in done.stdout
    assert "dry run: nothing sent" in done.stdout


# -- schema, rebuild ---------------------------------------------------------------------------


def test_a_changed_structure_refuses_the_append_and_names_the_rebuild(zone: LandingZone) -> None:
    """Catches rows of two shapes in one table (R4.1)."""
    warehouse = FakeWarehouse()
    run(zone, warehouse)
    columns, rows = warehouse.tables["mlb_boxscore"]
    warehouse.tables["mlb_boxscore"] = (columns[:-1], rows)
    land(zone, {("mlb", "boxscore"): payloads(1)[("mlb", "boxscore")]}, stamp="20260927T162300Z")
    jobs = list(warehouse.jobs)
    with pytest.raises(UploadRefused) as refused:
        run(zone, warehouse)
    assert "front-office upload --project test-project --rebuild mlb/boxscore" in str(refused.value)
    assert warehouse.jobs == jobs


def test_a_rebuild_replaces_the_table_in_one_job_from_every_capture(zone: LandingZone) -> None:
    """Catches a half-replaced table, or a rebuild that duplicates the manifest (R4.2)."""
    warehouse = FakeWarehouse()
    run(zone, warehouse)
    columns, rows = warehouse.tables["mlb_boxscore"]
    warehouse.tables["mlb_boxscore"] = (columns[:-1], rows)
    land(zone, {("mlb", "boxscore"): payloads(1)[("mlb", "boxscore")]}, stamp="20260927T162300Z")
    jobs = len(warehouse.jobs)
    run(zone, warehouse, rebuild=("mlb", "boxscore"))
    assert warehouse.jobs[jobs:] == [("replace", "mlb_boxscore"), ("append", MANIFEST)]
    assert warehouse.tables["mlb_boxscore"][0] == upload.table_columns(
        ("mlb", "boxscore"), STRUCTURES
    )
    assert len(rows_of(warehouse, "mlb_boxscore")) == 2
    assert len(rows_of(warehouse, MANIFEST)) == 11


# -- the checks after a run, and --verify -----------------------------------------------------


def test_a_job_that_wrote_fewer_rows_than_sent_fails_and_the_manifest_waits(
    zone: LandingZone,
) -> None:
    """Catches a short load that looks fine (R4.3)."""
    warehouse = FakeWarehouse()
    warehouse.short_on = "espn_matchups"
    with pytest.raises(UploadFailed, match="wrote 0 rows, not 1"):
        run(zone, warehouse)
    assert MANIFEST not in {table for kind, table in warehouse.jobs if kind == "append"}


def test_a_row_lost_by_a_job_that_said_it_wrote_all_fails_the_check(zone: LandingZone) -> None:
    """Catches a file_path set that differs from the zone's though the count agreed (R4.3)."""
    warehouse = FakeWarehouse()
    warehouse.lose_on = "espn_matchups"
    with pytest.raises(
        UploadFailed, match="espn_matchups, espn/matchups: 1 committed captures missing"
    ):
        run(zone, warehouse)


def test_a_key_stored_twice_with_one_path_fails_the_check(zone: LandingZone) -> None:
    """Catches what a set of file paths does not see: one key appended twice (R4.3)."""
    warehouse = FakeWarehouse()
    warehouse.double_on = "espn_matchups"
    with pytest.raises(UploadFailed, match="1 keys stored more than once"):
        run(zone, warehouse)


def test_verify_passes_on_what_was_sent_and_fails_on_a_changed_value(zone: LandingZone) -> None:
    """Catches a value altered on the way (R4.4)."""
    warehouse = FakeWarehouse()
    run(zone, warehouse, verify=True)
    said = run(zone, warehouse, verify=True)
    assert "verify: every row of every table equals what would be sent" in said
    rows_of(warehouse, "mlb_boxscore")[0]["teams"]["home"]["team"]["id"] = 9
    with pytest.raises(UploadFailed, match="raw.mlb_boxscore does not equal"):
        run(zone, warehouse, verify=True)


def test_verify_takes_a_whole_float_for_the_integer_it_was_sent_as(zone: LandingZone) -> None:
    warehouse = FakeWarehouse()
    run(zone, warehouse)
    rows_of(warehouse, "mlb_boxscore")[0]["teams"]["home"]["team"]["id"] = 1.0
    run(zone, warehouse, verify=True)


# -- a hit on a row already sent ---------------------------------------------------------------


def test_an_account_first_seen_later_that_equals_a_sent_id_stops_every_run(
    zone: LandingZone,
) -> None:
    """Catches the cross-check reading only new transactions (R6.4), and a run that goes on
    after finding a member's id already in BigQuery (R6.7)."""
    warehouse = FakeWarehouse()
    run(zone, warehouse)
    teams = payloads()[("espn", "teams")]
    teams["members"].append({"id": "{" + TOPIC_ID.upper() + "}"})
    land(zone, {("espn", "teams"): teams}, stamp="20260927T162300Z")
    jobs = list(warehouse.jobs)
    for _ in range(2):
        with pytest.raises(UploadRefused) as refused:
            run(zone, warehouse)
        message = str(refused.value)
        assert "transaction id equals an account id at $.topics[0].id" in message
        assert "in raw.espn_transactions, capture espn/transactions/season=2026/" in message
        assert "already uploaded" in message and "--rebuild espn/transactions" in message
        assert TOPIC_ID not in message.lower()
        assert warehouse.jobs == jobs


def test_a_matchup_day_whose_marker_holds_a_roster_is_refused(
    zone: LandingZone, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Catches the projection skipped for matchup days, which check() cannot see (task 1)."""
    monkeypatch.setitem(upload.PROJECTIONS, ("espn", "matchup_days"), lambda payload: payload)
    warehouse = FakeWarehouse()
    with pytest.raises(UploadRefused, match="not what its projection would produce"):
        run(zone, warehouse)
    assert warehouse.jobs == []
