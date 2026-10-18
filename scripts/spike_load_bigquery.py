"""Copy the raw rows the BigQuery slice reads into BigQuery, and prove they arrived whole.

Spec 0130, R3; ADRs 0052 and 0054. For the spike only: the table is replaced on every run,
and the production loader is another sub-project's.

Usage:  uv run --group bigquery python scripts/spike_load_bigquery.py \\
            --db data/warehouse.duckdb --raw-root data/raw --project "$FO_BQ_PROJECT" [--dry-run]

What it does, in order:

1. Reads the keys of `raw.captures` from the local warehouse, read-only, and each payload
   from the landing zone (`--raw-root`) through `LandingZone`, for nine endpoints and no
   others, and stops if the manifest and the zone do not name the same captures. Seven of
   the constant ALLOWLIST are read whole, and two as projections (ADR 0061).
   `espn/transactions` carries members' names and account ids, and `espn/matchup_days`
   carries `teams` and `settings`: of the first nothing of the payload is uploaded, of the
   second the ids, the marker's presence and ESPN's matchup lines (spec 0147) that its
   models read, rebuilt from a list of wanted fields.
   There is no option to widen either list. `espn/teams` is never read here.
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

The rows come from the manifest and the landing zone, and the capture views dbt reads on
either warehouse read exactly the manifest's files, so both builds read the same captures
by construction. `file_path` is the manifest's, relative to the landing root.
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
from front_office.landing import LandedResponse, LandingZone

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
# Endpoints that hold member data and go up as a projection: a payload rebuilt from a list
# of wanted fields, made before the check and never by removing unwanted ones (ADR 0061).
# The functions are defined below; PROJECTIONS maps each endpoint to its own.
MARKER = "rosterForCurrentScoringPeriod"
# ESPN's own record of what each player was credited with in a matchup (spec 0147), and the
# ids of one of its stat lines that are uploaded beside its `stats`.
MATCHUP_LINES = "rosterForMatchupPeriod"
LINE_IDS = ("statSourceId", "statSplitTypeId", "scoringPeriodId")
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
    """One row of the upload; `partitions` and `payload` are JSON text."""

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


def _whole_number(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _project_stat_line(line: Any) -> dict[str, Any]:
    """One stat line of a matchup entry: its three ids, only as whole numbers, and its
    `stats`: stat id to a number or text, nothing nested."""
    kept: dict[str, Any] = {}
    if isinstance(line, dict):
        for name in LINE_IDS:
            if _whole_number(line.get(name)):
                kept[name] = line[name]
        stats = line.get("stats")
        if isinstance(stats, dict):
            kept["stats"] = {
                key: value
                for key, value in stats.items()
                if isinstance(value, (int, float, str)) and not isinstance(value, bool)
            }
    return kept


def _project_matchup_entries(roster: Any) -> list[dict[str, Any]]:
    """ESPN's matchup lines of one side: for each entry its player id and its stat lines,
    in the nesting the capture view declares. No name, no slot, nothing else."""
    entries = roster.get("entries") if isinstance(roster, dict) else None
    kept = []
    for entry in entries if isinstance(entries, list) else []:
        out: dict[str, Any] = {}
        if isinstance(entry, dict):
            if _whole_number(entry.get("playerId")):
                out["playerId"] = entry["playerId"]
            pool = entry.get("playerPoolEntry")
            player = pool.get("player") if isinstance(pool, dict) else None
            lines = player.get("stats") if isinstance(player, dict) else None
            if isinstance(lines, list):
                out["playerPoolEntry"] = {
                    "player": {"stats": [_project_stat_line(line) for line in lines]}
                }
        kept.append(out)
    return kept


def _project_matchup_side(side: Any) -> dict[str, Any] | None:
    """A side of a matchup, or None when it has neither of the two keys the models read
    (a playoff bye's empty `away`): its team, the marker as its presence, and ESPN's matchup
    lines."""
    if not isinstance(side, dict) or not (MARKER in side or MATCHUP_LINES in side):
        return None
    kept: dict[str, Any] = {}
    if _whole_number(side.get("teamId")):
        kept["teamId"] = side["teamId"]
    if MARKER in side:
        kept[MARKER] = {}
    if MATCHUP_LINES in side:
        kept[MATCHUP_LINES] = {"entries": _project_matchup_entries(side[MATCHUP_LINES])}
    return kept


def project_matchup_day(payload: Any) -> dict[str, Any]:
    """What of a `matchup_days` response is uploaded: what stg_espn__matchup_days and
    stg_espn__matchup_player_lines and their tests read, and nothing else (ADR 0061, spec
    0147). The ids only as whole numbers; the marker only as its presence, an empty object;
    the matchup lines as player ids and stat lines, with no name."""
    if not isinstance(payload, dict):
        return {"schedule": []}
    projected: dict[str, Any] = {
        name: payload[name]
        for name in ("id", "seasonId", "scoringPeriodId")
        if _whole_number(payload.get(name))
    }
    schedule = payload.get("schedule")
    projected["schedule"] = []
    for matchup in schedule if isinstance(schedule, list) else []:
        kept: dict[str, Any] = {}
        if isinstance(matchup, dict):
            for name in ("id", "matchupPeriodId"):
                if _whole_number(matchup.get(name)):
                    kept[name] = matchup[name]
            for side in ("home", "away"):
                projected_side = _project_matchup_side(matchup.get(side))
                if projected_side is not None:
                    kept[side] = projected_side
        projected["schedule"].append(kept)
    return projected


def project_transactions(payload: Any) -> dict[str, Any]:
    """Nothing of a transaction log is uploaded: stg_espn__transaction_logs reads a
    capture's partitions and time, never its payload."""
    return {}


PROJECTIONS: dict[tuple[str, str], Any] = {
    ("espn", "transactions"): project_transactions,
    ("espn", "matchup_days"): project_matchup_day,
}
# Everything that is read for upload: ADR 0054's seven whole, ADR 0061's two projected.
UPLOADED: tuple[tuple[str, str], ...] = (*ALLOWLIST, *PROJECTIONS)


class ManifestDisagrees(Exception):
    """raw.captures and the landing zone do not name the same captures. Nothing was written.

    dbt reads exactly the manifest's captures, so an upload of any other set would not be the
    set the models read."""


class ManifestRows:
    """The rows that are uploaded: the keys from the manifest `raw.captures`, each payload
    read from its file through `LandingZone`, the two projected endpoints already projected.

    Iterable more than once. Each pass reads the manifest's narrow rows of one endpoint, in
    key order, and then reads one payload at a time as it yields the row; a sort of the
    payload-carrying rows ran out of memory on eight seasons (#83), and none is made here.
    Raises ManifestDisagrees, before yielding a row of an endpoint, if the manifest holds a
    capture the landing zone has not committed, or the zone holds one the manifest lacks."""

    def __init__(self, db: Path, raw_root: Path) -> None:
        self.db = db
        self.zone = LandingZone(raw_root)

    def _manifest(self, source: str, endpoint: str) -> list[tuple[str, ...]]:
        con = duckdb.connect(str(self.db), read_only=True)
        try:
            return con.execute(
                f"select {', '.join(KEY_COLUMNS)}, file_path, cast(partitions as varchar) "
                "from raw.captures where source = ? and endpoint = ? "
                f"order by {', '.join(KEY_COLUMNS)}",
                [source, endpoint],
            ).fetchall()
        finally:
            con.close()

    def _landed(self, source: str, endpoint: str) -> dict[str, LandedResponse]:
        """The endpoint's committed captures by path relative to the root. A capture's
        payload is read only when asked for."""
        return {
            landed.path.relative_to(self.zone.root).as_posix(): landed
            for landed in self.zone.iter_landed(source=source, endpoint=endpoint)
        }

    def __iter__(self) -> Iterator[RawRow]:
        for source, endpoint in sorted(UPLOADED):
            manifest = self._manifest(source, endpoint)
            landed = self._landed(source, endpoint)
            listed = {values[5] for values in manifest}
            missing = sorted(listed - landed.keys())
            unlisted = sorted(landed.keys() - listed)
            if missing or unlisted:
                raise ManifestDisagrees(
                    "\n".join(
                        [
                            f"{source}/{endpoint}: in raw.captures, not committed: {path}"
                            for path in missing[:5]
                        ]
                        + [
                            f"{source}/{endpoint}: committed, not in raw.captures: {path}"
                            for path in unlisted[:5]
                        ]
                    )
                    + f"\n{source}/{endpoint}: {len(missing)} in the manifest only, "
                    f"{len(unlisted)} in the landing zone only"
                )
            project = PROJECTIONS.get((source, endpoint))
            for *key, file_path, partitions in manifest:
                payload = landed[file_path].payload
                if project is not None:
                    payload = project(payload)
                yield RawRow(*key, file_path, partitions, json.dumps(payload))


def read_rows(db: Path, raw_root: Path) -> ManifestRows:
    return ManifestRows(db, raw_root)


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
    # A path is built from the document's own keys, and a key can be an account id: mask
    # every message whole, so no part of one can carry a value (R3.3).
    return [privacy.GUID.sub("<guid>", hit) for hit in hits]


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
        project = PROJECTIONS.get((row.source, row.endpoint))
        if (row.source, row.endpoint) not in UPLOADED:
            hits.append(f"{row.label}: endpoint is not on the allowlist")
        elif project is not None and project(json.loads(row.payload)) != json.loads(row.payload):
            # Only what the projection itself would produce may go up: a whole capture of
            # one of these endpoints is refused, however clean it looks.
            hits.append(f"{row.label}: not in its projected form (ADR 0061)")
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
    parser.add_argument(
        "--raw-root", type=Path, default=Path("data/raw"), help="the landing zone's root"
    )
    parser.add_argument("--project", help="the BigQuery project id; not needed for --dry-run")
    parser.add_argument("--export-dir", type=Path, default=EXPORT_DIR)
    parser.add_argument(
        "--dry-run", action="store_true", help="check the rows and say what would be uploaded"
    )
    args = parser.parse_args(argv)
    rows = read_rows(args.db, args.raw_root)
    try:
        if args.dry_run:
            counts = check(rows)
        else:
            if not args.project:
                parser.error("--project is required unless --dry-run")
            counts, files = checked_export(rows, args.export_dir)
    except ManifestDisagrees as stopped:
        print(stopped)
        print("raw.captures and the landing zone disagree. Nothing was written or uploaded.")
        return 1
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
