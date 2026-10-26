"""The best lineups each team could have fielded (#12, #164), one row per assigned player.

Why Python: filling slots with players is an assignment problem, which a greedy SQL pass
gets wrong (it double-assigns a player eligible at two slots). SciPy solves it exactly;
dbt/functions/solve_lineup_period.py builds the matrix and this model only feeds it (ADR 0039).

What the rows mean (R6.4): hindsight opportunity under the rule of R3.1 -- a starter who
played is replaced only by another player who played (ADR 0037), and ties keep the actual
lineup. They are NOT a measure of manager skill. The eligibility they rest on is ESPN's as
fetched, not of the day (ADR 0038). Injured-list slots are not candidates.

The period (spec 0164): a league's limit on pitcher starts couples the days of a matchup
period, so each team's matchup period is solved together, within a cap of floor(start_limit)
starts, or the starts of the actual lineup where it went past the limit (ADR 0090). The
solve is exact: it enumerates each day's starters and a dynamic programme over the starts so
far picks the lineups (ADR 0091). A league-season with no limit has no cap and is solved a
day at a time, as before.

Unvalued periods (R2.1): a team-period with any option whose value is null has no rows on
any of its days (ADR 0092). A team-day with no options never reaches this model (no option
rows), so it adds none. A value beyond the solver's bound fails the build, naming the
team-day (R1.8), even in an unvalued period: the bound is checked on every non-null option
before the skip. A team-day whose date is in no matchup period fails the build too; on real
data every option has one.

Running it: the solver is imported through `module_paths: ["python_modules", "functions"]` in
profiles.yml, which dbt-duckdb appends to sys.path as written. It resolves against the
working directory, so this model builds only when dbt is run from `dbt/`.

BigQuery: a Python model there needs a Spark or BigQuery DataFrames runtime, so this model
either stays DuckDB-only or the solver moves; sub-project 3 decides.

This is a dbt Python model: dbt calls model(dbt, session) and takes the returned relation
as the table. With dbt-duckdb, `session` is a DuckDB connection.
"""

import math
from itertools import groupby

from solve_lineup_period import Option, Slot, check_value_bound, solve_team_period

TEAM_DAY = ("platform", "league_id", "season", "scoring_date", "fantasy_team_id")
OPTION_COLUMNS = (
    *TEAM_DAY,
    "platform_player_id",
    "lineup_slot_id",
    "slot_role",
    "option_value",
    "is_actual",
    "day_kind",
)
PERIOD_KEY = ("platform", "league_id", "season", "matchup_period", "fantasy_team_id")


def named(keys, values):
    return ", ".join(f"{k}={v}" for k, v in zip(keys, values, strict=True))


def model(dbt, session):
    dbt.config(materialized="table")

    options = dbt.ref("int_fantasy__lineup_options")
    slots = dbt.ref("int_fantasy__lineup_slots").order(
        "platform, league_id, season, lineup_slot_id"
    )
    periods = dbt.ref("int_fantasy__matchup_periods")
    limits = dbt.ref("int_fantasy__start_limits")

    slots_of: dict[tuple, list[Slot]] = {}
    for platform, league_id, season, slot_id, role, count in slots.project(
        "platform, league_id, season, lineup_slot_id, slot_role, slot_count"
    ).fetchall():
        slots_of.setdefault((platform, league_id, season), []).append(Slot(slot_id, role, count))

    period_of = {
        (platform, league_id, season, scoring_date): matchup_period
        for platform, league_id, season, matchup_period, scoring_date in periods.project(
            "platform, league_id, season, matchup_period, scoring_date"
        ).fetchall()
    }
    limit_of = {
        (platform, league_id, season, matchup_period): start_limit
        for platform, league_id, season, matchup_period, start_limit in limits.project(
            "platform, league_id, season, matchup_period, start_limit"
        ).fetchall()
    }

    # Team-days in order, each placed in its team-period; days stay in date order.
    option_rows = (
        options.order(", ".join((*TEAM_DAY, "platform_player_id", "lineup_slot_id")))
        .project(", ".join(OPTION_COLUMNS))
        .fetchall()
    )
    team_periods: dict[tuple, list[tuple]] = {}
    for team_day, day_rows in groupby(option_rows, key=lambda r: r[: len(TEAM_DAY)]):
        platform, league_id, season, scoring_date, team_id = team_day
        matchup_period = period_of.get((platform, league_id, season, scoring_date))
        if matchup_period is None:
            raise ValueError(
                "optimal lineup failed for team-day "
                + named(TEAM_DAY, team_day)
                + ": its date is in no matchup period"
            )
        key = (platform, league_id, season, matchup_period, team_id)
        team_periods.setdefault(key, []).append((team_day, list(day_rows)))

    rows = []
    for key in sorted(team_periods):
        days = team_periods[key]
        parsed = []  # (team_day, options with a value, every option of the day)
        for team_day, day_rows in days:
            day_options = [
                Option(r[5], r[6], r[7], float(r[8]), r[9], r[7] == "pitcher" and r[10] == "start")
                for r in day_rows
                if r[8] is not None
            ]
            try:
                check_value_bound(day_options)
            except ValueError as error:
                raise ValueError(
                    "optimal lineup failed for team-day " + named(TEAM_DAY, team_day) + f": {error}"
                ) from error
            parsed.append((team_day, day_options, day_rows))
        if any(r[8] is None for _, _, day_rows in parsed for r in day_rows):
            continue  # unvalued (R2.1)

        start_limit = limit_of.get(key[:4])
        if start_limit is None:
            start_cap = None
        else:
            actual_starts = sum(o.is_actual and o.is_start for _, opts, _ in parsed for o in opts)
            start_cap = max(math.floor(start_limit), actual_starts)  # R1.3
        by_date = {team_day[3]: team_day for team_day, _, _ in parsed}
        try:
            assigned = solve_team_period(
                [(team_day[3], opts) for team_day, opts, _ in parsed],
                slots_of.get(key[:3], []),
                start_limit,
                start_cap,
            )
        except ValueError as error:
            raise ValueError(
                "optimal lineup failed for team-period " + named(PERIOD_KEY, key) + f": {error}"
            ) from error
        rows.extend((*by_date[d], player_id, slot_id) for d, player_id, slot_id in assigned)

    session.execute(
        "create or replace temporary table optimal_lineups_rows ("
        "platform varchar, league_id varchar, season bigint, scoring_date date, "
        "fantasy_team_id bigint, platform_player_id bigint, lineup_slot_id bigint)"
    )
    if rows:
        session.executemany("insert into optimal_lineups_rows values (?, ?, ?, ?, ?, ?, ?)", rows)
    return session.table("optimal_lineups_rows")
