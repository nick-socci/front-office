"""What may leave the machine for BigQuery, and what it becomes.

Spec 0140; ADRs 0054, 0061, 0093 to 0095 and 0117 to 0120. The first half is pure functions
over parsed JSON: the allowlist, the projections and the privacy check. The second is the run
(`upload`): it lists the landing zone, reads what each BigQuery table holds through a
`Warehouse`, builds and checks every row to send, then appends what each table lacks by load
jobs, the manifest `raw.captures` last. Nothing reads a credential (R6.6), and nothing imports
the BigQuery client: `bigquery.py` does, and only a run with a project loads it.

Eight endpoints are uploaded whole (ALLOWLIST; `mlb/players`, MLB's player list, among them,
ADR 0095). Three hold league members' data and go up as a projection (PROJECTIONS; ADRs 0061
and 0093): a payload rebuilt from a list of wanted fields, never by removing unwanted ones,
and keeping only single values (string, number, boolean, null), never an object or an array:

- `espn/matchup_days` carries `teams` and `settings`: the ids, the marker's presence and
  ESPN's matchup lines (spec 0147) that its models read;
- `espn/teams` carries `members`, owners and account ids: its `id` and `seasonId`, and per
  team `ESPN_TEAM_FIELDS`;
- `espn/transactions` carries an author and account ids: per topic its `id` and `date`, per
  message its `id` and `ESPN_TRANSACTION_MESSAGE_FIELDS`.
There is no option to widen any list. `ESPN_TEAM_FIELDS` and `ESPN_TRANSACTION_MESSAGE_FIELDS`
are defined here and imported by `scripts/make_fixtures.py`, so one list per endpoint serves
the fixtures and the upload.

`check` is the privacy check, run on every row before anything is sent. A key that names a
person (`privacy.FORBIDDEN_KEYS`) is a hit in any row. There are two exceptions, both for
`firstName` and `lastName`, which name a ballplayer: directly in a `playerPoolEntry.player`
object, and directly in an object of `$.people[]` of an `mlb/players` row. An ESPN account id
(`privacy.GUID`) is a hit anywhere in a row whose source is `espn`; MLB rows are not checked
for it, because MLB's `gameGuid` is a public game id of the same shape. The one exception is
the id of a transaction's topic and message, `$.topics[i].id` and
`$.topics[i].messages[j].id` of an `espn/transactions` row, when the whole string is one GUID
(ADR 0094). Each such id is cross-checked against the account ids found in the raw payloads
(`account_ids`), compared with braces and case ignored; an id equal to one is a hit. With
transaction rows to send and no account id found, the check fails, since a check against
nothing checks nothing. A row of `espn/teams` or `espn/transactions` that is not exactly what
its projection would produce is a hit too. A hit names the endpoint, the request and the path,
never the value.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import tempfile
from collections import Counter
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

from front_office import privacy
from front_office.capture_structures import (
    Column,
    StructureMismatch,
    as_columns,
    columns,
    read_structures,
    reduce,
)
from front_office.landing import LandedResponse, LandingZone

# The only endpoints that may leave the machine whole (ADR 0054). Not configurable.
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

# The wanted fields of a team of `espn/teams`, as dotted paths (ADR 0093). The fixtures are
# built from the same list.
ESPN_TEAM_FIELDS = (
    "id",
    "abbrev",
    "name",
    "playoffSeed",
    "eliminated",
    "record.overall.wins",
    "record.overall.losses",
    "record.overall.ties",
    "record.overall.streakLength",
    "record.overall.streakType",
)
# Transaction messages: what moved, where to. `for` is the acting team on a type-239 drop
# (ADR 0004). Never `author`, which is the ESPN account GUID of the member who made the move.
ESPN_TRANSACTION_MESSAGE_FIELDS = ("date", "messageTypeId", "targetId", "to", "from", "for")

# Endpoints that hold member data and go up as a projection: a payload rebuilt from a list
# of wanted fields, made before the check and never by removing unwanted ones (ADR 0061,
# 0093). The functions are defined below; PROJECTIONS maps each endpoint to its own.
MARKER = "rosterForCurrentScoringPeriod"
# ESPN's own record of what each player was credited with in a matchup (spec 0147), and the
# ids of one of its stat lines that are uploaded beside its `stats`.
MATCHUP_LINES = "rosterForMatchupPeriod"
LINE_IDS = ("statSourceId", "statSplitTypeId", "scoringPeriodId")
KEY_COLUMNS = ("source", "endpoint", "request_path", "request_key", "fetched_at")
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


@dataclass(frozen=True)
class Row:
    """One capture as it is to be sent. `partitions` and `document` are parsed JSON;
    `document` is what goes up of the payload: the whole payload, a projection, or (for a
    typed endpoint) its reduction to the declared structure, with each map still an object
    whose keys are keys (R6.3), before any map becomes key-value rows."""

    source: str
    endpoint: str
    request_path: str
    request_key: str
    fetched_at: str
    file_path: str
    partitions: Any
    document: Any

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
# Everything that may be sent: ADR 0054's seven and ADR 0095's player list whole, ADR 0061's
# and ADR 0093's three projected.
UPLOADED: tuple[tuple[str, str], ...] = (*ALLOWLIST, *PROJECTIONS)


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


def _is_transaction_id(row: Row, prefix: str, path: str, is_key: bool) -> bool:
    """Whether a string is a value at one of the two paths of an `espn/transactions` payload
    where a GUID-shaped id is allowed (ADR 0094)."""
    return (
        (row.source, row.endpoint) == TRANSACTIONS
        and prefix == ""
        and not is_key
        and TRANSACTION_ID_PATHS.fullmatch(path) is not None
    )


def privacy_hits(row: Row, accounts: frozenset[str]) -> list[str]:
    """What in this row may not be sent: where it is, never what it is. `accounts` are the
    known account ids in their normal form (see `account_ids`)."""
    hits = []
    documents = (("", row.document), ("partitions ", row.partitions))
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


def exempt_ids_checked(row: Row) -> int:
    """How many ids of this row passed the GUID exemption: whole GUIDs at a transaction's two
    id paths. Counted for the run's report."""
    if (row.source, row.endpoint) != TRANSACTIONS:
        return 0
    return sum(
        1
        for path, text, is_key in _strings(row.document)
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


def account_ids(source: str, endpoint: str, payload: Any) -> frozenset[str]:
    """The account ids one raw (unprojected) payload holds, in their normal form (ADR 0094):
    `members[].id`, `teams[].owners[]` and `teams[].primaryOwner` of an `espn/teams` payload,
    `topics[].author` and `topics[].messages[].author` of an `espn/transactions` one, each kept
    when it is one GUID whole (some authors are other strings). Any other endpoint holds none
    that count. The projected rows hold none, so the ids are read from the raw payloads."""
    found: set[str] = set()
    if (source, endpoint) == TEAMS:
        for member in _list_of(payload, "members"):
            found |= _guids_whole(_value_of(member, "id"))
        for team in _list_of(payload, "teams"):
            found |= _guids_whole(_list_of(team, "owners"))
            found |= _guids_whole(_value_of(team, "primaryOwner"))
    elif (source, endpoint) == TRANSACTIONS:
        for topic in _list_of(payload, "topics"):
            found |= _guids_whole(_value_of(topic, "author"))
            for message in _list_of(topic, "messages"):
                found |= _guids_whole(_value_of(message, "author"))
    return frozenset(found)


class PrivacyHit(Exception):
    """Rows hold something that may not be sent. Nothing was sent."""

    def __init__(self, hits: list[str]) -> None:
        super().__init__(f"{len(hits)} privacy hit(s); nothing was sent")
        self.hits = hits


def check(rows: Iterable[Row], accounts: frozenset[str]) -> dict[tuple[str, str], int]:
    """Rows per endpoint, after checking every one. Raises PrivacyHit with every hit."""
    counts: dict[tuple[str, str], int] = {}
    hits: list[str] = []
    for row in rows:
        project = PROJECTIONS.get((row.source, row.endpoint))
        if (row.source, row.endpoint) not in UPLOADED:
            hits.append(f"{row.label}: endpoint is not on the allowlist")
        elif (
            project is not None
            and (row.source, row.endpoint) in (TEAMS, TRANSACTIONS)
            and project(row.document) != row.document
        ):
            # Only what the projection itself would produce may go up: a whole capture of
            # one of these endpoints is refused, however clean it looks. A matchup_days
            # document is its projection reduced to a declared structure (the league id as
            # text, a missing field as null), which the projection alone does not reproduce,
            # so it is checked where its row is built.
            hits.append(f"{row.label}: not what its projection would produce")
        hits.extend(privacy_hits(row, accounts))
        if (row.source, row.endpoint) == TRANSACTIONS and not accounts:
            # A cross-check against nothing checks nothing (ADR 0094): each transaction row
            # is a hit, named by its request and the place its ids sit (R2.6).
            hits.append(f"{row.label}: no account ids were found to check the ids at $.topics")
        counts[(row.source, row.endpoint)] = counts.get((row.source, row.endpoint), 0) + 1
    if hits:
        raise PrivacyHit(hits)
    return counts


# -- the run -------------------------------------------------------------------------------

DATASET = "raw"
MANIFEST = "captures"
MATCHUP_DAYS = ("espn", "matchup_days")
STAMP_SHAPE = re.compile(r"\d{8}T\d{6}Z")
STAMP_FORMAT = "%Y%m%dT%H%M%SZ"
# Every table's key columns, in the order of the capture views and of raw.captures on DuckDB.
KEYS = (
    *(Column(name, "STRING") for name in KEY_COLUMNS),
    Column("partitions", "JSON"),
    Column("file_path", "STRING"),
)
# The owner's remedy for a row already sent that the check now finds (design, *A hit on a row
# already sent*). A check cannot undo a send, so every run stops until the row is gone.
REMEDY = (
    "This row is already uploaded, and every upload stops until it is gone. The remedy is "
    "the owner's: drop raw.espn_transactions (BigQuery's time travel keeps a dropped table "
    "for seven days, then it is gone), decide what this capture's row becomes, and run "
    "`front-office upload --project <id> --rebuild espn/transactions`."
)


class UploadRefused(Exception):
    """The upload stopped before sending anything. Nothing was sent."""


class UploadFailed(Exception):
    """Something was sent, and the run did not end as it should. Names what differs."""


class Warehouse(Protocol):
    """What the run needs of BigQuery, so that a fake can stand in for it in tests. Tables are
    named without the dataset; every method reads or writes the `raw` dataset."""

    project: str

    def billing_enabled(self) -> bool:
        """Whether the project has billing enabled. Read-only."""
        ...

    def columns(self, table: str) -> list[Column] | None:
        """The table's columns, or None if it does not exist."""
        ...

    def stored(self, table: str) -> list[tuple[str, ...]]:
        """(*key, file_path) of every row, read through the table read API with those fields
        selected, which bills nothing (R3.2)."""
        ...

    def create(self, table: str, columns: list[Column]) -> None:
        """Create an empty table with these columns."""
        ...

    def load(self, table: str, columns: list[Column], rows: Path, *, replace: bool) -> int:
        """Append (or with `replace`, replace the table with) the newline-delimited JSON file
        `rows`, by one load job. Returns the rows the job wrote."""
        ...

    def rows(self, table: str) -> Iterator[dict[str, Any]]:
        """Every row, every column, through the table read API, JSON values parsed."""
        ...


def table_name(pair: tuple[str, str]) -> str:
    return f"{pair[0]}_{pair[1]}"


def table_columns(pair: tuple[str, str], structures: dict[tuple[str, str], Any]) -> list[Column]:
    """A typed endpoint's key columns and its structure's fields; another's, and `payload`."""
    if pair in structures:
        return [*KEYS, *columns(structures[pair])]
    return [*KEYS, Column("payload", "JSON")]


@dataclass(frozen=True)
class Listed:
    """One committed capture of the run's listing: its key, path and partitions, and the
    capture itself, whose payload is read only when asked for."""

    pair: tuple[str, str]
    key: tuple[str, ...]
    file_path: str
    partitions: Any
    landed: LandedResponse


@contextmanager
def upload_lock(zone: LandingZone) -> Iterator[None]:
    """Hold the upload's own lock, `<root>.upload.lock`, or raise UploadRefused at once (R3.8).
    Not the landing zone's writer lock, so a fetch can go on while an upload runs."""
    path = zone.root.with_name(zone.root.name + ".upload.lock")
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_RDWR | os.O_CREAT, 0o644)
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise UploadRefused(f"another upload holds {path}: nothing was read or sent") from None
        yield
    finally:
        os.close(descriptor)  # closing releases the lock


def _masked(text: str) -> str:
    return privacy.GUID.sub("<guid>", text)


def _check_stamp(stamp: object, file_path: str) -> None:
    """Refuse a fetched_at that `front-office load` would refuse, and dbt fail on (R3.6)."""
    try:
        if not isinstance(stamp, str) or not STAMP_SHAPE.fullmatch(stamp):
            raise ValueError(stamp)
        datetime.strptime(stamp, STAMP_FORMAT)
    except ValueError:
        raise UploadRefused(
            f"capture {_masked(file_path)} has a fetched_at not of the form {STAMP_FORMAT}. "
            "Nothing was sent; fix or remove the capture."
        ) from None


def _collision(key: tuple[str, ...], first: str, second: str, where: str) -> UploadRefused:
    named = ", ".join(f"{column}={value!r}" for column, value in zip(KEY_COLUMNS, key, strict=True))
    return UploadRefused(
        _masked(f"two files share one raw key ({named}), {where}: {first} and {second}. ")
        + "Nothing was sent; remove or fix one of them (ADR 0011)."
    )


def list_zone(zone: LandingZone) -> dict[tuple[str, str], list[Listed]]:
    """Every committed capture of the uploaded endpoints, read once, from sidecars. Refuses a
    bad stamp, or two files with one key (R3.5, R3.6)."""
    listed: dict[tuple[str, str], list[Listed]] = {}
    seen: dict[tuple[str, ...], str] = {}
    for pair in sorted(UPLOADED):
        listed[pair] = []
        for landed in zone.iter_landed(source=pair[0], endpoint=pair[1]):
            meta = landed.meta
            file_path = landed.path.relative_to(zone.root).as_posix()
            _check_stamp(meta["fetched_at"], file_path)
            key = (
                meta["source"],
                meta["endpoint"],
                LandingZone.request_path(meta["url"]),
                meta["request_key"],
                meta["fetched_at"],
            )
            if key in seen:
                raise _collision(key, seen[key], file_path, "in the landing zone")
            seen[key] = file_path
            listed[pair].append(Listed(pair, key, file_path, meta["partitions"], landed))
    return listed


def build(listed: Listed, structures: dict[tuple[str, str], Any]) -> tuple[Row, dict[str, Any]]:
    """The row to check and the line to send for one capture: the payload projected if its
    endpoint has a projection, then reduced to its structure if it has one (R1.6), so that a
    matchup day's marker is an empty object before the structure keeps it."""
    payload = listed.landed.payload
    project = PROJECTIONS.get(listed.pair)
    if project is not None:
        payload = project(payload)
    structure = structures.get(listed.pair)
    label = f"{listed.pair[0]}/{listed.pair[1]} {_masked(listed.file_path)}"
    if structure is None:
        document, body = payload, {"payload": payload}
    else:
        try:
            document = reduce(payload, structure)
        except StructureMismatch as mismatch:
            raise UploadRefused(
                f"{label}: does not fit its declared structure {mismatch}. Nothing was sent."
            ) from None
        body = as_columns(document, structure)
    if listed.pair == MATCHUP_DAYS and any(
        side.get(MARKER) not in (None, {})
        for matchup in document.get("schedule", [])
        for side in (matchup.get("home"), matchup.get("away"))
        if isinstance(side, dict)
    ):
        # Only the marker's presence may go up, never the roster inside it (ADR 0061).
        raise UploadRefused(f"{label}: not what its projection would produce. Nothing was sent.")
    source, endpoint, request_path, request_key, fetched_at = listed.key
    row = Row(
        source,
        endpoint,
        request_path,
        request_key,
        fetched_at,
        listed.file_path,
        listed.partitions,
        document,
    )
    line = {
        **dict(zip(KEY_COLUMNS, listed.key, strict=True)),
        "partitions": listed.partitions,
        "file_path": listed.file_path,
        **body,
    }
    return row, line


def _manifest_line(listed: Listed) -> dict[str, Any]:
    return {
        **dict(zip(KEY_COLUMNS, listed.key, strict=True)),
        "partitions": listed.partitions,
        "file_path": listed.file_path,
    }


@dataclass
class _State:
    """What BigQuery holds at the start of the run: per table, each key's file path."""

    stored: dict[str, dict[tuple[str, ...], str]]
    absent: set[str]


def _read_state(
    warehouse: Warehouse,
    listed: dict[tuple[str, str], list[Listed]],
    structures: dict[tuple[str, str], Any],
    rebuild: tuple[str, str] | None,
) -> _State:
    """Each table's schema and stored keys, refused if they disagree with the listing (R3.5,
    R4.1). A rebuilt table's are not read: it is replaced whatever it holds."""
    state = _State({}, set())
    wanted = {table_name(pair): table_columns(pair, structures) for pair in listed}
    wanted[MANIFEST] = list(KEYS)
    zone_paths = {
        table_name(pair): {c.key: c.file_path for c in captures}
        for pair, captures in listed.items()
    }
    zone_paths[MANIFEST] = {
        key: path for paths in zone_paths.values() for key, path in paths.items()
    }
    for table, expected in wanted.items():
        if rebuild is not None and table == table_name(rebuild):
            state.stored[table] = {}
            continue
        found = warehouse.columns(table)
        if found is None:
            state.absent.add(table)
            state.stored[table] = {}
            continue
        if found != expected:
            command = (
                "no rebuild exists for the manifest; nothing in it can be lost, so recreate it "
                "from the endpoint tables by hand"
                if table == MANIFEST
                else f"rebuild it: front-office upload --project {warehouse.project} --rebuild "
                + table.replace("_", "/", 1)
            )
            raise UploadRefused(
                f"{DATASET}.{table}'s columns are not what its structure gives, so nothing is "
                f"appended to it: {command}. Nothing was sent."
            )
        stored: dict[tuple[str, ...], str] = {}
        for *key_parts, file_path in warehouse.stored(table):
            key = tuple(key_parts)
            if key in stored:
                raise UploadRefused(
                    f"{DATASET}.{table} holds one key twice ({_masked(stored[key])}). "
                    "Nothing was sent; rebuild the table."
                )
            zone_path = zone_paths[table].get(key)
            if zone_path is None:
                raise UploadRefused(
                    f"{DATASET}.{table} holds a capture the landing zone has not committed "
                    f"({_masked(file_path)}). Nothing was sent."
                )
            if zone_path != file_path:
                raise _collision(key, file_path, zone_path, f"{DATASET}.{table} against the zone")
            stored[key] = file_path
        state.stored[table] = stored
    return state


def _check_rows(
    rows: Iterable[tuple[Row, bool]], accounts: frozenset[str]
) -> tuple[dict[tuple[str, str], int], list[str], list[str]]:
    """Rows per endpoint, the hits on rows to send, and the hits on rows already sent."""
    counts: dict[tuple[str, str], int] = {}
    new: list[str] = []
    sent: list[str] = []
    for row, already in rows:
        try:
            for pair, count in check([row], accounts).items():
                counts[pair] = counts.get(pair, 0) + count
        except PrivacyHit as hit:
            if already:
                table = f"{DATASET}.{table_name((row.source, row.endpoint))}"
                where = f"in {table}, capture {_masked(row.file_path)}"
                sent.extend(f"{found} ({where})" for found in hit.hits)
            else:
                new.extend(hit.hits)
    return counts, new, sent


def upload(
    zone: LandingZone,
    warehouse: Warehouse | None,
    *,
    work_dir: Path,
    dry_run: bool = False,
    rebuild: tuple[str, str] | None = None,
    verify: bool = False,
    structures: dict[tuple[str, str], Any] | None = None,
    say: Callable[[str], None] = print,
) -> None:
    """One upload: list, read what each table holds, build and check every row to send, then
    append by load jobs, the manifest last, and check what the tables hold (design, *One
    run*). Raises UploadRefused when it stops before sending, UploadFailed after."""
    structures = read_structures() if structures is None else structures
    if rebuild is not None and rebuild not in UPLOADED:
        raise UploadRefused(f"{rebuild[0]}/{rebuild[1]} is not uploaded: nothing to rebuild")
    if warehouse is None and (verify or not dry_run):
        raise UploadRefused("--project is required, except for --dry-run. Nothing was sent.")
    with upload_lock(zone):
        listed = list_zone(zone)
        if rebuild is not None and not listed[rebuild]:
            raise UploadRefused(
                f"no committed captures of {rebuild[0]}/{rebuild[1]} to rebuild from"
            )
        accounts = frozenset().union(
            *(
                account_ids(*capture.pair, capture.landed.payload)
                for pair in (TEAMS, TRANSACTIONS)
                for capture in listed[pair]
            )
        )
        if warehouse is None:
            say("no --project: the remote checks (schemas, stored keys) did not run")
            nothing: dict[str, dict[tuple[str, ...], str]] = {table_name(p): {} for p in listed}
            state = _State({**nothing, MANIFEST: {}}, set())
        else:
            state = _read_state(warehouse, listed, structures, rebuild)
        work_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=work_dir, prefix="upload-") as scratch:
            to_send = _build_and_check(
                listed, structures, state, accounts, Path(scratch), say, dry_run
            )
            if dry_run:
                say("dry run: nothing sent")
            elif warehouse is not None:
                _send(warehouse, listed, structures, state, to_send, rebuild, Path(scratch), say)
        if verify and warehouse is not None:
            _verify(warehouse, listed, structures, say)


def _build_and_check(
    listed: dict[tuple[str, str], list[Listed]],
    structures: dict[tuple[str, str], Any],
    state: _State,
    accounts: frozenset[str],
    scratch: Path,
    say: Callable[[str], None],
    dry_run: bool,
) -> dict[tuple[str, str], int]:
    """Build every row to send, and every transaction row already sent, and check them all
    before any job runs (R6.3, R6.4). The rows to send are written to one file per table
    under `scratch` (not in a dry run). Returns the rows to send per endpoint."""
    to_send: dict[tuple[str, str], int] = {}
    exempt = 0

    def rows() -> Iterator[tuple[Row, bool]]:
        nonlocal exempt
        for pair, captures in listed.items():
            stored = state.stored[table_name(pair)]
            sending = [capture for capture in captures if capture.key not in stored]
            to_send[pair] = len(sending)
            # Every transaction capture is checked on every run, so that an account first
            # seen today is checked against the ids sent earlier (R6.4).
            checked = captures if pair == TRANSACTIONS else sending
            handle = (
                None
                if dry_run or not sending
                else (scratch / f"{table_name(pair)}.ndjson").open("w")
            )
            try:
                for capture in checked:
                    row, line = build(capture, structures)
                    exempt += exempt_ids_checked(row)
                    already = capture.key in stored
                    if handle is not None and not already:
                        handle.write(json.dumps(line) + "\n")
                    yield row, already
            finally:
                if handle is not None:
                    handle.close()

    _, new_hits, sent_hits = _check_rows(rows(), accounts)
    if sent_hits:
        raise UploadRefused("\n".join([*sent_hits, *new_hits, REMEDY, "Nothing was sent."]))
    if new_hits:
        raise UploadRefused(
            "\n".join([*new_hits, f"{len(new_hits)} privacy hit(s). Nothing was sent."])
        )
    for pair, count in to_send.items():
        held = len(state.stored[table_name(pair)])
        say(
            f"{DATASET}.{table_name(pair)}: {len(listed[pair])} committed, {held} stored, "
            f"{count} to send"
        )
    say(f"known account ids: {len(accounts)}; exempt transaction ids checked: {exempt}")
    return to_send


def _send(
    warehouse: Warehouse,
    listed: dict[tuple[str, str], list[Listed]],
    structures: dict[tuple[str, str], Any],
    state: _State,
    to_send: dict[tuple[str, str], int],
    rebuild: tuple[str, str] | None,
    scratch: Path,
    say: Callable[[str], None],
) -> None:
    """Steps 4 to 6 of *One run*: billing, missing tables, one load job per endpoint with rows
    to send, the manifest's rows for what the endpoint tables now hold, and the checks."""
    manifest_new = [
        capture
        for pair, captures in listed.items()
        for capture in captures
        if capture.key in state.stored[table_name(pair)]
        and capture.key not in state.stored[MANIFEST]
    ]
    if not any(to_send.values()) and not manifest_new and not state.absent:
        say("nothing to send")
        return
    if not warehouse.billing_enabled():
        raise UploadRefused(
            f"billing is not enabled on {warehouse.project}: no job is run (R6.5). "
            "Nothing was sent."
        )
    for table in sorted(state.absent):
        pair = next((p for p in listed if table_name(p) == table), None)
        warehouse.create(table, list(KEYS) if pair is None else table_columns(pair, structures))
        say(f"created {DATASET}.{table}")
    failed: str | None = None
    for pair, count in sorted(to_send.items()):
        if not count:
            continue
        table = table_name(pair)
        try:
            written = warehouse.load(
                table,
                table_columns(pair, structures),
                scratch / f"{table}.ndjson",
                replace=pair == rebuild,
            )
        except Exception as error:  # noqa: BLE001 - a job's failure is reported, and the run stops
            failed = f"{DATASET}.{table}: the load job failed: {error}"
            break
        if written != count:
            raise UploadFailed(
                f"{DATASET}.{table}: the load job wrote {written} rows, not {count}. Nothing "
                "more was sent, and the manifest was not appended."
            )
        say(f"{'replaced' if pair == rebuild else 'appended'} {DATASET}.{table}: {written} rows")
        sent = [capture for capture in listed[pair] if capture.key not in state.stored[table]]
        manifest_new.extend(c for c in sent if c.key not in state.stored[MANIFEST])
        state.stored[table].update({capture.key: capture.file_path for capture in sent})
    # The manifest last, and only for captures their endpoint's table now holds (R3.4).
    if manifest_new:
        path = scratch / f"{MANIFEST}.ndjson"
        with path.open("w") as handle:
            for capture in manifest_new:
                handle.write(json.dumps(_manifest_line(capture)) + "\n")
        try:
            written = warehouse.load(MANIFEST, list(KEYS), path, replace=False)
        except Exception as error:  # noqa: BLE001 - reported; the next run appends it again
            raise UploadFailed(
                f"{DATASET}.{MANIFEST}: the load job failed: {error}. The endpoint tables hold "
                "their captures; the next upload adds what the manifest lacks."
            ) from error
        if written != len(manifest_new):
            raise UploadFailed(
                f"{DATASET}.{MANIFEST}: the load job wrote {written} rows, not {len(manifest_new)}"
            )
        say(f"appended {DATASET}.{MANIFEST}: {written} rows")
    if failed is not None:
        # The tables that were appended are whole, and the manifest names only what they
        # hold; the next run finds what each lacks (R3.3).
        raise UploadFailed(f"{failed}. The next upload adds what each table lacks.")
    problems = _check_tables(warehouse, listed)
    if problems:
        raise UploadFailed("\n".join(problems))
    say("every table holds each committed capture once, and the manifest names each")


def _check_tables(warehouse: Warehouse, listed: dict[tuple[str, str], list[Listed]]) -> list[str]:
    """What differs between each table, the manifest and the listing: every key once, with
    the zone's file path, and nothing else (R4.3)."""
    problems: list[str] = []
    manifest = Counter((*key, path) for *key, path in warehouse.stored(MANIFEST))
    for pair, captures in sorted(listed.items()):
        table = table_name(pair)
        expected = Counter((*capture.key, capture.file_path) for capture in captures)
        for name, found in (
            (table, Counter(tuple(row) for row in warehouse.stored(table))),
            (MANIFEST, Counter({row: n for row, n in manifest.items() if row[:2] == pair})),
        ):
            if found == expected:
                continue
            repeated = sum(1 for row, n in found.items() if n > 1)
            missing = len(expected - found)
            extra = len(found - expected) - sum(n - 1 for n in found.values() if n > 1)
            problems.append(
                f"{DATASET}.{name}, {pair[0]}/{pair[1]}: {missing} committed captures missing, "
                f"{extra} rows the zone lacks, {repeated} keys stored more than once"
            )
    return problems


def _normal(node: Any) -> Any:
    """A parsed value with a whole float as an integer, so that 1 and 1.0, which a JSON value
    may come back as, compare equal."""
    if isinstance(node, dict):
        return {key: _normal(value) for key, value in node.items()}
    if isinstance(node, list):
        return [_normal(value) for value in node]
    if isinstance(node, float) and node.is_integer():
        return int(node)
    return node


def _digest(line: dict[str, Any]) -> str:
    text = json.dumps(_normal(line), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode()).hexdigest()


def _verify(
    warehouse: Warehouse,
    listed: dict[tuple[str, str], list[Listed]],
    structures: dict[tuple[str, str], Any],
    say: Callable[[str], None],
) -> None:
    """Read back every row of every table and compare it, as parsed values, with what this
    run would send for it (R4.4). Only digests of the expected rows are kept."""
    problems: list[str] = []
    for pair, captures in sorted(listed.items()):
        table = table_name(pair)
        expected = {capture.key: _digest(build(capture, structures)[1]) for capture in captures}
        differ = only_stored = 0
        for row in warehouse.rows(table):
            key = tuple(str(row[name]) for name in KEY_COLUMNS)
            digest = expected.pop(key, None)
            if digest is None:
                only_stored += 1
            elif digest != _digest(row):
                differ += 1
        say(
            f"verify {DATASET}.{table}: {len(captures) - len(expected) - differ} equal, "
            f"{differ} differ, {len(expected)} missing, {only_stored} only stored"
        )
        if differ or expected or only_stored:
            problems.append(f"{DATASET}.{table} does not equal what would be sent")
    expected = {
        capture.key: _digest(_manifest_line(capture))
        for captures in listed.values()
        for capture in captures
    }
    differ = only_stored = 0
    for row in warehouse.rows(MANIFEST):
        digest = expected.pop(tuple(str(row[name]) for name in KEY_COLUMNS), None)
        only_stored += digest is None
        differ += digest is not None and digest != _digest(row)
    say(
        f"verify {DATASET}.{MANIFEST}: {differ} differ, {len(expected)} missing, "
        f"{only_stored} only stored"
    )
    if differ or expected or only_stored:
        problems.append(f"{DATASET}.{MANIFEST} does not equal what would be sent")
    if problems:
        raise UploadFailed("\n".join(problems))
    say("verify: every row of every table equals what would be sent")
