"""Copy the raw rows the BigQuery slice reads into BigQuery, and prove they arrived whole.

Spec 0130, R3 and spec 0136; ADRs 0052, 0054, 0061 and 0093 to 0095. For the spike only: the
table is replaced on every run, and the production loader is another sub-project's.

Usage:  uv run --group bigquery python scripts/spike_load_bigquery.py \\
            --db data/warehouse.duckdb --raw-root data/raw --project "$FO_BQ_PROJECT" \\
            [--dry-run] [--write-landing ROOT]

What it does, in order:

1. Reads the keys of `raw.captures` from the local warehouse, read-only, and each payload
   from the landing zone (`--raw-root`) through `LandingZone`, for eleven endpoints and no
   others, and stops if the manifest and the zone do not name the same captures. The
   manifest's captures are read once, when the run starts: the known accounts of step 2,
   the check, the export and `--write-landing` are all drawn from that one set, so a capture
   loaded while the run is under way is neither written unchecked nor missing from the
   accounts. Eight of the constant ALLOWLIST are read whole (`mlb/players`, MLB's player
   list, among them, ADR 0095), and three as projections (ADRs 0061 and 0093), each a payload
   rebuilt from a list of wanted fields, never by removing unwanted ones, and keeping only
   single values (string, number, boolean, null), never an object or an array:
   - `espn/matchup_days` carries `teams` and `settings`: the ids, the marker's presence and
     ESPN's matchup lines (spec 0147) that its models read;
   - `espn/teams` carries `members`, owners and account ids: its `id` and `seasonId`, and per
     team the fixtures' `ESPN_TEAM_FIELDS`;
   - `espn/transactions` carries an author and account ids: per topic its `id` and `date`,
     per message its `id` and the fixtures' `ESPN_TRANSACTION_MESSAGE_FIELDS`.
   The two lists of wanted fields are imported from `scripts/make_fixtures.py`, so one list
   per endpoint serves the fixtures and the upload. There is no option to widen any list.
2. Checks every row before anything is written. A key that names a person
   (`privacy.FORBIDDEN_KEYS`) is a hit in any row. There are two exceptions, both for
   `firstName` and `lastName`, which name a ballplayer: directly in a
   `playerPoolEntry.player` object, and directly in an object of `$.people[]` of an
   `mlb/players` row. An ESPN account id (`privacy.GUID`) is a hit anywhere in a row whose
   source is `espn`; MLB rows are not checked for it, because MLB's `gameGuid` is a public
   game id of the same shape. The one exception is the id of a transaction's topic and
   message, `$.topics[i].id` and `$.topics[i].messages[j].id` of an `espn/transactions`
   row, when the whole string is one GUID (ADR 0094). Each such id is cross-checked against
   the account ids found in the raw payloads of the snapshot's `espn/teams` captures
   (`members[].id`, `teams[].owners[]`, `teams[].primaryOwner`) and `espn/transactions`
   captures (`topics[].author`, `topics[].messages[].author`), compared with braces and case
   ignored; an id equal to one is a hit. With transaction rows to upload and no account id
   found, the upload stops, since a check against nothing checks nothing. A row of a
   projected endpoint that is not exactly what its projection would produce is a hit too.
   On any hit it prints the endpoint, the request and the path, never the value, and exits 1
   having written nothing.
3. Writes one newline-delimited JSON file per endpoint under `data/bigquery_export/`, which
   is gitignored.
4. Confirms that billing is enabled on the project (R2.7), then loads the files into
   `raw.api_responses` by a load job, replacing the table: the text columns as STRING,
   `partitions` and `payload` as JSON, clustered by `source` and `endpoint`.
5. Reads every loaded row back, pairs it with its source row by the five key columns, and
   compares `file_path` exactly and `partitions` and `payload` as parsed JSON, since the two
   warehouses write the same JSON as different text. Exits 1 unless every row is paired and
   equal.

`--dry-run` does steps 1 and 2, prints what it would upload, with the number of known
accounts and of transaction ids it cross-checked, and stops. It needs neither credentials
nor the `bigquery` dependency group.

`--write-landing ROOT`, with or without `--dry-run` and needing no credentials, also writes,
once the check has passed, every row of the three projected endpoints to a new landing root
as the capture it came from (its partitions, capture name, request and `fetched_at`), so that
dbt's staging models can be built from the projection and compared with the real build. It
refuses, and writes nothing, a ROOT that exists or that `git check-ignore` does not report as
ignored.

The rows come from the manifest and the landing zone, and the capture views dbt reads on
either warehouse read exactly the manifest's files, so both builds read the same captures
by construction. `file_path` is the manifest's, relative to the landing root.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import duckdb

from front_office import privacy
from front_office.landing import LandedResponse, LandingZone

# The field lists the fixtures are built from: one list per endpoint serves the fixtures and
# the upload (ADR 0093). The module defines constants and functions and looks its roots up
# per call, so importing it does nothing.
from make_fixtures import ESPN_TEAM_FIELDS, ESPN_TRANSACTION_MESSAGE_FIELDS

# The only endpoints that may leave the machine (ADR 0054). Not configurable.
ALLOWLIST: tuple[tuple[str, str], ...] = (
    ("mlb", "boxscore"),
    ("mlb", "schedule"),
    ("espn", "roster"),
    ("espn", "matchups"),
    ("espn", "settings"),
    ("espn", "pro_schedule"),
    ("idmap", "player_id_map"),
    # Whole, with ballplayers' names (ADR 0095).
    ("mlb", "players"),
)
# Endpoints that hold member data and go up as a projection: a payload rebuilt from a list
# of wanted fields, made before the check and never by removing unwanted ones (ADR 0061,
# 0093). The functions are defined below; PROJECTIONS maps each endpoint to its own.
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
PLAYER_LIST = ("mlb", "players")
TEAMS = ("espn", "teams")
TRANSACTIONS = ("espn", "transactions")
# ... and, in MLB's player list, directly in an object of `people[]` (ADR 0095).
PERSON_OBJECT = re.compile(r"\$\.people\[\d+\]")
# The two places where a transaction's own id is allowed to be a GUID (ADR 0094).
TRANSACTION_ID_PATHS = re.compile(r"\$\.topics\[\d+\]\.(messages\[\d+\]\.)?id")
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


def _single(value: Any) -> bool:
    """A string, number, boolean or null: never an object or an array."""
    return value is None or isinstance(value, (str, int, float, bool))


def _rebuild(source: Any, fields: Iterable[str]) -> dict[str, Any]:
    """A new object holding only the listed dotted paths that exist in `source` and end in a
    single value. A value that is an object or an array is left out, since every listed field
    is one value and anything nested under it is not a field a model reads (R1.5). Unlike
    `make_fixtures.rebuild`, which copies whatever it finds."""
    out: dict[str, Any] = {}
    if not isinstance(source, dict):
        return out
    for dotted in fields:
        parts = dotted.split(".")
        node: Any = source
        for part in parts:
            if not isinstance(node, dict) or part not in node:
                break
            node = node[part]
        else:
            if _single(node):
                cursor = out
                for part in parts[:-1]:
                    cursor = cursor.setdefault(part, {})
                cursor[parts[-1]] = node
    return out


def project_teams(payload: Any) -> dict[str, Any]:
    """What of a `teams` response is uploaded: what stg_espn__teams reads (the ids, and for
    each team the fixtures' ESPN_TEAM_FIELDS) and nothing else, so no `members`, no
    `owners` and no `primaryOwner` (ADR 0093)."""
    projected = _rebuild(payload, ("id", "seasonId"))
    teams = payload.get("teams") if isinstance(payload, dict) else None
    projected["teams"] = [
        _rebuild(team, ESPN_TEAM_FIELDS) for team in (teams if isinstance(teams, list) else [])
    ]
    return projected


def project_transactions(payload: Any) -> dict[str, Any]:
    """What of a transaction log is uploaded: what stg_espn__transactions reads. Each topic's
    `id` and `date`, and each message's `id` and the fixtures'
    ESPN_TRANSACTION_MESSAGE_FIELDS; no `author`, no `creationInfo` (ADR 0093)."""
    topics = payload.get("topics") if isinstance(payload, dict) else None
    projected = []
    for topic in topics if isinstance(topics, list) else []:
        kept = _rebuild(topic, ("id", "date"))
        messages = topic.get("messages") if isinstance(topic, dict) else None
        kept["messages"] = [
            _rebuild(message, ("id", *ESPN_TRANSACTION_MESSAGE_FIELDS))
            for message in (messages if isinstance(messages, list) else [])
        ]
        projected.append(kept)
    return {"topics": projected}


PROJECTIONS: dict[tuple[str, str], Any] = {
    ("espn", "teams"): project_teams,
    ("espn", "transactions"): project_transactions,
    ("espn", "matchup_days"): project_matchup_day,
}
# Everything that is read for upload: ADR 0054's seven and ADR 0095's player list whole,
# ADR 0061's and ADR 0093's three projected.
UPLOADED: tuple[tuple[str, str], ...] = (*ALLOWLIST, *PROJECTIONS)


class ManifestDisagrees(Exception):
    """raw.captures and the landing zone do not name the same captures. Nothing was written.

    dbt reads exactly the manifest's captures, so an upload of any other set would not be the
    set the models read."""


@dataclass(frozen=True)
class Capture:
    """One capture of the snapshot: the manifest's narrow row and the committed capture it
    names. The payload is read only when asked for, through `landed`."""

    source: str
    endpoint: str
    key: tuple[str, ...]
    file_path: str
    partitions: str
    landed: LandedResponse


class ManifestRows:
    """The rows that are uploaded: the keys from the manifest `raw.captures`, each payload
    read from its file through `LandingZone`, the projected endpoints already projected.

    One set of captures per run (R2.7). The manifest's narrow rows of every uploaded
    endpoint are read once, at construction, and checked against the landing zone then, so
    the known accounts, the check, the export and the landing root are drawn from the same
    list. Payload files are never replaced (ADR 0014), so the list gives the same rows on
    every pass.

    Iterable more than once. Each pass walks that list in key order and reads one payload at
    a time as it yields the row; a sort of the payload-carrying rows ran out of memory on
    eight seasons (#83), and none is made here. Raises ManifestDisagrees, from the
    constructor, if the manifest holds a capture the landing zone has not committed, or the
    zone holds one the manifest lacks."""

    def __init__(self, db: Path, raw_root: Path) -> None:
        self.db = db
        self.zone = LandingZone(raw_root)
        # One query, so the manifest is read at one point in time: a load between two
        # endpoints' queries could otherwise list a transaction whose account the teams
        # captures read a moment earlier did not have (pre-PR review F2).
        manifest = self._manifest()
        self.captures: list[Capture] = []
        for source, endpoint in sorted(UPLOADED):
            listed = [values for values in manifest if values[:2] == (source, endpoint)]
            self.captures.extend(self._snapshot(source, endpoint, listed))

    def _snapshot(
        self, source: str, endpoint: str, manifest: list[tuple[str, ...]]
    ) -> list[Capture]:
        """The endpoint's captures: the manifest's rows, each tied to its committed capture."""
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
        return [
            Capture(source, endpoint, tuple(key), file_path, partitions, landed[file_path])
            for *key, file_path, partitions in manifest
        ]

    def row(self, capture: Capture) -> RawRow:
        """The row to upload for a capture: its payload read, and projected if the endpoint
        has a projection."""
        payload = capture.landed.payload
        project = PROJECTIONS.get((capture.source, capture.endpoint))
        if project is not None:
            payload = project(payload)
        return RawRow(*capture.key, capture.file_path, capture.partitions, json.dumps(payload))

    def _manifest(self) -> list[tuple[str, ...]]:
        """The manifest's narrow rows of every uploaded endpoint, in key order."""
        wanted = " or ".join("(source = ? and endpoint = ?)" for _ in UPLOADED)
        con = duckdb.connect(str(self.db), read_only=True)
        try:
            return con.execute(
                f"select {', '.join(KEY_COLUMNS)}, file_path, cast(partitions as varchar) "
                f"from raw.captures where {wanted} "
                f"order by {', '.join(KEY_COLUMNS)}",
                [part for pair in UPLOADED for part in pair],
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
        for capture in self.captures:
            yield self.row(capture)


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


def _normal_guid(text: str) -> str | None:
    """The normal form (braces stripped, lower case) of a string that is one GUID whole, else
    None. A string with text around a GUID is not one."""
    if privacy.GUID.fullmatch(text) is None:
        return None
    return text.strip("{}").lower()


def _is_transaction_id(row: RawRow, prefix: str, path: str, is_key: bool) -> bool:
    """Whether a string is a value at one of the two paths of an `espn/transactions` payload
    where a GUID-shaped id is allowed (ADR 0094)."""
    return (
        (row.source, row.endpoint) == TRANSACTIONS
        and prefix == ""
        and not is_key
        and TRANSACTION_ID_PATHS.fullmatch(path) is not None
    )


def privacy_hits(row: RawRow, accounts: frozenset[str]) -> list[str]:
    """What in this row may not be uploaded: where it is, never what it is. `accounts` are the
    known account ids in their normal form (see `known_accounts`)."""
    hits = []
    documents = (("", json.loads(row.payload)), ("partitions ", json.loads(row.partitions)))
    for prefix, document in documents:
        for path, key, _ in privacy.walk(document):
            if key not in privacy.FORBIDDEN_KEYS:
                continue
            # In an ESPN row only (R2.1): an MLB row's names are allowed at `people[i]` alone.
            if key in PLAYER_NAME_KEYS and row.source == "espn" and path.endswith(PLAYER_OBJECT):
                continue
            if (
                key in PLAYER_NAME_KEYS
                and (row.source, row.endpoint) == PLAYER_LIST
                and prefix == ""
                and PERSON_OBJECT.fullmatch(path) is not None
            ):
                continue
            hits.append(f"{row.label}: key {key} at {prefix}{path}")
    if row.source == "espn":
        for prefix, document in documents:
            for path, text, is_key in _strings(document):
                if not privacy.GUID.search(text):
                    continue
                if _is_transaction_id(row, prefix, path, is_key):
                    normal = _normal_guid(text)
                    if normal is not None:
                        if normal in accounts:
                            hits.append(
                                f"{row.label}: transaction id equals an account id at {path}"
                            )
                        continue
                where = "GUID in a key at" if is_key else "GUID at"
                hits.append(f"{row.label}: {where} {prefix}{path}")
        for name in ("request_path", "request_key", "file_path"):
            if privacy.GUID.search(getattr(row, name)):
                hits.append(f"{row.source}/{row.endpoint}: GUID in {name}")
    # A path is built from the document's own keys, and a key can be an account id: mask
    # every message whole, so no part of one can carry a value (R3.3).
    return [privacy.GUID.sub("<guid>", hit) for hit in hits]


def exempt_ids_checked(row: RawRow) -> int:
    """How many ids of this row passed the GUID exemption: whole GUIDs at a transaction's two
    id paths. Counted for the dry run's report."""
    if (row.source, row.endpoint) != TRANSACTIONS:
        return 0
    return sum(
        1
        for path, text, is_key in _strings(json.loads(row.payload))
        if _is_transaction_id(row, "", path, is_key) and _normal_guid(text) is not None
    )


def _guids_whole(values: Iterable[Any]) -> set[str]:
    """The normal form of each value that is one GUID whole."""
    return {
        normal
        for value in values
        if isinstance(value, str) and (normal := _normal_guid(value)) is not None
    }


def _list_of(node: Any, name: str) -> list[Any]:
    value = node.get(name) if isinstance(node, dict) else None
    return value if isinstance(value, list) else []


def _value_of(node: Any, name: str) -> list[Any]:
    return [node.get(name)] if isinstance(node, dict) else []


def known_accounts(rows: ManifestRows) -> frozenset[str]:
    """The account ids in the run's snapshot, in their normal form (ADR 0094). Read from the
    raw payloads of its `espn/teams` and `espn/transactions` captures, since the projected
    rows hold none: `members[].id`, `teams[].owners[]` and `teams[].primaryOwner` of the
    first, `topics[].author` and `topics[].messages[].author` of the second, each kept when
    it is one GUID whole (some authors are other strings)."""
    found: set[str] = set()
    for capture in rows.captures:
        pair = (capture.source, capture.endpoint)
        if pair not in (TEAMS, TRANSACTIONS):
            continue
        payload = capture.landed.payload
        if pair == TEAMS:
            for member in _list_of(payload, "members"):
                found |= _guids_whole(_value_of(member, "id"))
            for team in _list_of(payload, "teams"):
                found |= _guids_whole(_list_of(team, "owners"))
                found |= _guids_whole(_value_of(team, "primaryOwner"))
        else:
            for topic in _list_of(payload, "topics"):
                found |= _guids_whole(_value_of(topic, "author"))
                for message in _list_of(topic, "messages"):
                    found |= _guids_whole(_value_of(message, "author"))
    return frozenset(found)


class LandingRootRefused(Exception):
    """The root for `--write-landing` exists, or git does not ignore it. Nothing was written."""


def refuse_unsafe_landing_root(root: Path) -> None:
    """Raise LandingRootRefused unless `root` is new and ignored by git (R4.3): the captures
    written there are projections of real ones, and a commit must not be able to take them.
    A root git cannot judge, such as one outside any repository, is refused too."""
    if root.exists():
        raise LandingRootRefused(f"landing root {root} exists: refused, nothing was written")
    anchor = root.resolve().parent
    while not anchor.exists():
        anchor = anchor.parent
    ignored = subprocess.run(
        ["git", "check-ignore", "-q", "--", str(root.resolve())],
        cwd=anchor,
        capture_output=True,
        check=False,
    )
    if ignored.returncode != 0:
        raise LandingRootRefused(
            f"landing root {root} is not ignored by git: refused, nothing was written"
        )


def write_landing(rows: ManifestRows, root: Path) -> int:
    """Write the rows of the projected endpoints to a new landing root, as they would be
    uploaded, each as the capture it came from: its partitions, its name, its request and its
    `fetched_at`, so that the capture views and `fo_espn_latest` choose the same captures as
    on the real zone (R4.1). Returns the number written. Call it after the check has passed."""
    refuse_unsafe_landing_root(root)
    zone = LandingZone(root)
    written = 0
    for capture in rows.captures:
        if (capture.source, capture.endpoint) not in PROJECTIONS:
            continue
        row = rows.row(capture)
        meta = capture.landed.meta
        zone.write(
            source=capture.source,
            endpoint=capture.endpoint,
            partitions=meta["partitions"],
            name=capture.landed.capture.directory.name,
            payload=json.loads(row.payload),
            request={"url": meta["url"], "params": meta["params"]},
            fetched_at=row.fetched_at,
        )
        written += 1
    return written


class PrivacyHit(Exception):
    """Rows hold something that may not be uploaded. Nothing was written."""

    def __init__(self, hits: list[str]) -> None:
        super().__init__(f"{len(hits)} privacy hit(s); nothing was written")
        self.hits = hits


def check(rows: Iterable[RawRow], accounts: frozenset[str]) -> dict[tuple[str, str], int]:
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
            hits.append(f"{row.label}: not what its projection would produce")
        hits.extend(privacy_hits(row, accounts))
        counts[(row.source, row.endpoint)] = counts.get((row.source, row.endpoint), 0) + 1
    if TRANSACTIONS in counts and not accounts:
        # A cross-check against nothing checks nothing (ADR 0094).
        hits.append("no account ids were found to check transaction ids against")
    if hits:
        raise PrivacyHit(hits)
    return counts


def export(rows: Iterable[RawRow], out_dir: Path, accounts: frozenset[str]) -> list[Path]:
    """One newline-delimited JSON file per endpoint, written only if every row passes the
    check. `rows` is read twice: once to check all of it, once to write."""
    return checked_export(rows, out_dir, accounts)[1]


def checked_export(
    rows: Iterable[RawRow], out_dir: Path, accounts: frozenset[str]
) -> tuple[dict[tuple[str, str], int], list[Path]]:
    """`export`, with the rows per endpoint that the check counted."""
    counts = check(rows, accounts)
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
    parser.add_argument(
        "--write-landing",
        type=Path,
        metavar="ROOT",
        help="after the check, write the rows of the projected endpoints to a new landing "
        "root that git ignores, as the captures they came from; needs no credentials",
    )
    args = parser.parse_args(argv)
    try:
        if args.write_landing:
            refuse_unsafe_landing_root(args.write_landing)
        rows = read_rows(args.db, args.raw_root)
        accounts = known_accounts(rows)
        if args.dry_run:
            counts = check(rows, accounts)
        else:
            if not args.project:
                parser.error("--project is required unless --dry-run")
            counts, files = checked_export(rows, args.export_dir, accounts)
    except LandingRootRefused as stopped:
        print(stopped)
        return 1
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
    if args.write_landing:
        try:
            written = write_landing(rows, args.write_landing)
        except LandingRootRefused as stopped:
            print(stopped)
            return 1
        print(f"wrote {written} captures to {args.write_landing}")
    if args.dry_run:
        print(f"known account ids: {len(accounts)}")
        # Only the transaction captures: a pass over every row would read every payload again.
        transactions = (
            rows.row(capture)
            for capture in rows.captures
            if (capture.source, capture.endpoint) == TRANSACTIONS
        )
        print(f"exempt transaction ids checked: {sum(map(exempt_ids_checked, transactions))}")
        print("dry run: nothing exported, nothing uploaded")
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
