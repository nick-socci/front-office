"""Audit the landing zone and warehouse before treating them as historical evidence.

Passing dbt tests cannot show that an input is complete: a missing boxscore becomes a
player-day of zeros, not a failure. So before a reconciliation result is believed, this
checks the files themselves:

  landing  everything under the root is a committed capture (one directory holding a
           payload and a sidecar that agrees with its path) whose payload matches its
           checksum; nothing is waiting in quarantine
  loaded   every committed capture is a row in raw.api_responses, with no key collisions
  mlb      every played game in the newest schedule has a boxscore, and one was captured
           after the game's settle window closed
  espn     every scoring period has a roster captured after the period closed; the
           scoring-date anchor is stable across snapshots and lands on MLB opening day;
           league snapshots postdate the season; the transaction log is not truncated

ERROR means the data cannot be relied on as it stands. WARN means the evidence that it
is final or complete is missing, though the data may be fine. INFO records the facts
worth keeping with the audit output.
"""

from __future__ import annotations

import datetime as dt
import json
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import duckdb

from front_office.espn import transactions as espn_transactions
from front_office.landing import META_FILE, VANISHED, LandingZone
from front_office.load import QUALIFIED, SCHEMA, TABLE
from front_office.mlb import boxscore as mlb_boxscore

# ESPN's scoring day rolls over at midnight Eastern; see the fo_eastern_date dbt macro.
EASTERN = ZoneInfo("America/New_York")
EXAMPLES = 3
LEAGUE_SNAPSHOTS = ("settings", "teams", "matchups", "transactions")


class Severity(StrEnum):
    ERROR = "ERROR"
    WARN = "WARN"
    INFO = "INFO"


@dataclass(frozen=True)
class Finding:
    severity: Severity
    check: str
    subject: str
    detail: str


@dataclass(frozen=True)
class Capture:
    """A committed capture whose sidecar has been read; `path` is its payload.json."""

    path: Path
    meta: Mapping[str, Any]

    @property
    def source(self) -> str:
        return str(self.meta["source"])

    @property
    def endpoint(self) -> str:
        return str(self.meta["endpoint"])

    @property
    def fetched_at(self) -> str:
        return str(self.meta["fetched_at"])

    def partition(self, key: str) -> str | None:
        value = self.meta["partitions"].get(key)
        return None if value is None else str(value)

    def payload(self) -> Any:
        return json.loads(self.path.read_text())


def eastern_date(fetched_at: str) -> dt.date:
    """The Eastern calendar date of a compact UTC stamp like 20260926T162307Z."""
    instant = dt.datetime.strptime(fetched_at, "%Y%m%dT%H%M%SZ").replace(tzinfo=dt.UTC)
    return instant.astimezone(EASTERN).date()


def run_audit(
    zone: LandingZone,
    con: duckdb.DuckDBPyConnection | None,
    *,
    season: int,
    today: dt.date,
) -> list[Finding]:
    """Every check, in order. `con` is None when there is no warehouse to check."""
    findings, captures = check_landing(zone)
    if con is None:
        findings.append(
            Finding(Severity.ERROR, "loaded", QUALIFIED, "no warehouse; run `front-office load`")
        )
    else:
        findings += check_loaded(zone, captures, con)
    mlb_findings, opening_day = check_mlb(zone, captures, season=season, today=today)
    findings += mlb_findings
    findings += check_espn(captures, season=season, opening_day=opening_day)
    return findings


# -- landing ---------------------------------------------------------------------------

_FILE_PROBLEMS = {
    "temp": (Severity.ERROR, "temporary director(y/ies) left by an interrupted write"),
    "invalid": (Severity.ERROR, "capture director(y/ies) that fail the capture check"),
    "loose": (Severity.ERROR, "loose file(s) outside any capture directory (old layout?)"),
    "empty": (Severity.ERROR, "empty director(y/ies)"),
    "corrupt": (
        Severity.ERROR,
        "capture(s) whose payload is unreadable or does not match its checksum",
    ),
}


def check_landing(zone: LandingZone) -> tuple[list[Finding], list[Capture]]:
    """Classify everything under the root. Returns findings and the usable captures.

    A usable capture passes the shared check, shallow and deep. One that passes shallow
    and fails deep is reported and withheld, so the checks that read payloads never meet
    it.
    """
    problems: dict[tuple[str, str], list[str]] = defaultdict(list)
    committed: Counter[str] = Counter()
    captures: list[Capture] = []
    verified = unverified = 0

    for scanned in zone.scan():
        group = _group(zone, scanned.path)
        example = str(scanned.path.relative_to(zone.root))
        if scanned.kind != "committed":
            reason = zone.check(scanned.path) if scanned.kind == "invalid" else None
            problems[(scanned.kind, group)].append(f"{example} ({reason})" if reason else example)
            continue
        if zone.check(scanned.path, deep=True) is not None:
            problems[("corrupt", group)].append(example)
            continue
        try:
            meta = json.loads((scanned.path / META_FILE).read_bytes())
        except (*VANISHED, ValueError):
            continue  # swept between the check and the read
        if meta.get("payload_sha256") is None:
            unverified += 1
        else:
            verified += 1
        committed[group] += 1
        captures.append(Capture(path=scanned.path / "payload.json", meta=meta))

    findings = [
        Finding(Severity.INFO, "landing", group, f"{count} committed capture(s)")
        for group, count in sorted(committed.items())
    ]
    findings.append(
        Finding(
            Severity.INFO,
            "landing",
            "checksums",
            f"{verified} capture(s) checksum-verified, {unverified} with no recorded checksum",
        )
    )
    for (kind, group), examples in sorted(problems.items()):
        severity, message = _FILE_PROBLEMS[kind]
        findings.append(
            Finding(severity, "landing", group, f"{len(examples)} {message}; {_sample(examples)}")
        )
    layout = zone.layout_problem()
    if layout:
        findings.append(Finding(Severity.ERROR, "landing", "layout", layout))
    findings += _check_quarantine(zone)
    return findings, captures


def _check_quarantine(zone: LandingZone) -> list[Finding]:
    """Anything waiting in quarantine is a warning: someone should look, then clear it."""
    try:
        held = sorted(p for p in zone.quarantine_root.iterdir() if p.name != ".gitignore")
    except VANISHED:
        return []
    if not held:
        return []
    files = sum(1 for run in held for p in run.rglob("*") if p.is_file())
    runs = ", ".join(p.name for p in held)
    return [
        Finding(
            Severity.WARN,
            "landing",
            "quarantine",
            f"{files} file(s) in {len(held)} run director(y/ies) of {zone.quarantine_root}: "
            f"{runs}; look, then clear by hand",
        )
    ]


def _group(zone: LandingZone, path: Path) -> str:
    return "/".join(path.relative_to(zone.root).parts[:2])


# -- loaded ----------------------------------------------------------------------------


def check_loaded(
    zone: LandingZone, captures: list[Capture], con: duckdb.DuckDBPyConnection
) -> list[Finding]:
    """Every committed capture is a raw row, and no two captures compete for one row."""
    row = con.execute(
        "select count(*) from information_schema.tables where table_schema = ? and table_name = ?",
        [SCHEMA, TABLE],
    ).fetchone()
    if not row or not row[0]:
        return [
            Finding(Severity.ERROR, "loaded", QUALIFIED, "table missing; run `front-office load`")
        ]
    columns = {
        name
        for (name,) in con.execute(
            "select column_name from information_schema.columns "
            "where table_schema = ? and table_name = ?",
            [SCHEMA, TABLE],
        ).fetchall()
    }
    if "request_path" not in columns:
        return [
            Finding(
                Severity.ERROR,
                "loaded",
                QUALIFIED,
                "table has the old shape (no request_path column); rebuild into a new "
                "warehouse file with `front-office load --db <new file>`",
            )
        ]
    loaded = {
        tuple(map(str, key))
        for key in con.execute(
            f"select source, endpoint, request_path, request_key, fetched_at from {QUALIFIED}"
        ).fetchall()
    }

    # The raw table's primary key.
    by_key: dict[tuple[str, ...], list[Capture]] = defaultdict(list)
    for capture in captures:
        raw_key = (
            capture.source,
            capture.endpoint,
            LandingZone.request_path(capture.meta.get("url")),
            str(capture.meta["request_key"]),
            capture.fetched_at,
        )
        by_key[raw_key].append(capture)

    findings = []
    not_loaded: dict[str, list[str]] = defaultdict(list)
    for key, group in by_key.items():
        if key not in loaded:
            not_loaded[f"{key[0]}/{key[1]}"].append(str(group[0].path.relative_to(zone.root)))
        if len(group) > 1:
            findings.append(
                Finding(
                    Severity.ERROR,
                    "loaded",
                    f"{key[0]}/{key[1]}",
                    f"{len(group)} captures share raw key {key}; only one can be loaded "
                    f"(review R2); {_sample([str(c.path.relative_to(zone.root)) for c in group])}",
                )
            )
    for group_name, examples in sorted(not_loaded.items()):
        findings.append(
            Finding(
                Severity.ERROR,
                "loaded",
                group_name,
                f"{len(examples)} committed capture(s) not in {QUALIFIED}; "
                f"run `front-office load`; {_sample(examples)}",
            )
        )
    orphan_rows = loaded - by_key.keys()
    if orphan_rows:
        findings.append(
            Finding(
                Severity.WARN,
                "loaded",
                QUALIFIED,
                f"{len(orphan_rows)} row(s) with no committed capture on disk",
            )
        )
    if not findings:
        findings.append(
            Finding(
                Severity.INFO, "loaded", QUALIFIED, f"all {len(by_key)} committed capture(s) loaded"
            )
        )
    return findings


# -- mlb -------------------------------------------------------------------------------


def check_mlb(
    zone: LandingZone, captures: list[Capture], *, season: int, today: dt.date
) -> tuple[list[Finding], dt.date | None]:
    """Boxscore coverage and settle evidence. Also returns opening day, for the ESPN check.

    Played games come from the same function the backfill uses, so "expected" here means
    exactly what ingestion would have fetched.
    """
    subject = f"mlb {season}"
    schedule = _newest(captures, "mlb", "schedule", season=str(season))
    if schedule is None:
        return [Finding(Severity.ERROR, "mlb", subject, "no committed schedule capture")], None
    played = mlb_boxscore.games_from_landed_schedule(zone, season=season)
    played_pks = {game.game_pk for game in played}
    findings = []

    # Unplayed games need an explicit disposition, not silence. Resumed games finished
    # after their official date, so their settle window runs from the resume date.
    last_state: dict[int, str] = {}
    completed = {game.game_pk: game.official_date for game in played}
    resumed = set()
    for day in schedule.payload().get("dates", []):
        for entry in day.get("games", []):
            pk = int(entry["gamePk"])
            last_state[pk] = entry.get("status", {}).get("detailedState", "")
            resume = entry.get("resumeGameDate")
            if resume and pk in completed:
                completed[pk] = max(completed[pk], dt.date.fromisoformat(resume))
                resumed.add(pk)
    unplayed = Counter(state for pk, state in last_state.items() if pk not in played_pks)
    dispositions = ", ".join(f"{state} {n}" for state, n in sorted(unplayed.items()))
    findings.append(
        Finding(
            Severity.INFO,
            "mlb",
            subject,
            f"newest schedule {schedule.fetched_at}: {len(last_state)} scheduled, "
            f"{len(played)} played" + (f"; not played: {dispositions}" if dispositions else ""),
        )
    )

    boxscores: dict[int, list[str]] = defaultdict(list)
    for capture in captures:
        if (capture.source, capture.endpoint) == ("mlb", "boxscore") and capture.partition(
            "season"
        ) == str(season):
            boxscores[int(capture.partition("game_pk") or 0)].append(capture.fetched_at)

    missing = sorted(played_pks - boxscores.keys())
    if missing:
        findings.append(
            Finding(
                Severity.ERROR,
                "mlb",
                subject,
                f"{len(missing)} played game(s) with no boxscore; {_sample(map(str, missing))}",
            )
        )
    findings += _unplayed_boxscores(captures, boxscores.keys() - played_pks, last_state, subject)

    # Settled: some capture was taken on a later Eastern day than the window's last day.
    unsettled, pending = [], 0
    for pk in sorted(played_pks & boxscores.keys()):
        window_closes = completed[pk] + mlb_boxscore.SETTLE_WINDOW
        if any(eastern_date(stamp) > window_closes for stamp in boxscores[pk]):
            continue
        if today > window_closes:
            unsettled.append(pk)
        else:
            pending += 1
    if unsettled:
        findings.append(
            Finding(
                Severity.WARN,
                "mlb",
                subject,
                f"{len(unsettled)} game(s) captured only inside their settle window, which has "
                f"closed; a late correction may be missing (review R4). Run "
                f"`front-office backfill mlb --season {season} --refresh`; "
                f"{_sample(map(str, unsettled))}",
            )
        )
    if pending:
        findings.append(
            Finding(Severity.INFO, "mlb", subject, f"{pending} game(s) still in settle window")
        )
    if resumed:
        findings.append(
            Finding(
                Severity.INFO,
                "mlb",
                subject,
                f"{len(resumed)} resumed game(s) settle from their resume date, taken as the "
                f"completion date; {_sample(map(str, sorted(resumed)))}",
            )
        )
    opening_day = min((game.official_date for game in played), default=None)
    return findings, opening_day


# -- espn ------------------------------------------------------------------------------


def check_espn(
    captures: list[Capture], *, season: int, opening_day: dt.date | None
) -> list[Finding]:
    """Roster finality, calendar anchor and league-snapshot completeness, per league."""
    leagues = sorted(
        {
            capture.partition("league_id") or ""
            for capture in captures
            if (capture.source, capture.endpoint) == ("espn", "settings")
            and capture.partition("season") == str(season)
        }
    )
    if not leagues:
        return [Finding(Severity.ERROR, "espn", f"espn {season}", "no committed settings capture")]
    findings = []
    for league_id in leagues:
        findings += _check_league(
            captures, season=season, league_id=league_id, opening_day=opening_day
        )
    return findings


def _check_league(
    captures: list[Capture], *, season: int, league_id: str, opening_day: dt.date | None
) -> list[Finding]:
    subject = f"espn {season} league {league_id}"
    league = [
        capture
        for capture in captures
        if capture.source == "espn"
        and capture.partition("season") == str(season)
        and capture.partition("league_id") == league_id
    ]
    # Every run lands settings first under the run's fetched_at, so the status a settings
    # capture records is what ESPN reported when that run's other captures were taken.
    # Status only moves forward, so it is a conservative bound for anything fetched later
    # in the same run.
    status_by_run = {
        capture.fetched_at: capture.payload().get("status", {})
        for capture in league
        if capture.endpoint == "settings"
    }
    findings = []

    # The scoring-date anchor: each snapshot implies a date for period 1. They must agree
    # with each other and with MLB opening day, or stg_espn__scoring_periods shifts.
    implied = {
        run: eastern_date(run) - dt.timedelta(days=int(status["latestScoringPeriod"]) - 1)
        for run, status in status_by_run.items()
        if "latestScoringPeriod" in status
    }
    anchors = sorted(set(implied.values()))
    if len(anchors) > 1:
        detail = ", ".join(f"{run} -> {date}" for run, date in sorted(implied.items()))
        findings.append(
            Finding(
                Severity.ERROR,
                "espn",
                subject,
                f"settings snapshots imply different dates for period 1: {detail}",
            )
        )
    elif anchors and opening_day is None:
        findings.append(
            Finding(
                Severity.WARN,
                "espn",
                subject,
                f"period 1 = {anchors[0]} per {len(implied)} snapshot(s); no MLB schedule "
                "to confirm it against",
            )
        )
    elif anchors and anchors[0] != opening_day:
        findings.append(
            Finding(
                Severity.ERROR,
                "espn",
                subject,
                f"period 1 = {anchors[0]} per settings, but MLB opening day is {opening_day}",
            )
        )
    elif anchors:
        findings.append(
            Finding(
                Severity.INFO,
                "espn",
                subject,
                f"period 1 = {anchors[0]}: all {len(implied)} settings snapshot(s) agree, "
                "and it is MLB opening day",
            )
        )

    newest_status = status_by_run[max(status_by_run)]
    latest = int(newest_status.get("latestScoringPeriod", 0))
    final = int(newest_status.get("finalScoringPeriod", latest))
    first = int(newest_status.get("firstScoringPeriod", 1))
    season_over = latest > final

    def closed_at_run(run: str, period: int) -> bool:
        status = status_by_run.get(run)
        return status is not None and int(status.get("latestScoringPeriod", 0)) > period

    rosters: dict[int, list[str]] = defaultdict(list)
    for capture in league:
        if capture.endpoint == "roster":
            rosters[int(capture.partition("scoring_period") or 0)].append(capture.fetched_at)
    required = range(first, min(latest, final) + 1)
    missing = [period for period in required if period not in rosters]
    unproven = [
        period
        for period in required
        if period in rosters and not any(closed_at_run(run, period) for run in rosters[period])
    ]
    findings.append(
        Finding(
            Severity.INFO,
            "espn",
            subject,
            f"scoring periods {first}-{final}, latest {latest}; "
            f"{len(required) - len(missing) - len(unproven)} of {len(required)} rosters "
            "captured after their period closed",
        )
    )
    if missing:
        findings.append(
            Finding(
                Severity.ERROR,
                "espn",
                subject,
                f"{len(missing)} scoring period(s) with no roster; {_sample(map(str, missing))}",
            )
        )
    if unproven:
        findings.append(
            Finding(
                Severity.WARN,
                "espn",
                subject,
                f"{len(unproven)} roster(s) with no capture shown final by same-run settings "
                f"(review R1); {_sample(map(str, unproven))}",
            )
        )

    if not season_over:
        findings.append(
            Finding(
                Severity.INFO,
                "espn",
                subject,
                "season in progress: league snapshots are not final yet",
            )
        )
    else:
        for endpoint in LEAGUE_SNAPSHOTS:
            newest = _newest(league, "espn", endpoint)
            if newest is None:
                findings.append(
                    Finding(Severity.ERROR, "espn", subject, f"no committed {endpoint} capture")
                )
            elif not closed_at_run(newest.fetched_at, final):
                findings.append(
                    Finding(
                        Severity.WARN,
                        "espn",
                        subject,
                        f"newest {endpoint} capture ({newest.fetched_at}) is not shown to "
                        "postdate the final scoring period",
                    )
                )

    transactions = _newest(league, "espn", "transactions")
    if transactions is not None:
        run = [
            capture
            for capture in league
            if (capture.source, capture.endpoint) == ("espn", "transactions")
            and capture.fetched_at == transactions.fetched_at
        ]
        findings += _check_transactions(run, subject)
    return findings


def _check_transactions(run: list[Capture], subject: str) -> list[Finding]:
    """Completeness evidence for the transaction log, which milestone 10 depends on.

    `run` is every page landed by the newest run. The log is fetched unfiltered and
    paged (#26), so the pages must form the whole sequence (page_sequence_problems) and
    each topic must hold exactly its stated totalMessageCount; anything else is a
    missing page, a missing message or a truncated log.
    A capture without an offset predates that, used a message-type filter, and cannot
    be shown complete: a topic short by a filtered-out lineup move looks exactly like
    one short by a lost transaction.
    """
    run = sorted(run, key=lambda capture: int(capture.partition("offset") or 0))
    stamp = run[0].fetched_at
    parsed = [espn_transactions.page_topics(capture.payload()) for capture in run]
    malformed = [
        capture.partition("offset") or "none"
        for capture, page in zip(run, parsed, strict=True)
        if page is None
    ]
    topics = [topic for page in parsed if page is not None for topic in page]
    distinct = len({str(topic.get("id")) for topic in topics})
    findings = [
        Finding(
            Severity.INFO,
            "espn",
            subject,
            f"transactions {stamp}: {len(run)} page(s), {distinct} topic(s)"
            + (
                f" ({len(topics) - distinct} repeated across pages)"
                if len(topics) > distinct
                else ""
            ),
        )
    ]
    unpaged = [capture for capture in run if capture.partition("offset") is None]
    if len(unpaged) == len(run):
        findings.append(
            Finding(
                Severity.WARN,
                "espn",
                subject,
                f"transactions {stamp} predates the paged, unfiltered capture (#26), so its "
                "completeness cannot be shown; run `front-office backfill espn`",
            )
        )
        return findings

    pages = [
        (
            capture.meta.get("params", {}).get("offset"),
            capture.meta.get("params", {}).get("limit"),
            None if page is None else len(page),
        )
        for capture, page in zip(run, parsed, strict=True)
    ]
    problems = espn_transactions.page_sequence_problems(pages)
    if malformed:
        problems.append(
            f"{len(malformed)} page(s) carry no valid `topics` list, so their contents are "
            f"unknown (offset {', '.join(malformed)})"
        )
    if unpaged:
        problems.append(f"{len(unpaged)} page(s) of the run carry no offset")
    for problem in problems:
        findings.append(
            Finding(Severity.ERROR, "espn", subject, f"transactions {stamp}: {problem}")
        )
    short = espn_transactions.incomplete_topics(topics)
    if short:
        findings.append(
            Finding(
                Severity.ERROR,
                "espn",
                subject,
                f"transactions {stamp}: {len(short)} topic(s) do not hold exactly "
                f"totalMessageCount messages, or state no valid count; {_sample(short)}",
            )
        )
    return findings


# -- helpers ---------------------------------------------------------------------------


def _unplayed_boxscores(
    captures: list[Capture], game_pks: set[int], last_state: Mapping[int, str], subject: str
) -> list[Finding]:
    """Classify boxscores landed for games that were not played.

    A game can be fetched and only later cancelled, or fetched by older code that took a
    cancelled game for a played one (MLB files both under "Final"). The file is raw
    history and stays. What matters is whether it records appearances: a cancelled
    game's boxscore lists rosters with no stats, so nothing loads from it; one with
    appearances would put stats from an unplayed game into staging.
    """
    newest: dict[int, Capture] = {}
    for capture in captures:
        if (capture.source, capture.endpoint) != ("mlb", "boxscore"):
            continue
        pk = int(capture.partition("game_pk") or 0)
        if pk in game_pks and (pk not in newest or capture.fetched_at > newest[pk].fetched_at):
            newest[pk] = capture

    harmless: Counter[str] = Counter()
    harmless_pks, with_stats, unscheduled = [], [], []
    for pk in sorted(newest):
        if pk not in last_state:
            unscheduled.append(pk)
        elif _has_appearances(newest[pk].payload()):
            with_stats.append(pk)
        else:
            harmless[last_state[pk]] += 1
            harmless_pks.append(pk)

    findings = []
    if with_stats:
        findings.append(
            Finding(
                Severity.ERROR,
                "mlb",
                subject,
                f"{len(with_stats)} boxscore(s) record appearances for games the newest "
                f"schedule says were not played; staging would count them; "
                f"{_sample(map(str, with_stats))}",
            )
        )
    if unscheduled:
        findings.append(
            Finding(
                Severity.WARN,
                "mlb",
                subject,
                f"{len(unscheduled)} boxscore(s) for games the newest schedule does not list; "
                f"{_sample(map(str, unscheduled))}",
            )
        )
    if harmless:
        states = ", ".join(f"{state} {n}" for state, n in sorted(harmless.items()))
        findings.append(
            Finding(
                Severity.INFO,
                "mlb",
                subject,
                f"{len(harmless_pks)} boxscore(s) for games not played ({states}), with no "
                f"appearances, so nothing loads from them; {_sample(map(str, harmless_pks))}",
            )
        )
    return findings


def _has_appearances(payload: Mapping[str, Any]) -> bool:
    """True when any player batted or pitched: the same markers staging filters on."""
    for side in payload.get("teams", {}).values():
        for player in side.get("players", {}).values():
            stats = player.get("stats", {})
            if stats.get("batting", {}).get("gamesPlayed") or stats.get("pitching", {}).get(
                "gamesPitched"
            ):
                return True
    return False


def _newest(
    captures: Iterable[Capture], source: str, endpoint: str, **partitions: str
) -> Capture | None:
    matching = [
        capture
        for capture in captures
        if (capture.source, capture.endpoint) == (source, endpoint)
        and all(capture.partition(key) == value for key, value in partitions.items())
    ]
    return max(matching, key=lambda capture: capture.fetched_at, default=None)


def _sample(examples: Iterable[str]) -> str:
    listed = list(examples)
    more = f" and {len(listed) - EXAMPLES} more" if len(listed) > EXAMPLES else ""
    return f"e.g. {', '.join(listed[:EXAMPLES])}{more}"


def format_report(findings: list[Finding]) -> str:
    """Findings grouped by check, then a one-line tally."""
    lines = []
    for check in dict.fromkeys(finding.check for finding in findings):
        lines.append(f"== {check} ==")
        lines += [f"{f.severity:<5}  {f.subject}: {f.detail}" for f in findings if f.check == check]
    tally = Counter(finding.severity for finding in findings)
    lines.append(f"{tally[Severity.ERROR]} error(s), {tally[Severity.WARN]} warning(s)")
    return "\n".join(lines)
