"""Audit the landing zone and warehouse before treating them as historical evidence.

Passing dbt tests cannot show that an input is complete: a missing boxscore becomes a
player-day of zeros, not a failure. So before a reconciliation result is believed, this
checks the files themselves:

  landing  everything under the root is a committed capture (one directory holding a
           payload and a sidecar that agrees with its path) whose payload matches its
           checksum; nothing is waiting in quarantine
  loaded   every committed capture is a row in raw.api_responses, with no key collisions
  mlb      every played game in the newest schedule has a boxscore, and one was captured
           a settle window (7 days) after its first capture that postdates the game's last
           scheduled start, by the same functions the backfill uses (specs/0030)
  espn     every scoring period has a roster captured after the period closed; period 1's
           date comes from ESPN's pro schedule (ADR 0023), is confirmed against MLB
           opening day, and is the date every in-progress snapshot implies;
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
from front_office.espn.rosters import RECHECK_PERIODS, is_closed, is_settled, settled_through
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


def eastern_date_of_epoch_ms(epoch_ms: int) -> dt.date:
    """The Eastern calendar date of an epoch-millisecond instant, as ESPN stamps a game."""
    instant = dt.datetime.fromtimestamp(epoch_ms // 1000, tz=dt.UTC)
    return instant.astimezone(EASTERN).date()


def end_of_eastern_day(day: dt.date) -> dt.datetime:
    """The first instant after `day` ends in Eastern time, as an aware UTC instant."""
    midnight = dt.datetime.combine(day + dt.timedelta(days=1), dt.time.min, tzinfo=EASTERN)
    return midnight.astimezone(dt.UTC)


def run_audit(
    zone: LandingZone,
    con: duckdb.DuckDBPyConnection | None,
    *,
    season: int,
    as_of: dt.datetime,
) -> list[Finding]:
    """Every check, in order. `con` is None when there is no warehouse to check."""
    findings, captures = check_landing(zone)
    if con is None:
        findings.append(
            Finding(Severity.ERROR, "loaded", QUALIFIED, "no warehouse; run `front-office load`")
        )
    else:
        findings += check_loaded(zone, captures, con)
    mlb_findings, opening_day = check_mlb(zone, captures, season=season, as_of=as_of)
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
    """Anything waiting in quarantine is a warning: someone should look, then clear it.

    An item is a file or a directory holding nothing (a swept directory is evidence too); a
    run directory that is itself empty counts as one item."""
    try:
        held = sorted(p for p in zone.quarantine_root.iterdir() if p.name != ".gitignore")
    except VANISHED:
        return []
    if not held:
        return []
    items = sum(_quarantined_items(run) for run in held)
    runs = ", ".join(p.name for p in held)
    return [
        Finding(
            Severity.WARN,
            "landing",
            "quarantine",
            f"{items} item(s) in {len(held)} run director(y/ies) of {zone.quarantine_root}: "
            f"{runs}; look, then clear by hand",
        )
    ]


def _quarantined_items(run: Path) -> int:
    if not run.is_dir():
        return 1
    below = list(run.rglob("*"))
    if not below:
        return 1
    # Anything that is not a directory is an item, whatever it is (a file, a symlink, even
    # a dangling one); a directory is an item only when it holds nothing.
    return sum(1 for p in below if p.is_symlink() or not p.is_dir() or not any(p.iterdir()))


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
    zone: LandingZone, captures: list[Capture], *, season: int, as_of: dt.datetime
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

    # Unplayed games need an explicit disposition, not silence.
    last_state: dict[int, str] = {}
    for day in schedule.payload().get("dates", []):
        for entry in day.get("games", []):
            pk = int(entry["gamePk"])
            last_state[pk] = entry.get("status", {}).get("detailedState", "")
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

    # Settlement is judged by the fetch logic's own functions, over the captures held here.
    closed, pending, before_start, no_start, unreadable, unstamped = [], 0, [], [], 0, []
    for game in played:
        if game.game_pk not in boxscores:
            continue
        # A stamp that does not parse is no evidence, as in the backfill's capture_stamps.
        stamps = []
        for stamp in boxscores[game.game_pk]:
            try:
                stamps.append(mlb_boxscore.parse_stamp(stamp))
            except ValueError:
                unreadable += 1
        first = mlb_boxscore.first_final(stamps, game.last_start)
        # Two independent faults, each reported whatever the other is: no readable start,
        # and no readable stamp. Only a game with both a start and a stamp is compared.
        if game.last_start is None:
            no_start.append(game.game_pk)
        if not stamps:
            unstamped.append(game.game_pk)
        if game.last_start is None or not stamps:
            continue
        if first is None:
            before_start.append(game.game_pk)
        elif mlb_boxscore.is_settled(stamps, game.last_start):
            continue
        elif first + mlb_boxscore.SETTLE_WINDOW <= as_of:
            closed.append(game.game_pk)
        else:
            pending += 1
    if closed:
        findings.append(
            Finding(
                Severity.WARN,
                "mlb",
                subject,
                f"{len(closed)} game(s) not captured after their settle window closed; a late "
                f"correction may be missing (review R4). Run "
                f"`front-office backfill mlb --season {season}`; {_sample(map(str, closed))}",
            )
        )
    if pending:
        findings.append(
            Finding(Severity.INFO, "mlb", subject, f"{pending} game(s) still in settle window")
        )
    if before_start:
        findings.append(
            Finding(
                Severity.WARN,
                "mlb",
                subject,
                f"{len(before_start)} game(s) captured only before their last scheduled start; "
                f"{_sample(map(str, before_start))}",
            )
        )
    if no_start:
        findings.append(
            Finding(
                Severity.WARN,
                "mlb",
                subject,
                f"{len(no_start)} game(s) with an unreadable gameDate in the schedule, so no "
                f"last scheduled start: they cannot settle; {_sample(map(str, no_start))}",
            )
        )
    if unreadable:
        findings.append(
            Finding(
                Severity.WARN,
                "mlb",
                subject,
                f"{unreadable} boxscore capture(s) with a fetched_at that is not a UTC stamp; "
                "not counted as settle evidence"
                + (
                    f"; {len(unstamped)} game(s) have no other capture, so cannot settle; "
                    f"{_sample(map(str, unstamped))}"
                    if unstamped
                    else ""
                ),
            )
        )
    # Opening day is the model's rule (stg_espn__scoring_periods over stg_mlb__games): each
    # game counts once, at the official date of its played or still-scheduled entry when it
    # has one, so a postponed opener is dated by its makeup. Played or not, so the date
    # exists before the first pitch.
    official_dates: dict[int, tuple[bool, dt.date]] = {}
    for day in schedule.payload().get("dates", []):
        for entry in day.get("games", []):
            official_date = entry.get("officialDate")
            if not isinstance(official_date, str):
                continue
            pk = int(entry["gamePk"])
            not_played = entry.get("status", {}).get("detailedState", "") in mlb_boxscore.NOT_PLAYED
            if pk not in official_dates or (official_dates[pk][0] and not not_played):
                official_dates[pk] = (not_played, dt.date.fromisoformat(official_date))
    opening_day = min((date for _, date in official_dates.values()), default=None)
    return findings, opening_day


# -- espn ------------------------------------------------------------------------------


@dataclass(frozen=True)
class ProSchedule:
    """What the newest pro schedule capture says about period 1, read once per season.

    `capture` is None when none is landed. `dates` maps each implied period-1 date to its
    number of distinct games; `period_one` is set only when there is exactly one."""

    capture: Capture | None
    dates: Mapping[dt.date, int]

    @property
    def games(self) -> int:
        return sum(self.dates.values())

    @property
    def period_one(self) -> dt.date | None:
        return next(iter(self.dates)) if len(self.dates) == 1 else None


def pro_schedule_dates(payload: Any) -> dict[dt.date, int]:
    """Period 1's date implied by each distinct game, with the number of games implying it.

    Mirrors stg_espn__pro_games and stg_espn__scoring_periods: the Eastern date of the
    game's `date` minus (`scoringPeriodId` - 1) days. A game is listed under both its teams,
    so games are distinct by (id, date, period). A shape the model could not read is
    skipped, not an error: a schedule left with no game then dates nothing.
    """
    settings = payload.get("settings") if isinstance(payload, dict) else None
    teams = settings.get("proTeams") if isinstance(settings, dict) else None
    games: set[tuple[str, int, int]] = set()
    for team in teams if isinstance(teams, list) else []:
        by_period = team.get("proGamesByScoringPeriod") if isinstance(team, dict) else None
        for listed in by_period.values() if isinstance(by_period, dict) else []:
            for game in listed if isinstance(listed, list) else []:
                if not isinstance(game, dict):
                    continue
                date, period = game.get("date"), game.get("scoringPeriodId")
                if (
                    isinstance(date, int)
                    and isinstance(period, int)
                    and not isinstance(date, bool)
                    and not isinstance(period, bool)
                ):
                    games.add((str(game.get("id")), date, period))
    counts: Counter[dt.date] = Counter(
        eastern_date_of_epoch_ms(date) - dt.timedelta(days=period - 1) for _, date, period in games
    )
    return dict(sorted(counts.items()))


def check_espn(
    captures: list[Capture], *, season: int, opening_day: dt.date | None
) -> list[Finding]:
    """Roster finality, calendar anchor and league-snapshot completeness, per league.

    The pro schedule is a fact about the season, so it is read once; its findings are
    reported once per league, under that league's subject, like the other ESPN findings.
    """
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
    newest = _newest(captures, "espn", "pro_schedule", season=str(season))
    schedule = ProSchedule(newest, {} if newest is None else pro_schedule_dates(newest.payload()))
    findings = []
    for league_id in leagues:
        findings += _check_league(
            captures,
            season=season,
            league_id=league_id,
            schedule=schedule,
            opening_day=opening_day,
        )
    return findings


def _schedule_findings(
    subject: str, schedule: ProSchedule, opening_day: dt.date | None
) -> list[Finding]:
    """The pro schedule's own findings (R5.1, R5.3, R5.4); a date is used only if clean."""
    capture = schedule.capture
    if capture is None:
        return [
            Finding(
                Severity.ERROR,
                "espn",
                subject,
                "no committed pro schedule capture, so scoring periods cannot be dated",
            )
        ]
    stamp = capture.fetched_at
    if not schedule.dates:
        return [
            Finding(
                Severity.ERROR,
                "espn",
                subject,
                f"pro schedule {stamp} dates nothing: it holds no game with a usable date "
                "and scoringPeriodId",
            )
        ]
    if schedule.period_one is None:
        listed = ", ".join(f"{date} ({n} game(s))" for date, n in schedule.dates.items())
        return [
            Finding(
                Severity.ERROR,
                "espn",
                subject,
                f"pro schedule {stamp}: games imply different dates for period 1: {listed}",
            )
        ]
    period_one = schedule.period_one
    named = f"period 1 = {period_one} per ESPN's schedule ({stamp}, {schedule.games} games)"
    if opening_day is None:
        return [
            Finding(Severity.INFO, "espn", subject, named),
            Finding(
                Severity.WARN,
                "espn",
                subject,
                "no MLB schedule to confirm period 1 against; its date rests on ESPN's schedule",
            ),
        ]
    if opening_day != period_one:
        return [
            Finding(
                Severity.ERROR,
                "espn",
                subject,
                f"period 1 = {period_one} per ESPN's schedule, but MLB opening day is "
                f"{opening_day}",
            )
        ]
    return [Finding(Severity.INFO, "espn", subject, f"{named}, and it is MLB opening day")]


def _check_league(
    captures: list[Capture],
    *,
    season: int,
    league_id: str,
    schedule: ProSchedule,
    opening_day: dt.date | None,
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
    # A status that is not an object is kept as an empty one: it has no counters, and is
    # reported with the other unusable ones below.
    status_by_run = {
        capture.fetched_at: status if isinstance(status, dict) else {}
        for capture in league
        if capture.endpoint == "settings"
        for status in [capture.payload().get("status")]
    }
    findings = []

    def transaction_findings() -> list[Finding]:
        # Independent of the league status, so it runs whatever the status says.
        transactions = _newest(league, "espn", "transactions")
        if transactions is None:
            return []
        pages = [
            capture
            for capture in league
            if (capture.source, capture.endpoint) == ("espn", "transactions")
            and capture.fetched_at == transactions.fetched_at
        ]
        return _check_transactions(pages, subject)

    # The scoring-date anchor: an in-progress snapshot implies a date for period 1, which must
    # be the one ESPN's pro schedule gives or the model's dates shift. Only in-progress
    # snapshots are compared: ESPN's game-wide counter stops one past the last day with a pro
    # game, so after the final period it is not a date (ADR 0022).
    in_progress: dict[str, int] = {}
    past_final = []
    unreadable = []
    for stamp, status in sorted(status_by_run.items()):
        latest_period = status.get("latestScoringPeriod")
        final_period = status.get("finalScoringPeriod")
        if (
            not isinstance(latest_period, int)
            or not isinstance(final_period, int)
            or isinstance(latest_period, bool)
            or isinstance(final_period, bool)
        ):
            unreadable.append(stamp)
        elif latest_period <= final_period:
            in_progress[stamp] = latest_period
        else:
            past_final.append(stamp)
    if unreadable:
        findings.append(
            Finding(
                Severity.WARN,
                "espn",
                subject,
                f"{len(unreadable)} settings capture(s) with an unusable latestScoringPeriod or "
                f"finalScoringPeriod, so not dated; {_sample(unreadable)}",
            )
        )
    findings += _schedule_findings(subject, schedule, opening_day)
    period_one = schedule.period_one
    if period_one is not None:
        implied = {
            stamp: eastern_date(stamp) - dt.timedelta(days=latest_period - 1)
            for stamp, latest_period in in_progress.items()
        }
        off = {stamp: date for stamp, date in implied.items() if date != period_one}
        if off:
            detail = ", ".join(f"{stamp} -> {date}" for stamp, date in sorted(off.items()))
            findings.append(
                Finding(
                    Severity.ERROR,
                    "espn",
                    subject,
                    f"in-progress settings capture(s) imply a period 1 other than ESPN's "
                    f"schedule gives ({detail}); the schedule gives {period_one}",
                )
            )
        elif implied:
            findings.append(
                Finding(
                    Severity.INFO,
                    "espn",
                    subject,
                    f"{len(implied)} in-progress settings capture(s) imply period 1 = "
                    f"{period_one}, as ESPN's schedule gives",
                )
            )
    if past_final:
        findings.append(
            Finding(
                Severity.INFO,
                "espn",
                subject,
                f"{len(past_final)} settings capture(s) taken after the final period; their "
                "period counter is not compared with a date",
            )
        )

    newest_run = max(status_by_run)
    if newest_run in unreadable:
        # Everything below is judged from the newest status. Without its counters the audit
        # cannot say which periods exist or whether the season is over, and says so.
        findings.append(
            Finding(
                Severity.ERROR,
                "espn",
                subject,
                f"the newest settings capture ({newest_run}) has no usable period counters; "
                "roster finality and league snapshots are not checked",
            )
        )
        return findings + transaction_findings()
    newest_status = status_by_run[newest_run]
    latest = int(newest_status.get("latestScoringPeriod", 0))
    final = int(newest_status.get("finalScoringPeriod", latest))
    first = int(newest_status.get("firstScoringPeriod", 1))
    season_over = latest > final

    # The same function the fetch logic uses decides which rosters are closed, so the two
    # cannot disagree (ADR 0016). A settings capture counts only with an integer counter.
    settings_latest_by_run: dict[str, int] = {
        run: status["latestScoringPeriod"]
        for run, status in status_by_run.items()
        if isinstance(status.get("latestScoringPeriod"), int)
        and not isinstance(status.get("latestScoringPeriod"), bool)
    }

    def closed_at_run(run: str, period: int) -> bool:
        # A run whose settings counter is unusable is not shown to postdate anything.
        return settings_latest_by_run.get(run, 0) > period

    evidence = settled_through(
        [capture.meta for capture in league if capture.endpoint == "roster"],
        settings_latest_by_run,
    )
    captured = {
        int(capture.partition("scoring_period") or 0)
        for capture in league
        if capture.endpoint == "roster"
    }
    required = range(first, min(latest, final) + 1)
    missing = [period for period in required if period not in captured]
    unproven = [
        period for period in required if period in captured and not is_closed(period, evidence)
    ]
    rechecking = [
        period
        for period in required
        if is_closed(period, evidence) and not is_settled(period, evidence)
    ]
    # Every required period, a missing roster included: the closing refresh must cover them all.
    unclosed_season = [period for period in required if evidence.get(period, 0) <= final]
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
                f"{len(unproven)} roster(s) with no capture shown final "
                f"(review R1); {_sample(map(str, unproven))}",
            )
        )
    if rechecking:
        findings.append(
            Finding(
                Severity.INFO,
                "espn",
                subject,
                f"{len(rechecking)} closed roster period(s) inside the {RECHECK_PERIODS}-period "
                f"re-check window; the next run fetches them again; "
                f"{_sample(map(str, rechecking))}",
            )
        )
    if season_over and unclosed_season:
        findings.append(
            Finding(
                Severity.WARN,
                "espn",
                subject,
                f"{len(unclosed_season)} scoring period(s) with no roster captured after the "
                f"final scoring period: {_ranges(unclosed_season)}; run `front-office backfill "
                f"espn --season {season} --refresh` to close the season",
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

    return findings + transaction_findings()


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


def _ranges(periods: Iterable[int]) -> str:
    """Every number, with consecutive runs folded: [1, 2, 3, 7] -> "1-3, 7"."""
    runs: list[list[int]] = []
    for period in sorted(periods):
        if runs and period == runs[-1][1] + 1:
            runs[-1][1] = period
        else:
            runs.append([period, period])
    return ", ".join(str(lo) if lo == hi else f"{lo}-{hi}" for lo, hi in runs)


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
