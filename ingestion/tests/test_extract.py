"""`front-office extract-marts` (spec 0232, R2.1 to R2.7, R7.3; ADR 0144): the table list, the type
map, the refusals, the rename-publish, `extract_info` and the CLI's options. No BigQuery and no
`dbt/ci.duckdb`: a synthetic warehouse in `tmp_path` and a fake client.
"""

from __future__ import annotations

import datetime as dt
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import duckdb
import pytest
from typer.testing import CliRunner

from front_office import extract
from front_office.cli import app

runner = CliRunner()

EXPOSURES = """
exposures:
  - name: some_other_exposure
    type: analysis
    depends_on:
      - ref('not_wanted')
  - name: front_office_dashboard
    type: dashboard
    depends_on:
      - ref('alpha')
      - ref("beta")
"""
AWKWARD = [0.1 + 0.2, 1e-300, 0.12345678901234567, -1.7976931348623157e308, 5e-324]


@pytest.fixture
def exposures(tmp_path: Path) -> Path:
    path = tmp_path / "_exposures.yml"
    path.write_text(EXPOSURES)
    return path


@pytest.fixture
def warehouse(tmp_path: Path) -> Path:
    path = tmp_path / "warehouse.duckdb"
    con = duckdb.connect(str(path))
    con.execute("create schema marts")
    con.execute(
        "create table marts.alpha (id bigint, score double, name varchar, flag boolean,"
        " day date, seen timestamp, seen_tz timestamptz, big hugeint)"
    )
    for i, score in enumerate(AWKWARD):
        con.execute(
            "insert into marts.alpha values (?, ?, ?, ?, '2026-04-01', '2026-04-01 12:30:00',"
            " '2026-04-01 12:30:00+00', 170141183460469231731687303715884105727)",
            [i, score, f"n{i}", i % 2 == 0],
        )
    con.execute("insert into marts.alpha values (null, null, null, null, null, null, null, null)")
    con.execute("create table marts.beta (k varchar, n integer)")
    con.execute("insert into marts.beta values ('a', 1), ('b', null)")
    con.execute("create table marts.not_wanted (x integer)")
    con.close()
    return path


def test_the_tables_are_exactly_the_exposures_refs_in_both_quote_styles(exposures: Path) -> None:
    """Catches reading another exposure's refs, or missing one quote style (R2.1)."""
    assert extract.dashboard_tables(exposures) == ["alpha", "beta"]


def test_a_missing_exposure_is_refused(tmp_path: Path) -> None:
    """Catches an extract of nothing when the exposure is renamed."""
    path = tmp_path / "e.yml"
    path.write_text("exposures:\n  - name: other\n    depends_on: [\"ref('x')\"]\n")
    with pytest.raises(extract.ExtractRefused, match="front_office_dashboard"):
        extract.dashboard_tables(path)


def test_the_duckdb_path_copies_every_table_exactly(
    warehouse: Path, exposures: Path, tmp_path: Path
) -> None:
    """Catches a lost row, a changed type, or a float that does not round-trip (R2.1, R2.4)."""
    out = tmp_path / "out" / "extract.duckdb"
    reader = extract.DuckDBMartReader(warehouse)
    counts = extract.extract(reader, extract.dashboard_tables(exposures), out)
    reader.close()
    assert counts == {"alpha": len(AWKWARD) + 1, "beta": 2}
    con = duckdb.connect(str(out), read_only=True)
    con.execute(f"attach '{warehouse}' as src (read_only)")
    for table in ("alpha", "beta"):
        assert con.execute(
            f"select count(*) from (select * from src.marts.{table} except all"
            f" select * from marts.{table})"
        ).fetchone() == (0,)
        assert con.execute(
            f"select count(*) from (select * from marts.{table} except all"
            f" select * from src.marts.{table})"
        ).fetchone() == (0,)
        types = (
            "select column_name, data_type from information_schema.columns"
            f" where table_name = '{table}' and table_catalog = "
        )
        assert (
            con.execute(types + "'src'").fetchall() == con.execute(types + "'extract'").fetchall()
        )
    names = con.execute(
        "select table_name from information_schema.tables"
        " where table_schema = 'marts' and table_catalog = 'extract'"
    ).fetchall()
    assert {r[0] for r in names} == {"alpha", "beta", "extract_info"}
    floats = [
        r[0]
        for r in con.execute(
            "select score from marts.alpha where id is not null order by id"
        ).fetchall()
    ]
    assert floats == AWKWARD
    info = con.execute(
        "select table_name, row_count, extracted_at is not null, warehouse_modified_at is not null"
        " from marts.extract_info order by table_name"
    ).fetchall()
    assert info == [("alpha", len(AWKWARD) + 1, True, True), ("beta", 2, True, True)]
    assert not list(out.parent.glob("*.tmp-*"))


# --- BigQuery, by a fake client ---------------------------------------------------------------


def field(name: str, field_type: str, mode: str = "NULLABLE") -> Any:
    return SimpleNamespace(name=name, field_type=field_type, mode=mode)


class FakeRow:
    def __init__(self, *values: Any) -> None:
        self._values = values

    def values(self) -> tuple[Any, ...]:
        return self._values


class NotFound(Exception):
    pass


class FakeClient:
    """Tables as `{name: (fields, rows)}`; `query` must never be called (R2.2)."""

    def __init__(self, tables: dict[str, tuple[list[Any], list[FakeRow]]]) -> None:
        self.tables = tables
        self.modified = dt.datetime(2026, 11, 1, 6, 0, tzinfo=dt.UTC)

    def query(self, *args: Any, **kwargs: Any) -> Any:
        raise AssertionError("the extract must not run a query")

    def get_table(self, reference: str) -> Any:
        project, dataset, name = reference.split(".")
        assert (project, dataset) == ("proj-x", "marts")
        if name not in self.tables:
            raise NotFound(reference)
        fields, rows = self.tables[name]
        return SimpleNamespace(schema=fields, modified=self.modified, num_rows=len(rows))

    def list_rows(self, reference: str) -> list[FakeRow]:
        return self.tables[reference.split(".")[2]][1]


def good_client() -> FakeClient:
    when = dt.datetime(2026, 4, 1, 12, 30, tzinfo=dt.UTC)
    return FakeClient(
        {
            "alpha": (
                [
                    field("a", "INTEGER"),
                    field("b", "INT64"),
                    field("c", "FLOAT"),
                    field("d", "FLOAT64"),
                    field("e", "STRING"),
                    field("f", "BOOLEAN"),
                    field("g", "BOOL", "REQUIRED"),
                    field("h", "DATE"),
                    field("i", "TIMESTAMP"),
                ],
                [
                    FakeRow(1, 2, 0.1 + 0.2, 1e-300, "x", True, False, dt.date(2026, 4, 1), when),
                    FakeRow(None, None, None, None, None, None, True, None, None),
                ],
            ),
            "beta": ([field("k", "STRING")], [FakeRow("a")]),
        }
    )


def bq_reader(client: FakeClient) -> extract.BigQueryMartReader:
    return extract.BigQueryMartReader("proj-x", "marts", client=client)


def test_the_type_map_covers_the_six_types_and_writes_the_rows(
    exposures: Path, tmp_path: Path
) -> None:
    """Catches a wrong mapping (R2.5's list) and a float or timestamp changed on the way."""
    out = tmp_path / "extract.duckdb"
    extract.extract(bq_reader(good_client()), ["alpha", "beta"], out)
    con = duckdb.connect(str(out), read_only=True)
    types = con.execute(
        "select data_type from information_schema.columns where table_name = 'alpha'"
        " order by ordinal_position"
    ).fetchall()
    assert [t[0] for t in types] == [
        "BIGINT", "BIGINT", "DOUBLE", "DOUBLE", "VARCHAR", "BOOLEAN", "BOOLEAN", "DATE",
        "TIMESTAMP WITH TIME ZONE",
    ]  # fmt: skip
    first = con.execute("select c, d, e, h from marts.alpha where a = 1").fetchone()
    assert first == (0.1 + 0.2, 1e-300, "x", dt.date(2026, 4, 1))
    assert con.execute("select count(*) from marts.alpha").fetchone() == (2,)
    modified = con.execute("select warehouse_modified_at from marts.extract_info limit 1")
    assert modified.fetchone() == (dt.datetime(2026, 11, 1, 6, 0, tzinfo=dt.UTC),)


def refusal_cases() -> list[tuple[str, Any, str]]:
    def with_alpha(*fields: Any) -> FakeClient:
        client = good_client()
        client.tables["alpha"] = (list(fields), [])
        return client

    missing = good_client()
    del missing.tables["beta"]
    # JSON has no NaN: a non-finite double must stop the extract, never be written as null.
    not_finite = good_client()
    not_finite.tables["alpha"] = ([field("x", "FLOAT")], [FakeRow(1.5), FakeRow(float("nan"))])
    return [
        ("numeric", with_alpha(field("ok", "STRING"), field("money", "NUMERIC")), "alpha.*money"),
        ("record", with_alpha(field("rec", "RECORD")), "alpha.*rec"),
        ("repeated", with_alpha(field("arr", "STRING", "REPEATED")), "alpha.*arr"),
        ("missing", missing, "beta"),
        ("not_finite", not_finite, "alpha"),
    ]


@pytest.mark.parametrize("case", refusal_cases(), ids=lambda c: c[0])
def test_a_refusal_names_the_table_and_leaves_the_old_extract_alone(
    case: tuple[str, Any, str], tmp_path: Path
) -> None:
    """Catches a bad type or missing mart that is guessed at, or that damages the published
    file or leaves a temporary one behind (R2.3, R2.5)."""
    out = tmp_path / "extract.duckdb"
    extract.extract(bq_reader(good_client()), ["alpha", "beta"], out)
    before = out.read_bytes()
    with pytest.raises(extract.ExtractRefused, match=case[2]):
        extract.extract(bq_reader(case[1]), ["alpha", "beta"], out)
    assert out.read_bytes() == before
    assert sorted(p.name for p in tmp_path.iterdir()) == ["extract.duckdb"]


def test_a_refusal_with_no_old_extract_makes_none(tmp_path: Path) -> None:
    """Catches a half-written file published as the extract."""
    out = tmp_path / "extract.duckdb"
    client = good_client()
    client.tables["alpha"] = ([field("m", "NUMERIC")], [])
    with pytest.raises(extract.ExtractRefused):
        extract.extract(bq_reader(client), ["alpha"], out)
    assert list(tmp_path.iterdir()) == []


def test_publishing_by_rename_leaves_an_open_reader_on_the_old_file(tmp_path: Path) -> None:
    """Catches publishing in place, which would break the dashboard's open connection (R2.3)."""
    out = tmp_path / "extract.duckdb"
    extract.extract(bq_reader(good_client()), ["beta"], out)
    old = duckdb.connect(str(out), read_only=True)
    newer = good_client()
    newer.tables["beta"] = ([field("k", "STRING")], [FakeRow("a"), FakeRow("b"), FakeRow("c")])
    extract.extract(bq_reader(newer), ["beta"], out)
    assert old.execute("select count(*) from marts.beta").fetchone() == (1,)
    # DuckDB hands the same process the file it already has open, so a new reader is another
    # process, as the dashboard is.
    fresh = subprocess.run(
        [
            sys.executable,
            "-c",
            "import duckdb, sys; c = duckdb.connect(sys.argv[1], read_only=True);"
            " print(c.execute('select count(*) from marts.beta').fetchone()[0])",
            str(out),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    assert fresh.stdout.strip() == "3"
    old.close()


def test_git_commit_prefers_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Catches ignoring `FO_GIT_COMMIT`, which is all the image has (C20)."""
    monkeypatch.setenv("FO_GIT_COMMIT", "abc123")
    assert extract.git_commit() == "abc123"


def test_git_commit_is_unknown_when_nothing_gives_one(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Catches a missing commit failing the extract (R2.4)."""
    monkeypatch.delenv("FO_GIT_COMMIT", raising=False)

    def no_git(*args: Any, **kwargs: Any) -> Any:
        raise FileNotFoundError("git")

    monkeypatch.setattr(extract.subprocess, "run", no_git)
    assert extract.git_commit() == "unknown"
    out = tmp_path / "extract.duckdb"
    extract.extract(bq_reader(good_client()), ["beta"], out)
    con = duckdb.connect(str(out), read_only=True)
    assert con.execute("select git_commit from marts.extract_info").fetchone() == ("unknown",)


# --- the CLI ----------------------------------------------------------------------------------


@pytest.mark.parametrize("options", [[], ["--project", "proj-x", "--db", "w.duckdb"]])
def test_exactly_one_of_project_and_db(options: list[str], tmp_path: Path) -> None:
    """Catches an extract that picks a warehouse for itself."""
    result = runner.invoke(app, ["extract-marts", "--out", str(tmp_path / "o.duckdb"), *options])
    assert result.exit_code == 1
    assert "exactly one of --project and --db" in result.output


def test_the_command_extracts_a_duckdb_warehouse(
    warehouse: Path, exposures: Path, tmp_path: Path
) -> None:
    """Catches the command not wiring the reader, the exposure and the summary together."""
    out = tmp_path / "o.duckdb"
    result = runner.invoke(
        app,
        ["extract-marts", "--db", str(warehouse), "--out", str(out), "--exposures", str(exposures)],
    )
    assert result.exit_code == 0, result.output
    assert f"extracted 2 tables, {len(AWKWARD) + 3} rows, to {out}" in result.output


def test_a_missing_table_exits_1_naming_it(tmp_path: Path, exposures: Path) -> None:
    """Catches a missing mart that exits 0 or with a traceback (R2.5)."""
    warehouse = tmp_path / "w.duckdb"
    con = duckdb.connect(str(warehouse))
    con.execute("create schema marts; create table marts.alpha (x integer)")
    con.close()
    out = tmp_path / "o.duckdb"
    result = runner.invoke(
        app,
        ["extract-marts", "--db", str(warehouse), "--out", str(out), "--exposures", str(exposures)],
    )
    assert result.exit_code == 1
    assert "table beta" in result.output
    assert not out.exists()
