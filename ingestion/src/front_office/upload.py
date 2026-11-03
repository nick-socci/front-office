"""What may leave the machine for BigQuery, and what it becomes.

Spec 0140; ADRs 0054, 0061, 0093, 0094 and 0095. Pure functions over parsed JSON: nothing
here reads the landing zone, a warehouse or a credential, and nothing is sent. The run that
does those things builds a `Row` per capture and hands the rows to `check`.

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

import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from typing import Any

from front_office import privacy

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
