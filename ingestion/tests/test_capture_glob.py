"""fo_captures: a capture view reads committed payload files, and only the ones loaded.

Spec 0150, R2 and R3.2-R3.3 (ADRs 0066-0068). The macro is compiled by dbt itself, through
its Python API, against a landing root and a manifest built here, and the SQL it emits is
run on DuckDB. What each test catches:

- a glob that opens a capture still being written (`….tmp-<pid>/`) and fails on it (R2.1);
- a published file the loader has not recorded reaching a model (R2.2);
- a payload that does not parse passing silently, listed or not (R2.3);
- an endpoint with no captures failing the build instead of giving no rows (R2.4);
- partition levels of different depth within an endpoint breaking the read (R2.1);
- a whole-document read splitting a JSON array into rows (R3.3);
- a declared structure, map included, not giving its typed fields (R3.2).
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import duckdb
import pytest
from dbt.cli.main import dbtRunner

DBT_DIR = Path(__file__).resolve().parents[2] / "dbt"

ROSTER_STRUCTURE = (
    '{"id": "BIGINT", "teams": [{"id": "BIGINT", "roster": {"entries": '
    '[{"playerId": "BIGINT"}]}}], "stats": {"__map__": "DOUBLE"}}'
)


def _capture(root: Path, relative: str, payload: str) -> str:
    """Write a capture's payload (and a sidecar, as the writer does) under `root`."""
    directory = root / relative
    directory.mkdir(parents=True)
    (directory / "payload.json").write_text(payload)
    (directory / "meta.json").write_text(json.dumps({"fetched_at": directory.name}))
    return f"{relative}/payload.json"


@pytest.fixture(scope="module")
def landing(tmp_path_factory: pytest.TempPathFactory) -> Iterator[tuple[Path, Path]]:
    """A landing root holding every case, and a warehouse whose manifest lists some."""
    base = tmp_path_factory.mktemp("captures")
    root = base / "landing"
    listed: list[tuple[str, str, str]] = []

    def listed_capture(source: str, endpoint: str, relative: str, payload: str) -> None:
        listed.append((source, endpoint, _capture(root, relative, payload)))

    # R2.1: a published capture beside one being written, whose payload is cut short.
    listed_capture(
        "espn", "settings", "espn/settings/season=2026/fetched_at=20260101T000000Z", '{"id": 1}'
    )
    _capture(root, "espn/settings/season=2026/fetched_at=20260102T000000Z.tmp-123", '{"id": ')
    # R2.2: two published captures, only one of them loaded.
    listed_capture(
        "espn", "teams", "espn/teams/season=2026/fetched_at=20260101T000000Z", '{"id": 1}'
    )
    _capture(root, "espn/teams/season=2026/fetched_at=20260102T000000Z", '{"id": 2}')
    # R2.3: a payload that does not parse, listed, and another not listed.
    listed_capture(
        "mlb", "schedule", "mlb/schedule/season=2026/fetched_at=20260101T000000Z", '{"dates": ['
    )
    _capture(root, "mlb/players/season=2026/fetched_at=20260101T000000Z", '{"people": [')
    # R2.1: partition levels of two depths within one endpoint.
    listed_capture(
        "espn", "transactions", "espn/transactions/season=2026/fetched_at=20260101T000000Z", "{}"
    )
    listed_capture(
        "espn",
        "transactions",
        "espn/transactions/season=2026/offset=0/fetched_at=20260102T000000Z",
        "{}",
    )
    # R3.3: a document that is a JSON array.
    listed_capture(
        "idmap", "player_id_map", "idmap/player_id_map/fetched_at=20260101T000000Z", "[1, 2, 3]"
    )
    # R3.2: a declared structure, with a list of structs and a map.
    listed_capture(
        "espn",
        "roster",
        "espn/roster/season=2026/fetched_at=20260101T000000Z",
        json.dumps(
            {
                "id": 7,
                "teams": [{"id": 3, "roster": {"entries": [{"playerId": 11}, {"playerId": 12}]}}],
                "stats": {"20": 1.5, "21": 2.0},
                "ignored": "x" * 1000,
            }
        ),
    )
    # R2.4: espn/matchup_days has nothing at all.

    db = base / "warehouse.duckdb"
    con = duckdb.connect(str(db))
    con.execute(
        "create schema raw; create table raw.captures (source varchar, endpoint varchar, "
        "request_path varchar, request_key varchar, fetched_at varchar, partitions json, "
        "file_path varchar)"
    )
    con.executemany(
        "insert into raw.captures values (?, ?, '/p', 'k', ?, '{}', ?)",
        [(s, e, path.split("fetched_at=")[1].split("/")[0], path) for s, e, path in listed],
    )
    con.close()
    yield root, db


class CaptureReadFailed(Exception):
    """dbt ran the capture view's SQL and DuckDB refused it; the message is DuckDB's."""


def _rows(
    landing: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch, call: str, columns: str = "*"
) -> list[tuple]:
    """Compile `call` with dbt (target ci, pointed at this landing root) and run it there.

    dbt runs the SQL itself (`dbt show`): it holds the warehouse open in this process, so
    a second connection from the test would be refused.
    """
    root, db = landing
    monkeypatch.setenv("FO_CI_LANDING_ROOT", str(root))
    monkeypatch.setenv("FO_CI_DUCKDB_PATH", str(db))
    monkeypatch.setenv("DBT_PROFILES_DIR", str(DBT_DIR))
    monkeypatch.chdir(DBT_DIR)
    inline = f"select {columns} from ({{{{ {call} }}}}) as captures order by file_path"
    result = dbtRunner().invoke(
        ["show", "--target", "ci", "--quiet", "--limit", "-1", "--inline", inline]
    )
    if not result.success:
        failure = result.exception or result.result.results[0].message
        raise CaptureReadFailed(str(failure))
    table = result.result.results[0].agate_table
    return [tuple(row.values()) for row in table.rows]


def test_a_capture_being_written_is_never_opened(landing, monkeypatch):
    rows = _rows(landing, monkeypatch, "fo_captures('espn', 'settings')")
    assert [row[6] for row in rows] == [
        "espn/settings/season=2026/fetched_at=20260101T000000Z/payload.json"
    ]


def test_a_published_file_the_manifest_does_not_list_gives_no_row(landing, monkeypatch):
    rows = _rows(landing, monkeypatch, "fo_captures('espn', 'teams')")
    assert [json.loads(row[7])["id"] for row in rows] == [1]


@pytest.mark.parametrize("endpoint", ["schedule", "players"], ids=["listed", "not-listed"])
def test_a_payload_that_does_not_parse_fails_naming_its_file(landing, monkeypatch, endpoint):
    with pytest.raises(CaptureReadFailed, match=f"mlb/{endpoint}/season=2026"):
        _rows(landing, monkeypatch, f"fo_captures('mlb', '{endpoint}')")


def test_an_endpoint_with_no_captures_gives_no_rows_and_its_columns(landing, monkeypatch):
    assert _rows(landing, monkeypatch, "fo_captures('espn', 'matchup_days')") == []
    typed = _rows(
        landing, monkeypatch, f"fo_captures('espn', 'matchup_days', '{ROSTER_STRUCTURE}')"
    )
    assert typed == []


def test_partition_levels_of_two_depths_are_both_read(landing, monkeypatch):
    rows = _rows(landing, monkeypatch, "fo_captures('espn', 'transactions')")
    assert len(rows) == 2


def test_a_document_that_is_an_array_is_one_row(landing, monkeypatch):
    rows = _rows(landing, monkeypatch, "fo_captures('idmap', 'player_id_map')")
    assert len(rows) == 1
    assert json.loads(rows[0][7]) == [1, 2, 3]


def test_a_declared_structure_gives_its_typed_fields_and_drops_the_rest(landing, monkeypatch):
    call = f"fo_captures('espn', 'roster', '{ROSTER_STRUCTURE}')"
    assert len(_rows(landing, monkeypatch, call)[0]) == 7 + 3  # the manifest's, and three
    # dbt show gives nested values as JSON text, so each is read back from JSON here.
    columns = "id, to_json(teams)::varchar as teams, to_json(stats)::varchar as stats"
    [(league_id, teams, stats)] = _rows(landing, monkeypatch, call, columns)
    assert league_id == 7
    assert json.loads(teams) == [
        {"id": 3, "roster": {"entries": [{"playerId": 11}, {"playerId": 12}]}}
    ]
    assert json.loads(stats) == {"20": 1.5, "21": 2.0}


def test_a_landing_root_with_a_quote_in_its_path_is_read(tmp_path, monkeypatch):
    """Catches the root being put into the SQL unescaped: a path with a quote (a user's
    directory, "o'brien") would end the string literal and fail the view."""
    root = tmp_path / "o'brien" / "landing"
    path = _capture(root, "espn/settings/season=2026/fetched_at=20260101T000000Z", '{"id": 1}')
    db = tmp_path / "warehouse.duckdb"
    con = duckdb.connect(str(db))
    con.execute(
        "create schema raw; create table raw.captures (source varchar, endpoint varchar, "
        "request_path varchar, request_key varchar, fetched_at varchar, partitions json, "
        "file_path varchar)"
    )
    con.execute(
        "insert into raw.captures values ('espn', 'settings', '/p', 'k', 'x', '{}', ?)", [path]
    )
    con.close()
    rows = _rows((root, db), monkeypatch, "fo_captures('espn', 'settings')")
    assert [row[6] for row in rows] == [path]
