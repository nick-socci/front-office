"""Spec 0150 probe (C19, C20): two models' full shapes over every committed capture.

Reads every committed capture of the endpoint through the glob of ADR 0067, then keeps the
newest per entity in one of two ways:

    rank      `qualify row_number()` over the parsed rows (what a window over a capture
              view would do)
    manifest  `row_number()` over the raw table's key columns (stand-in for raw.captures),
              then a semi-join on the path (R3.6)

    uv run python docs/specs/0150-staging-reads-payload-files/probes/full_shape.py \
        player_game_stats manifest 1GB

Run from the repository root, against data/raw and data/warehouse_83.duckdb (read-only).
"""

from __future__ import annotations

import argparse
import resource
import time

import duckdb

WAREHOUSE = "data/warehouse_83.duckdb"
READ = "filename = true, maximum_object_size = 8388608"

LINE = (
    "STRUCT(scoringPeriodId BIGINT, statSourceId BIGINT, statSplitTypeId BIGINT, "
    "externalId VARCHAR, stats MAP(VARCHAR, DOUBLE))"
)
ENTRY = (
    "STRUCT(playerId BIGINT, lineupSlotId BIGINT, injuryStatus VARCHAR, acquisitionType "
    "VARCHAR, playerPoolEntry STRUCT(player STRUCT(fullName VARCHAR, defaultPositionId "
    f"BIGINT, proTeamId BIGINT, eligibleSlots BIGINT[], stats {LINE}[])))"
)
BATTING = (
    "STRUCT(gamesPlayed BIGINT, plateAppearances BIGINT, atBats BIGINT, hits BIGINT, "
    "doubles BIGINT, triples BIGINT, homeRuns BIGINT, runs BIGINT, rbi BIGINT, "
    "baseOnBalls BIGINT, strikeOuts BIGINT, stolenBases BIGINT)"
)
PITCHING = (
    "STRUCT(gamesPlayed BIGINT, outs BIGINT, hits BIGINT, earnedRuns BIGINT, "
    "baseOnBalls BIGINT, strikeOuts BIGINT, wins BIGINT, saves BIGINT)"
)
PLAYER = (
    "STRUCT(person STRUCT(id BIGINT, fullName VARCHAR), position STRUCT(abbreviation "
    "VARCHAR), battingOrder VARCHAR, gameStatus STRUCT(isSubstitute BOOLEAN), "
    f"stats STRUCT(batting {BATTING}, pitching {PITCHING}))"
)
SIDE = (
    "STRUCT(team STRUCT(id BIGINT), teamStats STRUCT(batting STRUCT(hits BIGINT, "
    f"runs BIGINT, atBats BIGINT)), players MAP(VARCHAR, {PLAYER}))"
)

ROSTERS = f"""
    select filename, regexp_extract(filename, 'fetched_at=([^/]+)', 1) as fetched_at,
           cast(id as varchar) as league_id, seasonId as season,
           cast(regexp_extract(filename, 'scoring_period=([0-9]+)', 1) as bigint)
               as scoring_period,
           teams
    from read_json('data/raw/espn/roster/**/fetched_at=*Z/payload.json',
                   columns = {{'id': 'BIGINT', 'seasonId': 'BIGINT',
                               'teams': 'STRUCT(id BIGINT, roster STRUCT(entries {ENTRY}[]))[]'}},
                   {READ})"""
BOXSCORES = f"""
    select filename, regexp_extract(filename, 'fetched_at=([^/]+)', 1) as fetched_at,
           cast(regexp_extract(filename, 'game_pk=([0-9]+)', 1) as bigint) as game_pk, teams
    from read_json('data/raw/mlb/boxscore/**/fetched_at=*Z/payload.json',
                   columns = {{'teams': 'STRUCT(home {SIDE}, away {SIDE})'}}, {READ})"""

LATEST = {
    ("player_game_stats", "rank"): """
        select * from captures
        qualify row_number() over (
            partition by league_id, season, scoring_period
            order by fetched_at desc, filename desc
        ) = 1""",
    ("player_game_stats", "manifest"): """
        select * from captures
        where regexp_extract(filename, 'data/raw/(.*)', 1) in (
            select replace(file_path, 'data/raw/', '')
            from raw.api_responses
            where source = 'espn' and endpoint = 'roster'
            qualify row_number() over (
                partition by json_extract_string(partitions, '$.league_id'),
                             json_extract_string(partitions, '$.season'),
                             json_extract_string(partitions, '$.scoring_period')
                order by fetched_at desc, file_path desc
            ) = 1
        )""",
    ("batting", "rank"): """
        select * from captures
        qualify row_number() over (
            partition by game_pk order by fetched_at desc, filename desc
        ) = 1""",
}

SHAPES = {
    "player_game_stats": (
        ROSTERS,
        """
        teams as (
            select league_id, season, scoring_period, unnest(teams) as team from latest
        ),
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
            select * from lines
            where line.statSourceId = 0 and line.statSplitTypeId = 5
              and line.scoringPeriodId = scoring_period
        ),
        stat_rows as (
            select league_id, season, team_id, espn_player_id,
                   line.externalId as espn_game_id, unnest(map_entries(line.stats)) as stat
            from game_lines
        )
        select count(*), sum(hash(league_id, season, team_id, espn_player_id, espn_game_id,
            cast(stat.key as bigint), stat.value))
        from stat_rows""",
    ),
    "batting": (
        BOXSCORES,
        """
        sides as (
            select game_pk, fetched_at, 'home' as side, map_values(teams.home.players) as ps
            from latest
            union all
            select game_pk, fetched_at, 'away', map_values(teams.away.players) from latest
        ),
        players as (select game_pk, fetched_at, side, unnest(ps) as player from sides),
        batting as (
            select *, row_number() over (
                partition by game_pk, player.person.id order by fetched_at desc, side
            ) as newest
            from players
            where player.stats.batting.gamesPlayed = 1
        )
        select count(*), sum(hash(game_pk, side, player.person.id,
            player.stats.batting.atBats, player.stats.batting.hits,
            player.stats.batting.homeRuns))
        from batting
        where newest = 1""",
    ),
}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("shape", choices=sorted(SHAPES))
    parser.add_argument("latest", choices=["rank", "manifest"])
    parser.add_argument("memory_limit")
    args = parser.parse_args()
    if (args.shape, args.latest) not in LATEST:
        parser.error(f"{args.shape} has no '{args.latest}' form")

    captures, rest = SHAPES[args.shape]
    sql = (
        f"with captures as ({captures}),\nlatest as ({LATEST[(args.shape, args.latest)]}),\n{rest}"
    )
    con = duckdb.connect(WAREHOUSE, read_only=True)
    con.execute(f"set memory_limit = '{args.memory_limit}'; set threads = 4")
    started = time.monotonic()
    try:
        count, digest = con.execute(sql).fetchone() or (None, None)
        result = f"rows={count} hash={digest}"
    except duckdb.OutOfMemoryException as error:
        result = f"OUT OF MEMORY: {str(error).splitlines()[0][:100]}"
    seconds = time.monotonic() - started
    peak_gb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1048576
    print(
        f"{args.shape} latest-by-{args.latest} limit={args.memory_limit} {result} "
        f"{seconds:.1f}s peak_rss={peak_gb:.2f}GB"
    )


if __name__ == "__main__":
    main()
