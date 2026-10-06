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
from pathlib import Path
from typing import Any

from front_office.landing import LandingZone

REPO_ROOT = Path(__file__).resolve().parent.parent
RAW_ROOT = REPO_ROOT / "data/raw"
FIXTURE_ROOT = REPO_ROOT / "fixtures/landing"

# A fixed stamp: fixtures are regenerated on purpose, and a moving fetched_at would
# churn the committed diff on every run.
#
# The value matters for more than tidiness. stg_espn__scoring_periods anchors the
# period -> date mapping on the settings snapshot's fetched_at (converted to US/Eastern),
# so this stamp is the Eastern afternoon of the LAST fixture game date. Together with the
# renumbered scoring periods below, that makes the fixture a coherent two-day season:
# period 1 = 2026-04-29, period 2 = 2026-04-30, matching the MLB fixture games.
FIXTURE_FETCHED_AT = "20260430T160000Z"

# Game 823471 was postponed on 2026-04-29 and made up on 2026-04-30. The schedule files
# the postponed copy under the ORIGINAL calendar date and the makeup under the new one,
# both sharing one game_pk, so capturing both days exercises the stg_mlb__games dedupe
# tie-break in CI rather than only locally.
DEFAULT_DATES = ("2026-04-29", "2026-04-30")

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

# ESPN fixtures are committed to a public repo, so identifying text is replaced at
# GENERATION time, not at query time. dbt's anonymize var protects query output; it
# cannot protect a file. League members never agreed to appear here.
FIXTURE_LEAGUE_ID = "111111"
FIXTURE_LEAGUE_NAME = "Fixture League"

# Two adjacent scoring periods, taken from mid-season (real rosters) but RENUMBERED to
# 1 and 2 so the fixture season is self-consistent: two scoring periods covering the two
# MLB fixture dates. Without that, the cross-source "period 1 is opening day" test could
# not run in CI.
FIXTURE_SOURCE_SCORING_PERIODS = (100, 101)

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


def latest_landed(source: str, endpoint: str) -> Path:
    candidates = landed(source, endpoint)
    if not candidates:
        raise SystemExit(f"no landed {source}/{endpoint} responses under {RAW_ROOT}")
    return candidates[-1]


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


def build_mlb_schedule(dates: tuple[str, ...]) -> Path:
    payload = json.loads(latest_landed("mlb", "schedule").read_text())
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
        partitions={"season": 2026, "game_type": "R"},
        payload=fixture,
        request={
            "url": "https://statsapi.mlb.com/api/v1/schedule",
            "params": {
                "sportId": 1,
                "season": 2026,
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


def build_mlb_boxscores(dates: tuple[str, ...]) -> list[Path]:
    """Boxscores for the first few played games on the fixture dates."""
    schedule = json.loads(latest_landed("mlb", "schedule").read_text())
    game_pks = [
        game["gamePk"]
        for day in schedule["dates"]
        if day["date"] in dates
        for game in day["games"]
        if game["status"]["detailedState"] == "Final"
    ]
    written: list[Path] = []
    for game_pk in sorted(set(game_pks))[:FIXTURE_BOXSCORE_GAMES]:
        payloads = landed("mlb", "boxscore", season=2026, game_pk=game_pk)
        if not payloads:
            print(f"mlb/boxscore: game_pk={game_pk} not landed yet, skipping")
            continue
        payload = json.loads(payloads[-1].read_text())
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
        print(
            f"mlb/boxscore: game_pk={game_pk}, {players} players -> {path.relative_to(REPO_ROOT)}"
        )
        written.append(path)
    if written:
        written.append(write_boxscore_correction(written[0]))
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


def latest_espn(endpoint: str, scoring_period: int | None = None) -> dict[str, Any]:
    # committed() leaves out anything that is not a complete capture, such as the spike
    # backups, which have no sidecar and a different layout.
    candidates = [
        path
        for path in landed("espn", endpoint)
        if scoring_period is None or f"scoring_period={scoring_period}/" in str(path)
    ]
    if not candidates:
        raise SystemExit(f"no landed espn/{endpoint} response (period={scoring_period})")
    return json.loads(sorted(candidates)[-1].read_text())


def build_espn_settings() -> Path:
    payload = latest_espn("settings")
    fixture = rebuild(payload, ESPN_SETTINGS_FIELDS)
    fixture["id"] = FIXTURE_LEAGUE_ID
    fixture["settings"]["name"] = FIXTURE_LEAGUE_NAME
    # The fixture season is two days long; see FIXTURE_FETCHED_AT.
    fixture["scoringPeriodId"] = len(FIXTURE_SOURCE_SCORING_PERIODS)
    fixture["status"]["latestScoringPeriod"] = len(FIXTURE_SOURCE_SCORING_PERIODS)
    fixture["status"]["finalScoringPeriod"] = len(FIXTURE_SOURCE_SCORING_PERIODS)
    fixture["settings"]["scoringSettings"]["scoringItems"] = [
        rebuild(item, ESPN_SCORING_ITEM_FIELDS)
        for item in payload["settings"]["scoringSettings"]["scoringItems"]
    ]
    path = write_fixture(
        source="espn",
        endpoint="settings",
        partitions={"season": 2026, "league_id": FIXTURE_LEAGUE_ID},
        payload=fixture,
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


def build_espn_rosters() -> list[Path]:
    written: list[Path] = []
    for fixture_period, source_period in enumerate(FIXTURE_SOURCE_SCORING_PERIODS, start=1):
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
                            rebuild(entry, ESPN_ROSTER_ENTRY_FIELDS)
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
        entries = sum(len(t["roster"]["entries"]) for t in fixture["teams"])
        print(
            f"espn/roster period {fixture_period} (from {source_period}): "
            f"{entries} entries -> {path.relative_to(REPO_ROOT)}"
        )
        written.append(path)
    return written


def trim_scoring_periods(matchup: dict[str, Any]) -> dict[str, Any]:
    """Cut each side's pointsByScoringPeriod down to the fixture's own scoring periods.

    The real matchup this is copied from spans twelve days; the fixture season is two.
    Left whole, stg_espn__matchup_periods would claim days 3-12 exist and the
    relationships test against stg_espn__scoring_periods would fail on ten phantom days.

    The fixture already renumbers scoring periods (see FIXTURE_SOURCE_SCORING_PERIODS),
    so this is the same fiction applied consistently: one coherent slice, not a real
    matchup with a real matchup's span.
    """
    keep = {str(period) for period in range(1, len(FIXTURE_SOURCE_SCORING_PERIODS) + 1)}
    for side in ("home", "away"):
        points = matchup.get(side, {}).get("pointsByScoringPeriod")
        if points:
            matchup[side]["pointsByScoringPeriod"] = {
                period: value for period, value in points.items() if period in keep
            }
    return matchup


def build_espn_matchups() -> Path:
    payload = latest_espn("matchups")
    schedule = [
        trim_scoring_periods(rebuild(matchup, ESPN_MATCHUP_FIELDS))
        for matchup in payload["schedule"][:FIXTURE_MATCHUPS]
    ]
    fixture = {"id": FIXTURE_LEAGUE_ID, "seasonId": payload.get("seasonId"), "schedule": schedule}
    path = write_fixture(
        source="espn",
        endpoint="matchups",
        partitions={"season": 2026, "league_id": FIXTURE_LEAGUE_ID},
        payload=fixture,
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
        path for path in landed("espn", "transactions") if path.parent.parent.name == "offset=0"
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
    build_mlb_schedule(tuple(args.dates))
    build_mlb_boxscores(tuple(args.dates))
    build_espn_settings()
    build_espn_teams()
    roster_paths = build_espn_rosters()
    build_espn_matchups()
    build_espn_transactions()
    build_idmap(roster_paths)


if __name__ == "__main__":
    main()
