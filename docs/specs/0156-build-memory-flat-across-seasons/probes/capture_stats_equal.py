"""Spec 0156 probe (R6.3, PR #202 review F2): the line stats the capture views give, unchanged.

This branch declares a stat line's `stats` as a map in `stg_raw__espn_roster` and in
`stg_raw__espn_matchup_days`, where `main` gave it as one JSON object. The views' parsed
columns are not compared by `compare_bounded.py`, so this compares every stat of every line
of every capture: from OLD the object's keys beside its values (`json_keys`, `$.*`), from
NEW the map's keys beside its values, each value as JSON text (both render it alike).

Per capture it sums a 64-bit hash of every (team or matchup side, player, line identity,
stat key, value) as a 128-bit integer, which is independent of order and streams, and
compares the sums and the counts capture by capture. Eight seasons of rosters are hundreds
of millions of stat values; an EXCEPT over them would not fit, a sum per capture does.

Each warehouse is opened read-only in its own connection: its views name the catalog
`warehouse`.

    uv run python docs/specs/0156-build-memory-flat-across-seasons/probes/capture_stats_equal.py \
        OLD_WAREHOUSE NEW_WAREHOUSE

Prints, per endpoint, the captures and stat values on each side and the captures that
differ; exit 1 if any differ. Run from the repository root.
"""

from __future__ import annotations

import sys

import duckdb

# Every level is unnested in a SELECT list, one CTE per level: DuckDB streams that, where
# unnests in the FROM clause are planned as delim joins that hold every parsed capture
# (the shape this spec removes from the models, C9).
OLD_PAIR = "unnest(json_keys(l.stats)) as k, unnest(json_extract(l.stats, '$.*')::json[]) as v"
NEW_PAIR = "unnest(map_keys(l.stats)) as k, unnest(map_values(l.stats)) as v"
TAIL = """
    lines as (
        select file_path, owner, e.playerId as player,
            unnest(e.playerPoolEntry.player.stats) as l
        from entries
    ),
    stats as (
        select file_path, owner, player, l.statSourceId as source_id,
            l.statSplitTypeId as split_id, l.scoringPeriodId as period, {line_key}, {pair}
        from lines
    )
    select file_path, count(*),
        sum(hash(owner, player, source_id, split_id, period, line_key, k, v::varchar)::hugeint)
    from stats
    group by file_path
"""
ROSTER = """
    with teams as (
        select file_path, unnest(teams) as t from staging.stg_raw__espn_roster
    ),
    entries as (
        select file_path, t.id::varchar as owner, unnest(t.roster.entries) as e from teams
    ),""" + TAIL.replace("{line_key}", "l.externalId as line_key")
MATCHUP_DAYS = """
    with matchups as (
        select file_path, unnest(schedule) as m from staging.stg_raw__espn_matchup_days
    ),
    sides as (
        select file_path, m.id as matchup_id, unnest([m.home, m.away]) as s from matchups
    ),
    entries as (
        select file_path, matchup_id::varchar || '/' || coalesce(s.teamId::varchar, '') as owner,
            unnest(s.rosterForMatchupPeriod.entries) as e
        from sides
    ),""" + TAIL.replace("{line_key}", "'' as line_key")


def sums(path: str, query: str, pair: str) -> dict[str, tuple[int, int]]:
    con = duckdb.connect(path, read_only=True)
    con.execute("set memory_limit = '8GB'")
    sql = query.replace("{pair}", pair)
    return {row[0]: (row[1], row[2]) for row in con.execute(sql).fetchall()}


def main(old: str, new: str) -> int:
    differing = 0
    for endpoint, query in (("espn/roster", ROSTER), ("espn/matchup_days", MATCHUP_DAYS)):
        before, after = sums(old, query, OLD_PAIR), sums(new, query, NEW_PAIR)
        bad = sorted(
            path for path in before.keys() | after.keys() if before.get(path) != after.get(path)
        )
        values = (
            sum(count for count, _ in before.values()),
            sum(count for count, _ in after.values()),
        )
        print(
            f"{endpoint}: captures {len(before)} / {len(after)}, stat values {values[0]} / "
            f"{values[1]}, captures differing {len(bad)}"
        )
        for path in bad[:5]:
            print(f"  {path}: {before.get(path)} vs {after.get(path)}")
        differing += len(bad)
    print("equal" if not differing else "DIFFERENT")
    return 1 if differing else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2]))
