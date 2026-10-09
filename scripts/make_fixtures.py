"""Build the committed CI fixture landing zone from real landed data.

Fixtures are rebuilt from an ALLOWLIST of the fields staging actually reads -- never by
scrubbing a full payload. A denylist would eventually miss a field, and for ESPN that
means a league member's name landing in a public repo. Rebuilding cannot leak a field
nobody listed.

Reads the real landing zone through LandingZone.committed (so only committed captures,
whatever else is lying around) and writes each fixture as a capture directory,
`fetched_at=<stamp>/payload.json` beside `meta.json`, with the sidecar as it always was.
The real landing zone must already be in the directory layout (ADR 0014).

Usage:  uv run python scripts/make_fixtures.py [--date 2026-04-30]
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, NamedTuple
from zoneinfo import ZoneInfo

from front_office.landing import LandingZone

REPO_ROOT = Path(__file__).resolve().parent.parent
RAW_ROOT = REPO_ROOT / "data/raw"
FIXTURE_ROOT = REPO_ROOT / "fixtures/landing"

# A fixed stamp: fixtures are regenerated on purpose, and a moving fetched_at would
# churn the committed diff on every run.
#
# The stamp is the Eastern afternoon of the LAST fixture game date, 2026-04-30. Scoring
# periods are no longer dated from it: stg_espn__scoring_periods counts from the period-1
# date the pro schedule fixture implies (ADR 0023). The pro schedule and the rosters are
# both built from the real periods of the three MLB fixture dates, so the season is seven
# periods, 2026-04-24 to 2026-04-30, with data on periods 1, 6 and 7, matching the MLB
# fixture games (#74, ADR 0025, ADR 0030). The stamp itself stays, because changing it
# would rename every fixture capture.
FIXTURE_FETCHED_AT = "20260430T160000Z"

# Game 823471 was postponed on 2026-04-29 and made up on 2026-04-30. The schedule files
# the postponed copy under the ORIGINAL calendar date and the makeup under the new one,
# both sharing one game_pk, so capturing both days exercises the stg_mlb__games dedupe
# tie-break in CI rather than only locally.
#
# 2026-04-24 is the earlier day (#93, ADR 0030): a starter's previous turn comes five or six
# days before his next, so the fixture season has to run from that day to carry a start the
# start replacement level can use. The four days between have no data. The last two dates
# are the days the ordinary boxscores come from.
DEFAULT_DATES = ("2026-04-24", "2026-04-29", "2026-04-30")

# Dotted paths, relative to one game object in the schedule payload.
SCHEDULE_GAME_FIELDS = (
    "gamePk",
    "gameGuid",
    "gameType",
    "season",
    "gameDate",
    "officialDate",
    "gameNumber",
    "doubleHeader",
    "dayNight",
    "rescheduledFrom",
    "resumedFrom",
    "status.abstractGameState",
    "status.detailedState",
    "teams.home.team.id",
    "teams.home.team.name",
    "teams.home.score",
    "teams.home.isWinner",
    "teams.away.team.id",
    "teams.away.team.name",
    "teams.away.score",
    "teams.away.isWinner",
    "venue.id",
    "venue.name",
)


# Per-player fields read by stg_mlb__batting_game_logs / stg_mlb__pitching_game_logs.
BOXSCORE_PLAYER_FIELDS = (
    "person.id",
    "person.fullName",
    "position.abbreviation",
    "battingOrder",
    "gameStatus.isSubstitute",
    "stats.batting.gamesPlayed",
    "stats.batting.plateAppearances",
    "stats.batting.atBats",
    "stats.batting.hits",
    "stats.batting.doubles",
    "stats.batting.triples",
    "stats.batting.homeRuns",
    "stats.batting.runs",
    "stats.batting.rbi",
    "stats.batting.baseOnBalls",
    "stats.batting.intentionalWalks",
    "stats.batting.strikeOuts",
    "stats.batting.stolenBases",
    "stats.batting.caughtStealing",
    "stats.batting.hitByPitch",
    "stats.batting.sacFlies",
    "stats.batting.sacBunts",
    "stats.batting.totalBases",
    "stats.batting.groundIntoDoublePlay",
    "stats.batting.catchersInterference",
    "stats.pitching.gamesPitched",
    "stats.pitching.gamesStarted",
    "stats.pitching.outs",
    "stats.pitching.inningsPitched",
    "stats.pitching.battersFaced",
    "stats.pitching.hits",
    "stats.pitching.runs",
    "stats.pitching.earnedRuns",
    "stats.pitching.homeRuns",
    "stats.pitching.baseOnBalls",
    "stats.pitching.intentionalWalks",
    "stats.pitching.strikeOuts",
    "stats.pitching.hitBatsmen",
    "stats.pitching.balks",
    "stats.pitching.wildPitches",
    "stats.pitching.pitchesThrown",
    "stats.pitching.inheritedRunners",
    "stats.pitching.wins",
    "stats.pitching.losses",
    "stats.pitching.saves",
    "stats.pitching.saveOpportunities",
    "stats.pitching.holds",
    "stats.pitching.blownSaves",
    "stats.pitching.completeGames",
    "stats.pitching.shutouts",
)

# Team-side totals read by the stg_mlb__batting_totals_match_team_stats test. Only the
# totals it compares: the rest of teamStats is not needed, so it is not copied.
BOXSCORE_TEAM_STATS_FIELDS = (
    "teamStats.batting.hits",
    "teamStats.batting.runs",
    "teamStats.batting.atBats",
)

# A later snapshot of the first fixture game, shaped like an official scorer's
# correction: one home batter gains a hit, one away batter's appearance is taken away,
# and both teams' totals follow. It proves staging reads only the latest snapshot (the
# removed appearance must not survive from the earlier one) and that the batting totals
# test judges that snapshot, so a legitimate correction does not fail it. Synthetic by
# design: a real correction may not exist on the fixture dates.
CORRECTION_FETCHED_AT = "20260502T160000Z"

# Two games keep the committed fixture small while still covering both sides, batters,
# pitchers and the relationship back to stg_mlb__games.
FIXTURE_BOXSCORE_GAMES = 2

# Boston's game of 2026-04-24, one rotation turn before fixture game 822821, in which free
# agent 678394 starts (ADR 0030, #93). Named, not searched for: a search would pick another
# game when the landing zone changes and move every fixture with it. Written after the
# ordinary games; generation checks that it does its job.
FIXTURE_HISTORY_GAME_PKS = (824854,)

# ESPN fixtures are committed to a public repo, so identifying text is replaced at
# GENERATION time, not at query time. dbt's anonymize var protects query output; it
# cannot protect a file. League members never agreed to appear here.
FIXTURE_LEAGUE_ID = "111111"
FIXTURE_LEAGUE_NAME = "Fixture League"

# The real scoring periods of DEFAULT_DATES (2026-04-24, 04-29 and 04-30), used for the
# rosters AND the pro schedule, RENUMBERED by offset from the first (31 -> 1, 36 -> 6,
# 37 -> 7) so the fixture season is self-consistent: seven consecutive periods, the four
# between with no data. Generation checks that they fall on the MLB fixture dates (ADR 0025).
FIXTURE_SOURCE_SCORING_PERIODS = (31, 36, 37)

# The only season the fixtures are built from: a capture of another season is never chosen.
FIXTURE_SEASON = 2026
EASTERN = ZoneInfo("America/New_York")


class PastSeason(NamedTuple):
    """A past season of the fixtures: settings, matchups and the two calendars, no rosters.

    The periods are real and keep their numbers (2025's first two are the Tokyo games), so
    nothing is renumbered. The stamp is the Eastern afternoon of the last date, as
    FIXTURE_FETCHED_AT is for 2026 (spec 0085, R3).
    """

    season: int
    source_periods: tuple[int, ...]
    dates: tuple[str, ...]
    fetched_at: str


PAST_SEASONS = (PastSeason(2025, (1, 2), ("2025-03-18", "2025-03-19"), "20250319T160000Z"),)

ESPN_PRO_GAME_FIELDS = ("id", "date", "scoringPeriodId", "homeProTeamId", "awayProTeamId")

ESPN_SETTINGS_FIELDS = (
    "id",
    "seasonId",
    "scoringPeriodId",
    "settings.name",
    "settings.size",
    "settings.scoringSettings.scoringType",
    "settings.scheduleSettings.playoffTeamCount",
    "status.currentMatchupPeriod",
    "status.latestScoringPeriod",
    "status.finalScoringPeriod",
    "status.isActive",
    # Slot id -> roster spot count. Read by stg_espn__lineup_slot_limits.
    "settings.rosterSettings.lineupSlotCounts",
)
ESPN_SCORING_ITEM_FIELDS = ("statId", "isReverseItem", "points")
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
# Matchup numbers only. scoreByStat is copied wholesale: it is stat ids and numbers.
ESPN_MATCHUP_FIELDS = (
    "id",
    "matchupPeriodId",
    "winner",
    "playoffTierType",
    "home.teamId",
    "home.cumulativeScore.wins",
    "home.cumulativeScore.losses",
    "home.cumulativeScore.ties",
    "home.cumulativeScore.scoreByStat",
    "away.teamId",
    "away.cumulativeScore.wins",
    "away.cumulativeScore.losses",
    "away.cumulativeScore.ties",
    "away.cumulativeScore.scoreByStat",
    # Scoring period -> points, keyed by scoring period id. The KEYS, not the point
    # values, are what stg_espn__matchup_periods reads: they are the period-to-day map.
    "home.pointsByScoringPeriod",
    "away.pointsByScoringPeriod",
)
FIXTURE_MATCHUPS = 2

# Transaction messages: what moved, where to. `for` is the acting team on a type-239 drop
# (ADR 0004). Never `author`, which is the ESPN account GUID of the member who made the move.
ESPN_TRANSACTION_MESSAGE_FIELDS = ("date", "messageTypeId", "targetId", "to", "from", "for")
FIXTURE_TRANSACTION_TOPICS = 6
# Message types that move a player, per dbt/seeds/espn_activity_types.csv. The fixture
# takes topics carrying one of these, plus one topic of lineup moves only (type 188), so
# CI exercises staging's exclusion of non-transactions from the unfiltered log (#26).
ESPN_TRANSACTION_TYPES = frozenset({178, 179, 180, 181, 239, 244})

# SFBB crosswalk columns. Player names here are public major leaguers.
IDMAP_FIELDS = ("PLAYERNAME", "MLBID", "ESPNID", "TEAM", "POS", "IDFANGRAPHS")

ESPN_ROSTER_ENTRY_FIELDS = (
    "playerId",
    "lineupSlotId",
    "injuryStatus",
    "acquisitionType",
    "playerPoolEntry.player.fullName",
    "playerPoolEntry.player.defaultPositionId",
    "playerPoolEntry.player.proTeamId",
    # Slot ids a player is eligible for. Read by stg_espn__roster_entry_slots.
    "playerPoolEntry.player.eligibleSlots",
)

# A player's single-game line in a roster entry. Rebuilt from this list, never scrubbed: the
# real line also has id, proTeamId, seasonId, appliedTotal and appliedStats. `stats` is ESPN's
# map from stat id to number, copied whole, as scoreByStat is in the matchup fixture.
ESPN_STAT_LINE_FIELDS = (
    "scoringPeriodId",
    "statSourceId",
    "statSplitTypeId",
    "externalId",
    "stats",
)
# What stg_espn__player_game_stats keeps: actuals (source 0) of a single game (split type 5).
ESPN_STAT_LINE_SOURCE = 0
ESPN_STAT_LINE_SPLIT = 5


def fixture_period_number(source_period: int, source_periods: tuple[int, ...]) -> int:
    """A source period's fixture number: its distance from the first, plus one."""
    return source_period - source_periods[0] + 1


def fixture_span(source_periods: tuple[int, ...]) -> int:
    """How many consecutive fixture periods the source periods cover, gaps included."""
    return source_periods[-1] - source_periods[0] + 1


def pick(source: dict[str, Any], dotted: str) -> tuple[list[str], Any] | None:
    """Return (path, value) for a dotted path, or None when absent."""
    parts = dotted.split(".")
    node: Any = source
    for part in parts:
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return parts, node


def rebuild(source: dict[str, Any], fields: tuple[str, ...]) -> dict[str, Any]:
    """Build a new object containing only the allowlisted fields that exist."""
    out: dict[str, Any] = {}
    for dotted in fields:
        found = pick(source, dotted)
        if found is None:
            continue
        parts, value = found
        cursor = out
        for part in parts[:-1]:
            cursor = cursor.setdefault(part, {})
        cursor[parts[-1]] = value
    return out


def landed(source: str, endpoint: str, **partitions: Any) -> list[Path]:
    """payload.json of every committed capture of an endpoint (or one entity), by path.

    The real root is looked up on each call, not at import, so a test can point it elsewhere.
    """
    zone = LandingZone(RAW_ROOT)
    return [
        capture.payload_path
        for capture in zone.committed(
            source=source, endpoint=endpoint, partitions=partitions or None
        )
    ]


def landed_in(source: str, endpoint: str, **partitions: Any) -> list[Path]:
    """payload.json of every committed capture whose sidecar partitions include these.

    `committed(partitions=...)` reads one exact folder, so a partial match (a season, say,
    across every league and period) is the sidecar's own partitions, over `committed`.
    """
    return [
        capture.payload_path
        for capture in LandingZone(RAW_ROOT).committed(source=source, endpoint=endpoint)
        if all(capture.meta.get("partitions", {}).get(k) == v for k, v in partitions.items())
    ]


def latest_landed(source: str, endpoint: str) -> Path:
    candidates = landed(source, endpoint)
    if not candidates:
        raise SystemExit(f"no landed {source}/{endpoint} responses under {RAW_ROOT}")
    return candidates[-1]


def latest_schedule(season: int) -> Path:
    """payload.json of the newest committed regular-season MLB schedule of one season."""
    candidates = landed_in("mlb", "schedule", season=season, game_type="R")
    if not candidates:
        raise SystemExit(f"no landed mlb/schedule response for {season} under {RAW_ROOT}")
    return sorted(candidates)[-1]


def write_fixture(
    *,
    source: str,
    endpoint: str,
    partitions: dict[str, Any],
    payload: Any,
    request: dict[str, Any],
    fetched_at: str = FIXTURE_FETCHED_AT,
) -> Path:
    path = FIXTURE_ROOT / source / endpoint
    for key, value in partitions.items():
        path = path / f"{key}={value}"
    path = path / f"fetched_at={fetched_at}"
    path.mkdir(parents=True, exist_ok=True)
    payload_path = path / "payload.json"
    payload_path.write_text(json.dumps(payload, indent=1) + "\n")
    meta = {
        "source": source,
        "endpoint": endpoint,
        "partitions": partitions,
        "url": request["url"],
        "params": request["params"],
        "request_key": "&".join(f"{k}={request['params'][k]}" for k in sorted(request["params"])),
        "fetched_at": fetched_at,
    }
    (path / "meta.json").write_text(json.dumps(meta, indent=2) + "\n")
    return payload_path


def build_mlb_schedule(
    dates: tuple[str, ...],
    season: int = FIXTURE_SEASON,
    fetched_at: str = FIXTURE_FETCHED_AT,
) -> Path:
    payload = json.loads(latest_schedule(season).read_text())
    days = [day for day in payload["dates"] if day["date"] in dates]
    if not days:
        raise SystemExit(f"no games found on {', '.join(dates)} in the landed schedule")
    fixture = {
        "dates": [
            {
                "date": day["date"],
                "games": [rebuild(game, SCHEDULE_GAME_FIELDS) for game in day["games"]],
            }
            for day in days
        ]
    }
    games = sum(len(day["games"]) for day in fixture["dates"])
    game_pks = {game["gamePk"] for day in fixture["dates"] for game in day["games"]}
    path = write_fixture(
        source="mlb",
        endpoint="schedule",
        partitions={"season": season, "game_type": "R"},
        payload=fixture,
        fetched_at=fetched_at,
        request={
            "url": "https://statsapi.mlb.com/api/v1/schedule",
            "params": {
                "sportId": 1,
                "season": season,
                "gameType": "R",
                "startDate": min(dates),
                "endDate": max(dates),
            },
        },
    )
    print(
        f"mlb/schedule: {games} game entries ({len(game_pks)} distinct game_pk) "
        f"on {', '.join(dates)} -> {path.relative_to(REPO_ROOT)}"
    )
    return path


def select_boxscore_games(dates: tuple[str, ...]) -> list[tuple[int, str]]:
    """(game_pk, date) of the ordinary fixture boxscores: the first few played games of the
    LAST TWO fixture dates, by game id.

    The earlier dates are left out on purpose: their lower game ids would displace the
    games the existing fixtures are built on. The earlier day's game is named instead
    (FIXTURE_HISTORY_GAME_PKS).
    """
    schedule = json.loads(latest_schedule(FIXTURE_SEASON).read_text())
    played: dict[int, str] = {}
    for day in schedule["dates"]:
        if day["date"] not in dates[-2:]:
            continue
        for game in day["games"]:
            if game["status"]["detailedState"] == "Final":
                played.setdefault(game["gamePk"], day["date"])
    return sorted(played.items())[:FIXTURE_BOXSCORE_GAMES]


def landed_boxscore_path(game_pk: int) -> Path | None:
    payloads = landed("mlb", "boxscore", season=2026, game_pk=game_pk)
    return payloads[-1] if payloads else None


def write_boxscore(game_pk: int, source: Path) -> Path:
    payload = json.loads(source.read_text())
    fixture = {
        "teams": {
            side: {
                "team": {"id": payload["teams"][side]["team"]["id"]},
                **rebuild(payload["teams"][side], BOXSCORE_TEAM_STATS_FIELDS),
                "players": {
                    key: rebuild(player, BOXSCORE_PLAYER_FIELDS)
                    for key, player in payload["teams"][side]["players"].items()
                },
            }
            for side in ("home", "away")
        }
    }
    path = write_fixture(
        source="mlb",
        endpoint="boxscore",
        partitions={"season": 2026, "game_pk": game_pk},
        payload=fixture,
        request={
            "url": f"https://statsapi.mlb.com/api/v1/game/{game_pk}/boxscore",
            "params": {"gamePk": game_pk},
        },
    )
    players = sum(len(fixture["teams"][s]["players"]) for s in ("home", "away"))
    print(f"mlb/boxscore: game_pk={game_pk}, {players} players -> {path.relative_to(REPO_ROOT)}")
    return path


def build_mlb_boxscores(dates: tuple[str, ...]) -> list[Path]:
    """Boxscores for the first few played games of the last two fixture dates, then the
    named games of the earlier day."""
    history = {pk: landed_boxscore_path(pk) for pk in FIXTURE_HISTORY_GAME_PKS}
    missing = [pk for pk, source in history.items() if source is None]
    if missing:
        raise SystemExit(
            f"mlb/boxscore: the named history game_pk {', '.join(map(str, missing))} is not "
            "landed; the fixture season needs it (ADR 0030)"
        )
    written: list[Path] = []
    for game_pk, _date in select_boxscore_games(dates):
        source = landed_boxscore_path(game_pk)
        if source is None:
            print(f"mlb/boxscore: game_pk={game_pk} not landed yet, skipping")
            continue
        written.append(write_boxscore(game_pk, source))
    first = written[0] if written else None
    for game_pk, source in history.items():
        assert source is not None
        written.append(write_boxscore(game_pk, source))
    if first is not None:
        written.append(write_boxscore_correction(first))
    return written


def corrected_boxscore(payload: dict[str, Any]) -> dict[str, Any]:
    """A copy with one home hit added and one away appearance removed, totals adjusted."""
    corrected = json.loads(json.dumps(payload))
    home, away = corrected["teams"]["home"], corrected["teams"]["away"]
    home_batter = first_batter_with_a_hit(home)
    home_batter["hits"] += 1
    home["teamStats"]["batting"]["hits"] += 1
    away_batter = first_batter_with_a_hit(away)
    for stat in ("hits", "runs", "atBats"):
        away["teamStats"]["batting"][stat] -= away_batter.get(stat, 0)
    away_batter.clear()
    away_batter["gamesPlayed"] = 0
    return corrected


def first_batter_with_a_hit(side: dict[str, Any]) -> dict[str, Any]:
    for key in sorted(side["players"]):
        batting: dict[str, Any] = side["players"][key].get("stats", {}).get("batting", {})
        if batting.get("hits"):
            return batting
    raise SystemExit("no batter with a hit to correct in the first fixture boxscore")


def write_boxscore_correction(original: Path) -> Path:
    meta = json.loads((original.parent / "meta.json").read_text())
    path = write_fixture(
        source="mlb",
        endpoint="boxscore",
        partitions=meta["partitions"],
        payload=corrected_boxscore(json.loads(original.read_text())),
        request={"url": meta["url"], "params": meta["params"]},
        fetched_at=CORRECTION_FETCHED_AT,
    )
    print(f"mlb/boxscore: synthetic correction snapshot -> {path.relative_to(REPO_ROOT)}")
    return path


def espn_team_alias(team_id: int) -> dict[str, str]:
    """Stable, meaningless names for a fixture team."""
    return {"name": f"Team {team_id:02d}", "abbrev": f"T{team_id}"}


def latest_espn(
    endpoint: str, scoring_period: int | None = None, season: int = FIXTURE_SEASON
) -> dict[str, Any]:
    # committed() leaves out anything that is not a complete capture, such as the spike
    # backups, which have no sidecar and a different layout.
    partitions: dict[str, Any] = {"season": season}
    if scoring_period is not None:
        partitions["scoring_period"] = scoring_period
    candidates = landed_in("espn", endpoint, **partitions)
    if not candidates:
        raise SystemExit(
            f"no landed espn/{endpoint} response for {season} (period={scoring_period})"
        )
    return json.loads(sorted(candidates)[-1].read_text())


def check_source_periods_are_the_fixture_dates(
    source_periods: tuple[int, ...], dates: tuple[str, ...], season: int = FIXTURE_SEASON
) -> None:
    """Stop unless each source period's games are all on its fixture date (Eastern), in order.

    Reads the season's landed pro schedule. This is what keeps FIXTURE_SOURCE_SCORING_PERIODS
    and the MLB fixture dates from drifting apart (ADR 0025), and what makes 2025's periods 1
    and 2 the Tokyo dates or no fixture at all (spec 0085, R3.2).
    """
    candidates = landed("espn", "pro_schedule", season=season)
    if not candidates:
        raise SystemExit(
            f"no landed espn/pro_schedule response for {season}: run `front-office backfill`"
        )
    payload = json.loads(sorted(candidates)[-1].read_text())
    found: dict[str, set[str]] = {str(period): set() for period in source_periods}
    for team in payload["settings"]["proTeams"]:
        for period, games in (team.get("proGamesByScoringPeriod") or {}).items():
            if period in found:
                for game in games:
                    local = datetime.fromtimestamp(game["date"] / 1000, UTC).astimezone(EASTERN)
                    found[period].add(local.date().isoformat())
    if len(source_periods) != len(dates):
        raise SystemExit(
            f"{len(source_periods)} source scoring periods but {len(dates)} dates: {dates}"
        )
    for period, wanted in zip(source_periods, dates, strict=True):
        got = sorted(found[str(period)])
        if got != [wanted]:
            raise SystemExit(
                f"{season} scoring period {period}: its games in the landed pro schedule are on "
                f"{', '.join(got) or 'no date'}, but the fixture date wanted is {wanted}"
            )


def check_mlb_has_games_on_the_fixture_dates(
    dates: tuple[str, ...], season: int = FIXTURE_SEASON
) -> None:
    """Stop unless MLB's landed schedule has a regular-season game on every fixture date.

    The ESPN periods are checked against the dates; this checks the dates against MLB, so the
    two calendars of a fixture season agree (spec 0085, R3.2). A date with no regular-season
    game would otherwise give a season whose ESPN periods have nothing to join to.
    """
    payload = json.loads(latest_schedule(season).read_text())
    with_games = {
        day["date"]
        for day in payload["dates"]
        if any(game.get("gameType") == "R" for game in day["games"])
    }
    missing = [date for date in dates if date not in with_games]
    if missing:
        raise SystemExit(
            f"{season}: the landed MLB schedule has no regular-season game on {', '.join(missing)}"
        )


def check_one_league(season: int = FIXTURE_SEASON) -> None:
    """Stop when captures of more than one league are landed for the season (R1.5).

    Every ESPN endpoint counts, not settings alone: a second league with a roster or a
    transaction page and no settings capture would otherwise supply fixture data unnoticed.
    A capture with no league_id, the season-level pro schedule, is no league. Which league's
    rosters are published is a decision, so the script does not choose, and it says how many
    it found, not which.
    """
    leagues = {
        str(capture.meta["partitions"]["league_id"])
        for capture in LandingZone(RAW_ROOT).committed(source="espn")
        if capture.meta.get("partitions", {}).get("season") == season
        and capture.meta["partitions"].get("league_id") is not None
    }
    if len(leagues) > 1:
        raise SystemExit(
            f"{len(leagues)} leagues are landed for season {season}: fixtures are "
            "built from one league, and which one is a decision for the person"
        )


def build_espn_pro_schedule(
    season: int = FIXTURE_SEASON,
    source_periods: tuple[int, ...] = FIXTURE_SOURCE_SCORING_PERIODS,
    fetched_at: str = FIXTURE_FETCHED_AT,
) -> Path:
    """ESPN's pro schedule: teams and games only, the real periods renumbered by offset."""
    candidates = landed("espn", "pro_schedule", season=season)
    if not candidates:
        raise SystemExit(
            f"no landed espn/pro_schedule response for {season}: run `front-office backfill`"
        )
    payload = json.loads(sorted(candidates)[-1].read_text())
    renumber = {
        str(source): str(fixture_period_number(source, source_periods)) for source in source_periods
    }
    teams: list[dict[str, Any]] = []
    for team in payload["settings"]["proTeams"]:
        rebuilt: dict[str, Any] = {"id": team["id"]}
        by_period = team.get("proGamesByScoringPeriod")
        if by_period is not None:
            kept = {
                renumber[period]: [
                    rebuild(game, ESPN_PRO_GAME_FIELDS) | {"scoringPeriodId": int(renumber[period])}
                    for game in games
                ]
                for period, games in by_period.items()
                if period in renumber
            }
            if kept:
                rebuilt["proGamesByScoringPeriod"] = dict(sorted(kept.items()))
        teams.append(rebuilt)
    fixture = {"settings": {"proTeams": teams}}
    path = write_fixture(
        source="espn",
        endpoint="pro_schedule",
        partitions={"season": season},
        payload=fixture,
        fetched_at=fetched_at,
        request={
            "url": f"https://lm-api-reads.fantasy.espn.com/apis/v3/games/flb/seasons/{season}",
            "params": {"view": "proTeamSchedules_wl"},
        },
    )
    game_ids = {
        game["id"]
        for team in teams
        for games in team.get("proGamesByScoringPeriod", {}).values()
        for game in games
    }
    print(
        f"espn/pro_schedule: {len(teams)} teams, {len(game_ids)} distinct games "
        f"-> {path.relative_to(REPO_ROOT)}"
    )
    return path


def build_espn_settings(
    season: int = FIXTURE_SEASON,
    source_periods: tuple[int, ...] = FIXTURE_SOURCE_SCORING_PERIODS,
    fetched_at: str = FIXTURE_FETCHED_AT,
) -> Path:
    payload = latest_espn("settings", season=season)
    fixture = rebuild(payload, ESPN_SETTINGS_FIELDS)
    fixture["id"] = FIXTURE_LEAGUE_ID
    fixture["settings"]["name"] = FIXTURE_LEAGUE_NAME
    # The fixture season is the span of the source periods (seven days for 2026, with data
    # on three); see FIXTURE_FETCHED_AT.
    span = fixture_span(source_periods)
    fixture["scoringPeriodId"] = span
    fixture["status"]["latestScoringPeriod"] = span
    fixture["status"]["finalScoringPeriod"] = span
    fixture["settings"]["scoringSettings"]["scoringItems"] = [
        rebuild(item, ESPN_SCORING_ITEM_FIELDS)
        for item in payload["settings"]["scoringSettings"]["scoringItems"]
    ]
    path = write_fixture(
        source="espn",
        endpoint="settings",
        partitions={"season": season, "league_id": FIXTURE_LEAGUE_ID},
        payload=fixture,
        fetched_at=fetched_at,
        request={
            "url": "https://lm-api-reads.fantasy.espn.com/",
            "params": {"view": "mSettings,mStatus"},
        },
    )
    items = len(fixture["settings"]["scoringSettings"]["scoringItems"])
    print(f"espn/settings: {items} scoring categories -> {path.relative_to(REPO_ROOT)}")
    return path


def build_espn_teams() -> Path:
    payload = latest_espn("teams")
    fixture = {"id": FIXTURE_LEAGUE_ID, "seasonId": payload.get("seasonId"), "teams": []}
    for team in payload["teams"]:
        rebuilt = rebuild(team, ESPN_TEAM_FIELDS)
        rebuilt.update(espn_team_alias(int(team["id"])))
        fixture["teams"].append(rebuilt)
    path = write_fixture(
        source="espn",
        endpoint="teams",
        partitions={"season": 2026, "league_id": FIXTURE_LEAGUE_ID},
        payload=fixture,
        request={"url": "https://lm-api-reads.fantasy.espn.com/", "params": {"view": "mTeam"}},
    )
    print(f"espn/teams: {len(fixture['teams'])} teams (aliased) -> {path.relative_to(REPO_ROOT)}")
    return path


def stat_lines(
    entry: dict[str, Any], source_period: int, fixture_period: int
) -> list[dict[str, Any]]:
    """The player's actual single-game lines for the source period, rebuilt from the allowlist.

    These are the conditions stg_espn__player_game_stats applies, so the fixture keeps what
    the model would keep and nothing else. scoringPeriodId is renumbered to the fixture period.
    """
    lines = entry.get("playerPoolEntry", {}).get("player", {}).get("stats") or []
    return [
        rebuild(line, ESPN_STAT_LINE_FIELDS) | {"scoringPeriodId": fixture_period}
        for line in lines
        if line.get("statSourceId") == ESPN_STAT_LINE_SOURCE
        and line.get("statSplitTypeId") == ESPN_STAT_LINE_SPLIT
        and line.get("scoringPeriodId") == source_period
    ]


def rebuild_roster_entry(
    entry: dict[str, Any], source_period: int, fixture_period: int
) -> dict[str, Any]:
    """A roster entry from the allowlist, plus its game lines when it has any (none: no key)."""
    rebuilt = rebuild(entry, ESPN_ROSTER_ENTRY_FIELDS)
    lines = stat_lines(entry, source_period, fixture_period)
    if lines:
        rebuilt.setdefault("playerPoolEntry", {}).setdefault("player", {})["stats"] = lines
    return rebuilt


def build_espn_rosters() -> list[Path]:
    written: list[Path] = []
    for source_period in FIXTURE_SOURCE_SCORING_PERIODS:
        fixture_period = fixture_period_number(source_period, FIXTURE_SOURCE_SCORING_PERIODS)
        payload = latest_espn("roster", scoring_period=source_period)
        fixture = {
            "id": FIXTURE_LEAGUE_ID,
            "seasonId": payload.get("seasonId"),
            "scoringPeriodId": fixture_period,
            "teams": [
                {
                    "id": team["id"],
                    "roster": {
                        "entries": [
                            rebuild_roster_entry(entry, source_period, fixture_period)
                            for entry in team["roster"]["entries"]
                        ]
                    },
                }
                for team in payload["teams"]
            ],
        }
        path = write_fixture(
            source="espn",
            endpoint="roster",
            partitions={
                "season": 2026,
                "league_id": FIXTURE_LEAGUE_ID,
                "scoring_period": fixture_period,
            },
            payload=fixture,
            request={
                "url": "https://lm-api-reads.fantasy.espn.com/",
                "params": {"view": "mRoster", "scoringPeriodId": fixture_period},
            },
        )
        entries = [e for t in fixture["teams"] for e in t["roster"]["entries"]]
        with_lines = [
            e for e in entries if "stats" in e.get("playerPoolEntry", {}).get("player", {})
        ]
        print(
            f"espn/roster period {fixture_period} (from {source_period}): "
            f"{len(entries)} entries, {len(with_lines)} with game lines "
            f"-> {path.relative_to(REPO_ROOT)}"
        )
        written.append(path)
    return written


def trim_scoring_periods(
    matchup: dict[str, Any], periods: int = fixture_span(FIXTURE_SOURCE_SCORING_PERIODS)
) -> dict[str, Any]:
    """Cut each side's pointsByScoringPeriod down to the fixture's own scoring periods.

    The real matchup this is copied from spans twelve days; the fixture season is seven.
    Left whole, stg_espn__matchup_periods would claim days 3-12 exist and the
    relationships test against stg_espn__scoring_periods would fail on ten phantom days.

    The fixture already renumbers scoring periods (see FIXTURE_SOURCE_SCORING_PERIODS),
    so this is the same fiction applied consistently: one coherent slice, not a real
    matchup with a real matchup's span.
    """
    keep = {str(period) for period in range(1, periods + 1)}
    for side in ("home", "away"):
        points = matchup.get(side, {}).get("pointsByScoringPeriod")
        if points:
            matchup[side]["pointsByScoringPeriod"] = {
                period: value for period, value in points.items() if period in keep
            }
    return matchup


def build_espn_matchups(
    season: int = FIXTURE_SEASON,
    source_periods: tuple[int, ...] = FIXTURE_SOURCE_SCORING_PERIODS,
    fetched_at: str = FIXTURE_FETCHED_AT,
) -> Path:
    payload = latest_espn("matchups", season=season)
    schedule = [
        trim_scoring_periods(rebuild(matchup, ESPN_MATCHUP_FIELDS), fixture_span(source_periods))
        for matchup in payload["schedule"][:FIXTURE_MATCHUPS]
    ]
    fixture = {"id": FIXTURE_LEAGUE_ID, "seasonId": payload.get("seasonId"), "schedule": schedule}
    path = write_fixture(
        source="espn",
        endpoint="matchups",
        partitions={"season": season, "league_id": FIXTURE_LEAGUE_ID},
        payload=fixture,
        fetched_at=fetched_at,
        request={
            "url": "https://lm-api-reads.fantasy.espn.com/",
            "params": {"view": "mMatchupScore,mScoreboard"},
        },
    )
    print(f"espn/matchups: {len(schedule)} matchups -> {path.relative_to(REPO_ROOT)}")
    return path


def newest_transactions_first_page() -> dict[str, Any]:
    """Page 0 (offset=0) of the newest paged transaction run."""
    pages = [
        path
        for path in landed_in("espn", "transactions", season=FIXTURE_SEASON)
        if path.parent.parent.name == "offset=0"
    ]
    if not pages:
        raise SystemExit("no paged espn/transactions capture: run `front-office backfill espn`")
    return json.loads(pages[-1].read_text())


def build_espn_transactions() -> Path:
    payload = newest_transactions_first_page()

    def types(topic: dict[str, Any]) -> set[int]:
        return {message["messageTypeId"] for message in topic["messages"]}

    moves = [t for t in payload["topics"] if types(t) & ESPN_TRANSACTION_TYPES]
    lineup_only = [t for t in payload["topics"] if types(t) == {188}]
    chosen = moves[:FIXTURE_TRANSACTION_TOPICS] + lineup_only[:1]
    topics = []
    for index, topic in enumerate(chosen, start=1):
        # Topic and message ids are themselves GUIDs. They identify transactions rather
        # than people, but synthesising them keeps the fixture privacy check free to
        # reject every GUID-shaped string without exceptions.
        topics.append(
            {
                "id": f"topic-{index:03d}",
                "date": topic["date"],
                "totalMessageCount": topic["totalMessageCount"],
                "messages": [
                    {"id": f"message-{index:03d}-{position:02d}"}
                    | rebuild(message, ESPN_TRANSACTION_MESSAGE_FIELDS)
                    for position, message in enumerate(topic["messages"], start=1)
                ],
            }
        )
    path = write_fixture(
        source="espn",
        endpoint="transactions",
        partitions={"season": 2026, "league_id": FIXTURE_LEAGUE_ID, "offset": 0},
        payload={"topics": topics},
        request={
            "url": "https://lm-api-reads.fantasy.espn.com/",
            "params": {"view": "kona_league_communication", "limit": 2000, "offset": 0},
        },
    )
    messages = sum(len(t["messages"]) for t in topics)
    print(
        f"espn/transactions: {len(topics)} topics, {messages} messages "
        f"-> {path.relative_to(REPO_ROOT)}"
    )
    return path


def build_idmap(fixture_paths: list[Path]) -> Path:
    """Crosswalk rows for exactly the players in the ESPN roster fixtures."""
    wanted: set[str] = set()
    for path in fixture_paths:
        payload = json.loads(path.read_text())
        for team in payload["teams"]:
            for entry in team["roster"]["entries"]:
                wanted.add(str(entry["playerId"]))

    source = latest_landed("idmap", "player_id_map")
    rows = [
        rebuild(row, IDMAP_FIELDS)
        for row in json.loads(source.read_text())
        if row.get("ESPNID") in wanted
    ]
    path = write_fixture(
        source="idmap",
        endpoint="player_id_map",
        partitions={"provider": "sfbb"},
        payload=rows,
        request={
            "url": "https://www.smartfantasybaseball.com/PLAYERIDMAPCSV",
            "params": {"provider": "sfbb"},
        },
    )
    print(
        f"idmap/player_id_map: {len(rows)} of {len(wanted)} fixture players "
        f"-> {path.relative_to(REPO_ROOT)}"
    )
    return path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--dates",
        nargs="+",
        default=list(DEFAULT_DATES),
        help="Schedule dates to capture (calendar dates, not officialDate).",
    )
    args = parser.parse_args()
    dates = tuple(args.dates)
    check_source_periods_are_the_fixture_dates(FIXTURE_SOURCE_SCORING_PERIODS, dates)
    check_one_league()
    # Every check of every season first, so a failing past season leaves no half-written run.
    for past in PAST_SEASONS:
        check_source_periods_are_the_fixture_dates(past.source_periods, past.dates, past.season)
        check_mlb_has_games_on_the_fixture_dates(past.dates, past.season)
        check_one_league(past.season)
    build_mlb_schedule(tuple(args.dates))
    build_mlb_boxscores(tuple(args.dates))
    build_espn_pro_schedule()
    build_espn_settings()
    build_espn_teams()
    roster_paths = build_espn_rosters()
    build_espn_matchups()
    build_espn_transactions()
    build_idmap(roster_paths)
    for past in PAST_SEASONS:
        build_mlb_schedule(past.dates, past.season, past.fetched_at)
        build_espn_pro_schedule(past.season, past.source_periods, past.fetched_at)
        build_espn_settings(past.season, past.source_periods, past.fetched_at)
        build_espn_matchups(past.season, past.source_periods, past.fetched_at)


if __name__ == "__main__":
    main()
