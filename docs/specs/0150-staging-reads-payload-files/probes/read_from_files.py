"""Spec 0150 probe: parse the heavy endpoints from the payload files, or from the raw table.

Each probe takes the newest committed capture per entity (league, season and scoring
period for ESPN; game for MLB boxscores), parses it with a declared structure, and returns
a row count and an order-free hash. `files` reads payload.json with DuckDB's read_json;
`table` parses the same captures from raw.api_responses' JSON column, which is how the
staging models read them before this spec. Where a staging model exists, its rows in the
warehouse are hashed the same way, so a match shows the file read gives the model's rows.

    uv run python docs/specs/0150-staging-reads-payload-files/probes/read_from_files.py \
        roster files all 1GB

Run from the repository root, against data/raw and data/warehouse_83.duckdb (read-only).
"""

from __future__ import annotations

import argparse
import resource
import time
from pathlib import Path

import duckdb

from front_office.landing import LandingZone

RAW = Path("data/raw")
WAREHOUSE = "data/warehouse_83.duckdb"

ROSTER_ENTRY = (
    "STRUCT(playerId BIGINT, lineupSlotId BIGINT, injuryStatus VARCHAR, acquisitionType "
    "VARCHAR, playerPoolEntry STRUCT(player STRUCT(fullName VARCHAR, defaultPositionId BIGINT, "
    "proTeamId BIGINT)))"
)
ROSTER_TEAMS = f"STRUCT(id BIGINT, roster STRUCT(entries {ROSTER_ENTRY}[]))[]"
ROSTER_JSON = (
    '[{"id":"BIGINT","roster":{"entries":[{"playerId":"BIGINT","lineupSlotId":"BIGINT",'
    '"injuryStatus":"VARCHAR","acquisitionType":"VARCHAR","playerPoolEntry":{"player":'
    '{"fullName":"VARCHAR","defaultPositionId":"BIGINT","proTeamId":"BIGINT"}}}]}}]'
)
STAT_LINE = (
    "STRUCT(scoringPeriodId BIGINT, statSourceId BIGINT, statSplitTypeId BIGINT, "
    "externalId VARCHAR, stats MAP(VARCHAR, DOUBLE))"
)
STATS_TEAMS = (
    "STRUCT(id BIGINT, roster STRUCT(entries STRUCT(playerId BIGINT, playerPoolEntry "
    f"STRUCT(player STRUCT(stats {STAT_LINE}[])))[]))[]"
)
BATTING = (
    "STRUCT(gamesPlayed BIGINT, atBats BIGINT, hits BIGINT, homeRuns BIGINT, "
    "plateAppearances BIGINT)"
)
BOX_PLAYER = f"STRUCT(person STRUCT(id BIGINT, fullName VARCHAR), stats STRUCT(batting {BATTING}))"
BOX_SIDE = f"STRUCT(team STRUCT(id BIGINT), players MAP(VARCHAR, {BOX_PLAYER}))"
BOX_TEAMS = f"STRUCT(home {BOX_SIDE}, away {BOX_SIDE})"
BOX_JSON = (
    '{"home":{"team":{"id":"BIGINT"},"players":"MAP(VARCHAR, ' + BOX_PLAYER + ')"},'
    '"away":{"team":{"id":"BIGINT"},"players":"MAP(VARCHAR, ' + BOX_PLAYER + ')"}}'
)
MATCHUP_SIDE = "STRUCT(rosterForCurrentScoringPeriod JSON)"
READ = "format = 'auto', records = true, filename = true, maximum_object_size = 33554432"


def newest_captures(source: str, endpoint: str, seasons: str, key: tuple[str, ...]) -> list[Path]:
    """The newest committed capture per entity, through LandingZone (never a glob)."""
    newest: dict[tuple[str, ...], tuple[str, Path]] = {}
    for landed in LandingZone(RAW).iter_landed(source=source, endpoint=endpoint):
        partitions = landed.meta["partitions"]
        if seasons != "all" and int(partitions["season"]) != int(seasons):
            continue
        entity = tuple(str(partitions[name]) for name in key)
        stamp = landed.meta["fetched_at"]
        if entity not in newest or stamp > newest[entity][0]:
            newest[entity] = (stamp, Path(landed.path).resolve())
    return sorted(path for _, path in newest.values())


def roster_sql(method: str) -> str:
    if method == "files":
        header = f"""
            select cast(id as varchar) as league_id, seasonId as season, teams
            from read_json($files, columns = {{'id': 'BIGINT', 'seasonId': 'BIGINT',
                                               'teams': '{ROSTER_TEAMS}'}}, {READ})"""
    else:
        header = f"""
            select json_extract_string(r.payload, '$.id') as league_id,
                   cast(json_extract(r.payload, '$.seasonId') as bigint) as season,
                   from_json(json_extract(r.payload, '$.teams'), '{ROSTER_JSON}') as teams
            from raw.api_responses as r inner join picked using (file_path)
            where r.source = 'espn' and r.endpoint = 'roster'"""
    return f"""
        with header as ({header}),
        teams as (select league_id, season, unnest(teams) as team from header),
        entries as (
            select league_id, season, team.id as team_id, unnest(team.roster.entries) as entry
            from teams
        )
        select count(*), sum(hash(league_id, season, team_id, entry.playerId,
            entry.lineupSlotId, entry.playerPoolEntry.player.fullName,
            entry.playerPoolEntry.player.proTeamId, entry.injuryStatus))
        from entries"""


def boxscore_sql(method: str) -> str:
    if method == "files":
        header = f"""
            select cast(regexp_extract(filename, 'game_pk=([0-9]+)', 1) as bigint) as game_pk,
                   teams
            from read_json($files, columns = {{'teams': '{BOX_TEAMS}'}}, {READ})"""
    else:
        header = f"""
            select cast(regexp_extract(r.file_path, 'game_pk=([0-9]+)', 1) as bigint) as game_pk,
                   from_json(json_extract(r.payload, '$.teams'), '{BOX_JSON}') as teams
            from raw.api_responses as r inner join picked using (file_path)
            where r.source = 'mlb' and r.endpoint = 'boxscore'"""
    return f"""
        with header as ({header}),
        sides as (
            select game_pk, 'home' as side, map_values(teams.home.players) as players
            from header
            union all
            select game_pk, 'away', map_values(teams.away.players) from header
        ),
        players as (select game_pk, side, unnest(players) as player from sides)
        select count(*), sum(hash(game_pk, side, player.person.id,
            player.stats.batting.atBats, player.stats.batting.hits,
            player.stats.batting.homeRuns))
        from players
        where player.stats.batting.gamesPlayed = 1"""


def player_game_stats_sql() -> str:
    return f"""
        with header as (
            select cast(id as varchar) as league_id, seasonId as season,
                   cast(regexp_extract(filename, 'scoring_period=([0-9]+)', 1) as bigint)
                       as scoring_period,
                   teams
            from read_json($files, columns = {{'id': 'BIGINT', 'seasonId': 'BIGINT',
                                               'teams': '{STATS_TEAMS}'}}, {READ})
        ),
        teams as (select league_id, season, scoring_period, unnest(teams) as team from header),
        entries as (
            select league_id, season, scoring_period, team.id as team_id,
                   unnest(team.roster.entries) as entry
            from teams
        ),
        lines as (
            select league_id, season, scoring_period, team_id,
                   entry.playerId as espn_player_id,
                   unnest(entry.playerPoolEntry.player.stats) as line
            from entries
        ),
        game_lines as (
            select league_id, season, team_id, espn_player_id,
                   line.externalId as espn_game_id, line.stats as line_stats
            from lines
            where line.statSourceId = 0 and line.statSplitTypeId = 5
              and line.scoringPeriodId = scoring_period
        ),
        stat_rows as (
            select league_id, season, team_id, espn_player_id, espn_game_id,
                   unnest(map_entries(line_stats)) as stat
            from game_lines
        )
        select count(*), sum(hash(league_id, season, team_id, espn_player_id, espn_game_id,
            cast(stat.key as bigint), stat.value))
        from stat_rows"""


def matchup_days_sql() -> str:
    return f"""
        with header as (
            select cast(id as varchar) as league_id, seasonId as season,
                   cast(regexp_extract(filename, 'scoring_period=([0-9]+)', 1) as bigint)
                       as scoring_period,
                   schedule
            from read_json($files, columns = {{'id': 'BIGINT', 'seasonId': 'BIGINT',
                'schedule': 'STRUCT(matchupPeriodId BIGINT, home {MATCHUP_SIDE},
                                    away {MATCHUP_SIDE})[]'}}, {READ})
        ),
        matchups as (
            select league_id, season, scoring_period, unnest(schedule) as matchup from header
        ),
        marked as (
            select distinct league_id, season, scoring_period,
                   matchup.matchupPeriodId as matchup_period
            from matchups
            where matchup.home.rosterForCurrentScoringPeriod is not null
               or matchup.away.rosterForCurrentScoringPeriod is not null
        )
        select count(*), sum(hash(league_id, season, scoring_period, matchup_period))
        from marked"""


PROBES = {
    # name: (source, endpoint, entity key, model hash query, season column)
    "roster": (
        "espn",
        "roster",
        ("league_id", "season", "scoring_period"),
        "select count(*), sum(hash(league_id, season, team_id, espn_player_id, "
        "lineup_slot_id, player_name, pro_team_id, injury_status)) "
        "from staging.stg_espn__roster_entries",
        "season",
    ),
    "boxscore": (
        "mlb",
        "boxscore",
        ("game_pk",),
        "select count(*), sum(hash(game_pk, side, mlbam_player_id, at_bats, hits, home_runs)) "
        "from staging.stg_mlb__batting_game_logs",
        "year(season_start)",
    ),
    "player_game_stats": (
        "espn",
        "roster",
        ("league_id", "season", "scoring_period"),
        "select count(*), sum(hash(league_id, season, team_id, espn_player_id, espn_game_id, "
        "stat_id, stat_value)) from staging.stg_espn__player_game_stats",
        "season",
    ),
    "matchup_days": (
        "espn",
        "matchup_days",
        ("league_id", "season", "scoring_period"),
        "select count(*), sum(hash(league_id, season, scoring_period, matchup_period)) "
        "from staging.stg_espn__matchup_days",
        "season",
    ),
}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("probe", choices=sorted(PROBES))
    parser.add_argument("method", choices=["files", "table"])
    parser.add_argument("seasons", help="a season, e.g. 2026, or 'all'")
    parser.add_argument("memory_limit", help="DuckDB memory_limit, e.g. 1GB")
    parser.add_argument("--threads", type=int, default=4)
    args = parser.parse_args()

    source, endpoint, key, model_sql, season_column = PROBES[args.probe]
    if args.method == "table" and args.probe not in ("roster", "boxscore"):
        parser.error("the table method is written for roster and boxscore only")
    files = newest_captures(source, endpoint, args.seasons, key)

    con = duckdb.connect(WAREHOUSE, read_only=True)
    con.execute(f"set memory_limit = '{args.memory_limit}'; set threads = {args.threads}")
    if args.method == "table":
        con.execute("create temp table picked (file_path varchar)")
        con.executemany(
            "insert into picked values (?)",
            [(str(path.relative_to(Path.cwd())),) for path in files],
        )
    sql = {
        "roster": lambda: roster_sql(args.method),
        "boxscore": lambda: boxscore_sql(args.method),
        "player_game_stats": player_game_stats_sql,
        "matchup_days": matchup_days_sql,
    }[args.probe]()
    params = {"files": [str(path) for path in files]} if args.method == "files" else None

    started = time.monotonic()
    try:
        count, digest = con.execute(sql, params).fetchone() or (None, None)
        result = f"rows={count} hash={digest}"
    except duckdb.OutOfMemoryException as error:
        result = f"OUT OF MEMORY: {str(error).splitlines()[0][:100]}"
    seconds = time.monotonic() - started
    peak_gb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1048576
    print(
        f"{args.probe} {args.method} seasons={args.seasons} captures={len(files)} "
        f"limit={args.memory_limit} {result} {seconds:.1f}s peak_rss={peak_gb:.2f}GB"
    )
    where = "" if args.seasons == "all" else f" where {season_column} = {int(args.seasons)}"
    model_count, model_digest = con.execute(model_sql + where).fetchone() or (None, None)
    print(f"  model: rows={model_count} hash={model_digest}")


if __name__ == "__main__":
    main()
