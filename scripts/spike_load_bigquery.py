"""Copy the raw rows the BigQuery slice reads into BigQuery, and prove they arrived whole.

Spec 0130, R3; ADRs 0052 and 0054. For the spike only: the table is replaced on every run,
and the production loader is another sub-project's.

Usage:  uv run --group bigquery python scripts/spike_load_bigquery.py \\
            --db data/warehouse.duckdb --project "$FO_BQ_PROJECT" [--dry-run]

What it does, in order:

1. Reads `raw.api_responses` from the local warehouse, read-only, for seven endpoints and no
   others. The list is the constant ALLOWLIST; there is no option to widen it. `espn/teams`
   and `espn/transactions` carry league members' names and account ids and are never read
   here.
2. Checks every row before anything is written. A key that names a person
   (`privacy.FORBIDDEN_KEYS`) is a hit in any row; the one exception is `firstName` and
   `lastName` directly in a `playerPoolEntry.player` object, which name a ballplayer. An
   ESPN account id (`privacy.GUID`) is a hit anywhere in a row whose source is `espn`; MLB
   rows are not checked for it, because MLB's `gameGuid` is a public game id of the same
   shape. On any hit it prints the endpoint, the request and the path, never the value,
   and exits 1 having written nothing.
3. Writes one newline-delimited JSON file per endpoint under `data/bigquery_export/`, which
   is gitignored.
4. Confirms that billing is enabled on the project (R2.7), then loads the files into
   `raw.api_responses` by a load job, replacing the table: the text columns as STRING,
   `partitions` and `payload` as JSON, clustered by `source` and `endpoint`.
5. Reads every loaded row back, pairs it with its source row by the five key columns, and
   compares `file_path` exactly and `partitions` and `payload` as parsed JSON, since the two
   warehouses write the same JSON as different text. Exits 1 unless every row is paired and
   equal.

`--dry-run` does steps 1 and 2, prints what it would upload, and stops. It needs neither
credentials nor the `bigquery` dependency group.

The rows come from the local warehouse and not from the landing zone, so that both builds
read the same rows by construction.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import duckdb

from front_office import privacy

# The only endpoints that may leave the machine (ADR 0054). Not configurable.
ALLOWLIST: tuple[tuple[str, str], ...] = (
    ("mlb", "boxscore"),
    ("mlb", "schedule"),
    ("espn", "roster"),
    ("espn", "matchups"),
    ("espn", "settings"),
    ("espn", "pro_schedule"),
    ("idmap", "player_id_map"),
)
KEY_COLUMNS = ("source", "endpoint", "request_path", "request_key", "fetched_at")
JSON_COLUMNS = ("partitions", "payload")
COLUMNS = (*KEY_COLUMNS, "file_path", *JSON_COLUMNS)
# The two keys that name a ballplayer when they sit directly in this object.
PLAYER_OBJECT = ".playerPoolEntry.player"
PLAYER_NAME_KEYS = frozenset({"firstName", "lastName"})
DATASET = "raw"
TABLE = "api_responses"
LOCATION = "US"
EXPORT_DIR = Path("data/bigquery_export")


@dataclass(frozen=True)
class RawRow:
    """One row of raw.api_responses; `partitions` and `payload` are JSON text."""

    source: str
    endpoint: str
    request_path: str
    request_key: str
    fetched_at: str
    file_path: str
    partitions: str
    payload: str

    @property
    def key(self) -> tuple[str, ...]:
        return tuple(getattr(self, name) for name in KEY_COLUMNS)

    @property
    def label(self) -> str:
        """Which row, for a message. A GUID in the request key is masked: a rejection says
        where a value is, never what it is (R3.3), and the key is itself a place one can be."""
        return f"{self.source}/{self.endpoint} {privacy.GUID.sub('<guid>', self.request_key)}"


class WarehouseRows:
    """The allowlisted rows of a local warehouse. Iterable more than once: each pass opens
    the file read-only and streams, so the 1.5 GB of payloads is never held at once."""

    def __init__(self, db: Path) -> None:
        self.db = db

    def __iter__(self) -> Iterator[RawRow]:
        pairs = ", ".join(f"('{source}', '{endpoint}')" for source, endpoint in ALLOWLIST)
        con = duckdb.connect(str(self.db), read_only=True)
        try:
            cursor = con.execute(
                f"select {', '.join(KEY_COLUMNS)}, file_path, "
                "cast(partitions as varchar), cast(payload as varchar) "
                f"from raw.api_responses where (source, endpoint) in ({pairs}) "
                f"order by {', '.join(KEY_COLUMNS)}"
            )
            while batch := cursor.fetchmany(50):
                for values in batch:
                    yield RawRow(*values)
        finally:
            con.close()


def read_rows(db: Path) -> WarehouseRows:
    return WarehouseRows(db)


# -- the privacy check ---------------------------------------------------------------------


def _strings(node: Any, path: str = "$") -> Iterator[tuple[str, str, bool]]:
    """(path, text, is a key) for every key and every string value in a nested structure."""
    if isinstance(node, dict):
        for key, value in node.items():
            yield path, key, True
            yield from _strings(value, f"{path}.{key}")
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from _strings(value, f"{path}[{index}]")
    elif isinstance(node, str):
        yield path, node, False


def privacy_hits(row: RawRow) -> list[str]:
    """What in this row may not be uploaded: where it is, never what it is."""
    hits = []
    documents = (("", json.loads(row.payload)), ("partitions ", json.loads(row.partitions)))
    for prefix, document in documents:
        for path, key, _ in privacy.walk(document):
            if key not in privacy.FORBIDDEN_KEYS:
                continue
            if key in PLAYER_NAME_KEYS and path.endswith(PLAYER_OBJECT):
                continue
            hits.append(f"{row.label}: key {key} at {prefix}{path}")
    if row.source == "espn":
        for prefix, document in documents:
            for path, text, is_key in _strings(document):
                if privacy.GUID.search(text):
                    where = "GUID in a key at" if is_key else "GUID at"
                    hits.append(f"{row.label}: {where} {prefix}{path}")
        for name in ("request_path", "request_key", "file_path"):
            if privacy.GUID.search(getattr(row, name)):
                hits.append(f"{row.source}/{row.endpoint}: GUID in {name}")
    return hits


class PrivacyHit(Exception):
    """Rows hold something that may not be uploaded. Nothing was written."""

    def __init__(self, hits: list[str]) -> None:
        super().__init__(f"{len(hits)} privacy hit(s); nothing was written")
        self.hits = hits


def check(rows: Iterable[RawRow]) -> dict[tuple[str, str], int]:
    """Rows per endpoint, after checking every one. Raises PrivacyHit with every hit."""
    counts: dict[tuple[str, str], int] = {}
    hits: list[str] = []
    for row in rows:
        if (row.source, row.endpoint) not in ALLOWLIST:
            hits.append(f"{row.label}: endpoint is not on the allowlist")
        hits.extend(privacy_hits(row))
        counts[(row.source, row.endpoint)] = counts.get((row.source, row.endpoint), 0) + 1
    if hits:
        raise PrivacyHit(hits)
    return counts


def export(rows: Iterable[RawRow], out_dir: Path) -> list[Path]:
    """One newline-delimited JSON file per endpoint, written only if every row passes the
    check. `rows` is read twice: once to check all of it, once to write."""
    return checked_export(rows, out_dir)[1]


def checked_export(
    rows: Iterable[RawRow], out_dir: Path
) -> tuple[dict[tuple[str, str], int], list[Path]]:
    """`export`, with the rows per endpoint that the check counted."""
    counts = check(rows)
    out_dir.mkdir(parents=True, exist_ok=True)
    for stale in out_dir.glob("*.ndjson"):
        stale.unlink()
    files: dict[tuple[str, str], Any] = {}
    try:
        for row in rows:
            pair = (row.source, row.endpoint)
            if pair not in files:
                files[pair] = (out_dir / f"{row.source}__{row.endpoint}.ndjson").open("w")
            line = {name: getattr(row, name) for name in (*KEY_COLUMNS, "file_path")}
            line.update({name: json.loads(getattr(row, name)) for name in JSON_COLUMNS})
            files[pair].write(json.dumps(line) + "\n")
    finally:
        for handle in files.values():
            handle.close()
    return counts, sorted(Path(handle.name) for handle in files.values())


# -- the comparison after the load ---------------------------------------------------------


@dataclass
class Tally:
    paired: int = 0
    equal: int = 0
    only_source: int = 0
    only_loaded: int = 0


def _normal(node: Any) -> Any:
    """A parsed JSON value with a whole float as an integer, so that 1 and 1.0, which the
    two warehouses may write for the same number, compare equal."""
    if isinstance(node, dict):
        return {key: _normal(value) for key, value in node.items()}
    if isinstance(node, list):
        return [_normal(value) for value in node]
    if isinstance(node, float) and node.is_integer():
        return int(node)
    return node


def _digest(value: Any) -> str:
    """A digest of a JSON value as parsed, whatever its key order; text is parsed first."""
    parsed = json.loads(value) if isinstance(value, str) else value
    text = json.dumps(_normal(parsed), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode()).hexdigest()


def compare_rows(
    source_rows: Iterable[RawRow], loaded_rows: Iterable[dict[str, Any]]
) -> dict[tuple[str, str], Tally]:
    """Pair loaded rows with source rows by the key columns and compare each pair.

    Equal means the same `file_path` text and the same `partitions` and `payload` as parsed
    JSON. Each source row pairs once: a second loaded row with the same key is counted as
    only in the load. Only digests of the source rows are kept, not their payloads.
    """
    result: dict[tuple[str, str], Tally] = {}
    waiting: dict[tuple[str, ...], tuple[str, str, str]] = {}
    for row in source_rows:
        result.setdefault((row.source, row.endpoint), Tally())
        waiting[row.key] = (row.file_path, _digest(row.partitions), _digest(row.payload))
    for loaded in loaded_rows:
        key = tuple(str(loaded[name]) for name in KEY_COLUMNS)
        tally = result.setdefault((key[0], key[1]), Tally())
        expected = waiting.pop(key, None)
        if expected is None:
            tally.only_loaded += 1
            continue
        tally.paired += 1
        found = (loaded["file_path"], _digest(loaded["partitions"]), _digest(loaded["payload"]))
        tally.equal += found == expected
    for key in waiting:
        result[(key[0], key[1])].only_source += 1
    return result


def all_equal(result: dict[tuple[str, str], Tally]) -> bool:
    """True when there was something to compare and every row is paired and equal."""
    return bool(result) and all(
        tally.paired > 0
        and tally.equal == tally.paired
        and tally.only_source == 0
        and tally.only_loaded == 0
        for tally in result.values()
    )


# -- BigQuery ------------------------------------------------------------------------------


def billing_enabled(project: str) -> bool:
    """Whether the project has a billing account linked (R2.7). Read-only: this never
    creates, changes or removes one."""
    import google.auth
    from google.auth.transport.requests import AuthorizedSession

    credentials, _ = google.auth.default(
        scopes=["https://www.googleapis.com/auth/cloud-platform.read-only"]
    )
    response = AuthorizedSession(credentials).get(
        f"https://cloudbilling.googleapis.com/v1/projects/{project}/billingInfo", timeout=30
    )
    response.raise_for_status()
    return bool(response.json().get("billingEnabled"))


def load(files: list[Path], project: str) -> None:
    """Replace raw.api_responses with the exported files, by load jobs."""
    from google.cloud import bigquery

    client = bigquery.Client(project=project, location=LOCATION)
    dataset = bigquery.Dataset(f"{project}.{DATASET}")
    dataset.location = LOCATION
    client.create_dataset(dataset, exists_ok=True)
    schema = [
        bigquery.SchemaField(name, "JSON" if name in JSON_COLUMNS else "STRING", mode="REQUIRED")
        for name in COLUMNS
    ]
    for number, path in enumerate(files):
        config = bigquery.LoadJobConfig(
            schema=schema,
            source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
            write_disposition=(
                bigquery.WriteDisposition.WRITE_TRUNCATE
                if number == 0
                else bigquery.WriteDisposition.WRITE_APPEND
            ),
            clustering_fields=["source", "endpoint"],
        )
        with path.open("rb") as handle:
            job = client.load_table_from_file(
                handle, f"{project}.{DATASET}.{TABLE}", job_config=config
            )
        job.result()
        print(f"loaded {path.name}: {job.output_rows} rows")


def loaded_rows(project: str) -> Iterator[dict[str, Any]]:
    """Every row of the loaded table, read through the client (not a query, not billed)."""
    from google.cloud import bigquery

    client = bigquery.Client(project=project, location=LOCATION)
    for row in client.list_rows(f"{project}.{DATASET}.{TABLE}", page_size=50):
        yield dict(row.items())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", type=Path, required=True, help="the local warehouse")
    parser.add_argument("--project", help="the BigQuery project id; not needed for --dry-run")
    parser.add_argument("--export-dir", type=Path, default=EXPORT_DIR)
    parser.add_argument(
        "--dry-run", action="store_true", help="check the rows and say what would be uploaded"
    )
    args = parser.parse_args(argv)
    rows = read_rows(args.db)
    try:
        if args.dry_run:
            counts = check(rows)
        else:
            if not args.project:
                parser.error("--project is required unless --dry-run")
            counts, files = checked_export(rows, args.export_dir)
    except PrivacyHit as stopped:
        print("\n".join(stopped.hits))
        print(f"{len(stopped.hits)} privacy hit(s). Nothing was written or uploaded.")
        return 1
    for (source, endpoint), count in sorted(counts.items()):
        print(f"{source}/{endpoint}: {count} rows")
    print(f"{sum(counts.values())} rows in {len(counts)} endpoints")
    if args.dry_run:
        print("dry run: nothing written, nothing uploaded")
        return 0
    if not billing_enabled(args.project):
        print(f"billing is not enabled on {args.project}: no job is run (spec 0130, R2.7)")
        return 1
    load(files, args.project)
    result = compare_rows(rows, loaded_rows(args.project))
    for (source, endpoint), tally in sorted(result.items()):
        print(
            f"{source}/{endpoint}: paired {tally.paired}, equal {tally.equal}, "
            f"only in the warehouse {tally.only_source}, only in BigQuery {tally.only_loaded}"
        )
    if not all_equal(result):
        print("the loaded table does not equal its source")
        return 1
    print("every loaded row equals its source row as parsed JSON")
    return 0


if __name__ == "__main__":
    sys.exit(main())
