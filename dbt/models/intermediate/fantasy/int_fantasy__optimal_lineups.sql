-- The best lineups each team could have fielded (#12, #164), one row per assigned player.
--
-- Why a function: filling slots with players is an assignment problem, which a greedy SQL
-- pass gets wrong (it double-assigns a player eligible at two slots). SciPy solves it
-- exactly, in dbt/functions/solve_lineup_period.py (ADR 0039). That file is one Python
-- function, a BigQuery Python UDF on BigQuery and a function the fo_duckdb_functions plugin
-- registers on DuckDB, so this is one SQL model for both warehouses and calls it once per
-- team-period (ADR 0103). The model only gathers the function's inputs and unnests its rows.
--
-- What the rows mean (R6.4): hindsight opportunity under the rule of R3.1 -- a starter who
-- played is replaced only by another player who played (ADR 0037), and ties keep the actual
-- lineup. They are NOT a measure of manager skill. The eligibility they rest on is ESPN's as
-- fetched, not of the day (ADR 0038). Injured-list slots are not candidates.
--
-- The period (spec 0164): a league's limit on pitcher starts couples the days of a matchup
-- period, so each team's matchup period is solved together, within a cap of floor(start_limit)
-- starts, or the starts of the actual lineup where it went past the limit (ADR 0090). The
-- solve is exact (ADR 0091). A league-season with no limit has a null start_limit, no cap,
-- and is solved a day at a time.
--
-- Values are rounded to 12 places inside the function, before anything else uses them, so
-- the two warehouses, whose float sums differ in the last digits, choose the same lineups
-- (ADR 0104).
--
-- Unvalued periods (R2.1): a team-period with any option whose value is null has no rows on
-- any of its days (ADR 0092). A team-day with no options never reaches this model (no option
-- rows), so it adds none. A value beyond the solver's bound fails the build, naming the
-- team-day (R1.8), even in an unvalued period: the bound is checked on every non-null option
-- before the skip. The options are joined to their matchup period with a left join, so a
-- team-day whose date is in no matchup period reaches the function with a null period and
-- fails the build, naming the team-day, rather than being dropped; on real data every option
-- has one (R2.4).
--
-- A TABLE, never a view: the DuckDB function exists on dbt's connections only, so a view
-- calling it would fail for anyone who reads the warehouse outside dbt. A test holds that
-- this model is the only caller and is a table (spec 0137, R6.4).
--
-- Written once for both warehouses (ADR 0051). Nothing here is a heavy payload.

{{ config(materialized='table') }}

with options_in_period as (

    -- Left join: an option whose date is in no matchup period keeps a null period.
    select
        options.platform,
        options.league_id,
        options.season,
        options.fantasy_team_id,
        options.scoring_date,
        options.platform_player_id,
        options.lineup_slot_id,
        options.slot_role,
        options.option_value,
        options.is_actual,
        options.slot_role = 'pitcher' and options.day_kind = 'start' as is_start,
        periods.matchup_period
    from {{ ref('int_fantasy__lineup_options') }} as options
    left join {{ ref('int_fantasy__matchup_periods') }} as periods
        on periods.platform = options.platform
        and periods.league_id = options.league_id
        and periods.season = options.season
        and periods.scoring_date = options.scoring_date

),

team_period_options as (

    -- The field names and order are the function's signature (dbt/functions/_functions.yml).
    select
        platform,
        league_id,
        season,
        matchup_period,
        fantasy_team_id,
        concat(
            'platform=', platform,
            ', league_id=', league_id,
            ', season=', cast(season as {{ fo_type_text() }}),
            ', fantasy_team_id=', cast(fantasy_team_id as {{ fo_type_text() }})
        ) as team,
        array_agg(
            {{ fo_struct([
                ('scoring_date', 'scoring_date'),
                ('platform_player_id', 'player_id'),
                ('lineup_slot_id', 'slot_id'),
                ('slot_role', 'role'),
                ('option_value', 'value'),
                ('is_actual', 'is_actual'),
                ('is_start', 'is_start'),
            ]) }}
            order by scoring_date, platform_player_id, lineup_slot_id
        ) as option_list
    from options_in_period
    group by platform, league_id, season, matchup_period, fantasy_team_id

),

league_slots as (

    select
        platform,
        league_id,
        season,
        array_agg(
            {{ fo_struct([
                ('lineup_slot_id', 'slot_id'),
                ('slot_role', 'role'),
                ('slot_count', 'count'),
            ]) }}
            order by lineup_slot_id
        ) as slot_list
    from {{ ref('int_fantasy__lineup_slots') }}
    group by platform, league_id, season

),

solved as (

    -- A league-season with no slot rows, or no limit, passes a null; the function reads a
    -- null slot list as empty and a null limit as none.
    select
        team_period_options.platform,
        team_period_options.league_id,
        team_period_options.season,
        team_period_options.fantasy_team_id,
        {{ fo_solve_lineup_period() }}(
            team_period_options.team,
            team_period_options.matchup_period,
            team_period_options.option_list,
            league_slots.slot_list,
            start_limits.start_limit
        ) as lineup
    from team_period_options
    left join league_slots
        on league_slots.platform = team_period_options.platform
        and league_slots.league_id = team_period_options.league_id
        and league_slots.season = team_period_options.season
    left join {{ ref('int_fantasy__start_limits') }} as start_limits
        on start_limits.platform = team_period_options.platform
        and start_limits.league_id = team_period_options.league_id
        and start_limits.season = team_period_options.season
        and start_limits.matchup_period = team_period_options.matchup_period

)

select
    solved.platform,
    solved.league_id,
    solved.season,
    lineup_row.scoring_date,
    solved.fantasy_team_id,
    lineup_row.player_id as platform_player_id,
    lineup_row.slot_id as lineup_slot_id
from solved
{{ fo_unnest('solved.lineup', 'lineup_row') }}
