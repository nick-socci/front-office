"""The best lineup each team-day could have fielded (#12, R3.3), one row per assigned player.

Why Python: filling slots with players is an assignment problem, which a greedy SQL pass
gets wrong (it double-assigns a player eligible at two slots). SciPy solves it exactly;
dbt/python_modules/lineup_solver.py builds the matrix and this model only feeds it (ADR 0039).

What the rows mean (R6.4): hindsight opportunity under the rule of R3.1 -- a starter who
played is replaced only by another player who played (ADR 0037), and ties keep the actual
lineup. They are NOT a measure of manager skill. The eligibility they rest on is ESPN's as
fetched, not of the day (ADR 0038).

Unvalued team-days (R3.5): a team-day with any option whose value is null has no rows. A
team-day with no options never reaches this model (no option rows), so it has none either.
A value beyond the solver's bound fails the build, naming the team-day (R3.7).

Running it: the solver is imported through `module_paths: ["python_modules"]` in
profiles.yml, which dbt-duckdb appends to sys.path as written. It resolves against the
working directory, so this model builds only when dbt is run from `dbt/`.

BigQuery: a Python model there needs a Spark or BigQuery DataFrames runtime, so this model
either stays DuckDB-only or the solver moves; sub-project 3 decides.

This is a dbt Python model: dbt calls model(dbt, session) and takes the returned relation
as the table. With dbt-duckdb, `session` is a DuckDB connection.
"""

from itertools import groupby

from lineup_solver import Option, Slot, solve_team_day

TEAM_DAY = ("platform", "league_id", "season", "scoring_date", "fantasy_team_id")
OPTION_COLUMNS = (
    *TEAM_DAY,
    "platform_player_id",
    "lineup_slot_id",
    "slot_role",
    "option_value",
    "is_actual",
)


def model(dbt, session):
    dbt.config(materialized="table")

    options = dbt.ref("int_fantasy__lineup_options").order(
        ", ".join((*TEAM_DAY, "platform_player_id", "lineup_slot_id"))
    )
    slots = dbt.ref("int_fantasy__lineup_slots").order(
        "platform, league_id, season, lineup_slot_id"
    )

    slots_of: dict[tuple, list[Slot]] = {}
    for platform, league_id, season, slot_id, role, count in slots.project(
        "platform, league_id, season, lineup_slot_id, slot_role, slot_count"
    ).fetchall():
        slots_of.setdefault((platform, league_id, season), []).append(Slot(slot_id, role, count))

    rows = []
    option_rows = options.project(", ".join(OPTION_COLUMNS)).fetchall()
    for team_day, day_rows in groupby(option_rows, key=lambda r: r[: len(TEAM_DAY)]):
        day_rows = list(day_rows)
        if any(r[-2] is None for r in day_rows):
            continue  # unvalued (R3.5)
        day_options = [Option(r[5], r[6], r[7], float(r[8]), r[9]) for r in day_rows]
        try:
            assigned = solve_team_day(day_options, slots_of.get(team_day[:3], []))
        except ValueError as error:
            raise ValueError(
                "optimal lineup failed for team-day "
                + ", ".join(f"{k}={v}" for k, v in zip(TEAM_DAY, team_day, strict=True))
                + f": {error}"
            ) from error
        rows.extend((*team_day, player_id, slot_id) for player_id, slot_id in assigned)

    session.execute(
        "create or replace temporary table optimal_lineups_rows ("
        "platform varchar, league_id varchar, season bigint, scoring_date date, "
        "fantasy_team_id bigint, platform_player_id bigint, lineup_slot_id bigint)"
    )
    if rows:
        session.executemany("insert into optimal_lineups_rows values (?, ?, ?, ?, ?, ?, ?)", rows)
    return session.table("optimal_lineups_rows")
