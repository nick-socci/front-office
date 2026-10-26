"""Spec 0137's probe: solve the real season's lineup options, and compare two solutions.

Kept with the spec so that claims C9 to C11 and C19 can be rerun, and so that task 9 checks
R4.2 the same way. It is evidence, not part of the build.

    solve    Solve every team-period the way the planned entry point does: per team-period,
             the cap of spec 0164, the bound check, and optionally each value rounded to
             --round decimals first. The options come from the warehouse, or from a parquet
             snapshot of another warehouse's options (BigQuery's, C8). Writes a parquet of
             (platform, league_id, season, scoring_date, fantasy_team_id,
             platform_player_id, lineup_slot_id).
    compare  Compare two solutions (a parquet, or `model` for the warehouse's
             int_fantasy__optimal_lineups). Prints the rows that differ each way. Then, per
             changed team-day: the size, the kept actual players and the summed value of
             each lineup. Per changed team-period: the credited value under the start rule
             (a start on a day the limit was already reached counts 0) and the starts each
             day. Values are taken from --values (the warehouse's own, by default).

Run from the repository root:
    uv run python docs/specs/0137-lineup-solver-on-bigquery/probes/compare_solves.py \\
        solve --warehouse data/spec137/warehouse.duckdb --round 12 --out data/spec137/dk_r12.parquet
    uv run python …/compare_solves.py compare --warehouse data/spec137/warehouse.duckdb \\
        model data/spec137/dk_r12.parquet
"""

import argparse
import importlib.util
import math
import sys
from collections import defaultdict
from pathlib import Path

import duckdb

KEY = (
    "platform",
    "league_id",
    "season",
    "scoring_date",
    "fantasy_team_id",
    "platform_player_id",
    "lineup_slot_id",
)
OPTION_KEY = ", ".join(KEY)


def load_solver(path: str):
    spec = importlib.util.spec_from_file_location("lineup_solver", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def connect(warehouse: str) -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    # The warehouse's views name their catalog `warehouse`.
    con.execute(f"attach '{warehouse}' as warehouse (read_only)")
    return con


def options_relation(con, source: str | None) -> str:
    if source is None:
        return "warehouse.intermediate.int_fantasy__lineup_options"
    con.execute(f"create table snapshot_options as from read_parquet('{source}')")
    return "snapshot_options"


def solve(args) -> None:
    solver = load_solver(args.solver)
    con = connect(args.warehouse)
    options = options_relation(con, args.options)
    rows = con.sql(
        f"""
        select o.platform, o.league_id, o.season, p.matchup_period, o.fantasy_team_id,
            o.scoring_date, o.platform_player_id, o.lineup_slot_id, o.slot_role,
            o.option_value, o.is_actual, o.slot_role = 'pitcher' and o.day_kind = 'start'
        from {options} as o
        left join warehouse.intermediate.int_fantasy__matchup_periods as p
            using (platform, league_id, season, scoring_date)
        order by all
        """
    ).fetchall()
    slots = defaultdict(list)
    for platform, league_id, season, slot_id, role, count in con.sql(
        "select platform, league_id, season, lineup_slot_id, slot_role, slot_count "
        "from warehouse.intermediate.int_fantasy__lineup_slots order by all"
    ).fetchall():
        slots[(platform, league_id, season)].append(solver.Slot(slot_id, role, count))
    limits = {
        tuple(r[:4]): r[4]
        for r in con.sql(
            "select platform, league_id, season, matchup_period, start_limit "
            "from warehouse.intermediate.int_fantasy__start_limits"
        ).fetchall()
    }

    periods = defaultdict(lambda: defaultdict(list))
    for *team_key, period, team, day, player, slot, role, value, actual, start in rows:
        if period is None:
            sys.exit(f"no matchup period: {team_key} {day} team {team}")
        if value is not None and args.round is not None:
            value = round(value, args.round)
        periods[(*team_key, period, team)][day].append((player, slot, role, value, actual, start))

    out = []
    for key in sorted(periods):
        days = periods[key]
        if any(o[3] is None for opts in days.values() for o in opts):
            continue  # unvalued (spec 0164, R2.1)
        parsed = [
            (day, [solver.Option(p, s, r, v, a, st) for p, s, r, v, a, st in opts])
            for day, opts in sorted(days.items())
        ]
        limit = limits.get(key[:4])
        cap = None
        if limit is not None:
            actual = sum(o.is_actual and o.is_start for _, opts in parsed for o in opts)
            cap = max(math.floor(limit), actual)
        for day, player, slot in solver.solve_team_period(parsed, slots[key[:3]], limit, cap):
            out.append((key[0], key[1], key[2], day, key[4], player, slot))

    con.execute(
        "create table solved (platform varchar, league_id varchar, season bigint, "
        "scoring_date date, fantasy_team_id bigint, platform_player_id bigint, "
        "lineup_slot_id bigint)"
    )
    con.executemany("insert into solved values (?, ?, ?, ?, ?, ?, ?)", out)
    con.execute(f"copy solved to '{args.out}' (format parquet)")
    print(f"{len(out)} rows in {len(periods)} team-periods -> {args.out}")


def solution(con, name: str, source: str) -> None:
    if source == "model":
        con.execute(
            f"create table {name} as select {OPTION_KEY} "
            "from warehouse.intermediate.int_fantasy__optimal_lineups"
        )
    else:
        con.execute(f"create table {name} as select {OPTION_KEY} from read_parquet('{source}')")


def compare(args) -> None:
    con = connect(args.warehouse)
    options = options_relation(con, args.values)
    solution(con, "a", args.a)
    solution(con, "b", args.b)
    a_only = con.sql("select count(*) from (from a except all from b)").fetchone()[0]
    b_only = con.sql("select count(*) from (from b except all from a)").fetchone()[0]
    print(
        f"rows: a {con.sql('select count(*) from a').fetchone()[0]}, "
        f"b {con.sql('select count(*) from b').fetchone()[0]}; "
        f"a only {a_only}, b only {b_only}"
    )
    if not a_only and not b_only:
        return

    team_day = "platform, league_id, season, scoring_date, fantasy_team_id"
    print(
        "changed team-days (count, max |value gap|, kept differs, size differs, other players):",
        con.sql(f"""
        with changed as (select distinct {team_day} from (from a except all from b)
                         union select distinct {team_day} from (from b except all from a)),
        sides as (select 'a' as side, * from a union all select 'b', * from b),
        per as (
            select s.side, {", ".join("c." + c for c in team_day.split(", "))},
                count(*) as n, count(*) filter (where o.is_actual) as kept,
                sum(o.option_value order by s.platform_player_id, s.lineup_slot_id) as val,
                list(s.platform_player_id order by s.platform_player_id) as players
            from changed as c
            inner join sides as s using ({team_day})
            inner join {options} as o using ({OPTION_KEY})
            group by all)
        select count(*), max(abs(x.val - y.val)), count(*) filter (where x.kept <> y.kept),
            count(*) filter (where x.n <> y.n), count(*) filter (where x.players <> y.players)
        from per as x inner join per as y using ({team_day})
        where x.side = 'a' and y.side = 'b'""").fetchall(),
    )

    # Per team-period: the credited value under the start rule, and the starts each day.
    rows = con.sql(f"""
        with changed as (
            select distinct p.platform, p.league_id, p.season, p.matchup_period, d.fantasy_team_id
            from (select distinct {team_day} from (from a except all from b)
                  union select distinct {team_day} from (from b except all from a)) as d
            inner join warehouse.intermediate.int_fantasy__matchup_periods as p
                using (platform, league_id, season, scoring_date))
        select s.side, c.platform, c.league_id, c.season, c.matchup_period, c.fantasy_team_id,
            s.scoring_date, o.option_value, o.slot_role = 'pitcher' and o.day_kind = 'start',
            l.start_limit
        from changed as c
        inner join warehouse.intermediate.int_fantasy__matchup_periods as p
            using (platform, league_id, season, matchup_period)
        inner join (select 'a' as side, * from a union all select 'b', * from b) as s
            on s.platform = c.platform and s.league_id = c.league_id and s.season = c.season
            and s.fantasy_team_id = c.fantasy_team_id and s.scoring_date = p.scoring_date
        inner join {options} as o
            on {" and ".join(f"o.{column} = s.{column}" for column in KEY)}
        left join warehouse.intermediate.int_fantasy__start_limits as l
            on l.platform = c.platform and l.league_id = c.league_id and l.season = c.season
            and l.matchup_period = c.matchup_period
        order by all""").fetchall()
    plans = defaultdict(lambda: defaultdict(list))
    limit_of = {}
    for side, *key, day, value, is_start, limit in rows:
        plans[tuple(key)][(side, day)].append((value, is_start))
        limit_of[tuple(key)] = limit
    gaps, start_sequences_differ = [], 0
    for key, by_side_day in plans.items():
        credited, sequence = {}, {}
        for side in ("a", "b"):
            starts, total, seq = 0, 0.0, []
            for s, day in sorted(k for k in by_side_day if k[0] == side):
                closed = limit_of[key] is not None and starts >= limit_of[key]
                lineup = sorted(by_side_day[(s, day)])
                total += sum(0.0 if closed and st else v for v, st in lineup)
                day_starts = sum(st for _, st in lineup)
                starts += day_starts
                seq.append(day_starts)
            credited[side], sequence[side] = total, seq
        gaps.append(abs(credited["a"] - credited["b"]))
        start_sequences_differ += sequence["a"] != sequence["b"]
    print(
        f"changed team-periods: {len(plans)}; max |credited value gap| {max(gaps):.3g}; "
        f"start sequence differs in {start_sequences_differ}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    s = sub.add_parser("solve")
    s.add_argument("--warehouse", required=True)
    s.add_argument("--options", help="parquet of another warehouse's lineup options")
    s.add_argument("--round", type=int)
    s.add_argument("--solver", default=str(Path("dbt/python_modules/lineup_solver.py")))
    s.add_argument("--out", required=True)
    c = sub.add_parser("compare")
    c.add_argument("--warehouse", required=True)
    c.add_argument("--values", help="parquet of the options whose values judge the ties")
    c.add_argument("a")
    c.add_argument("b")
    args = parser.parse_args()
    solve(args) if args.command == "solve" else compare(args)


if __name__ == "__main__":
    main()
