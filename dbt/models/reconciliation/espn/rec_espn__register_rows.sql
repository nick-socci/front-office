-- One row per row of the register of known residuals (espn_reconciliation_residuals) whose
-- league-season is loaded: the row, the status the reconciliation gave the side and stat it
-- names (null if it has none), and what is wrong with the row if anything. A view the tests
-- select from, so that a unit test can reach the rule: dbt can unit-test a model and not a
-- singular test (see rec_espn__player_day_residuals).
--
-- The register is looked up by league, season, matchup, side and stat, so a row is judged
-- only against its own league-season.
--
-- problem is, in this order:
--   matchup_absent      ESPN has no such matchup in the row's league-season: a mistyped
--                       matchup id.
--   explains_nothing    the matchup exists but the reconciliation has no status for the
--                       side and stat, or its status is not registered or unverified: the
--                       residual went away, changed size, or the row names a side or stat
--                       that does not exist. A register that only grows would quietly widen
--                       what counts as correct. A row about a past season that has
--                       matchups and no rosters lands here too, because that season's rows
--                       are not compared (ADR 0026).
--   null                the row explains a live residual, or the side is unverified.
--
-- Rows of a league-season that is not loaded are deliberately left out. A league-scoped
-- relation must hold no row of a league that is not loaded (ADR 0013, the tenant-isolation
-- gate), and this view is league-scoped. rec_espn__register_matchups_exist reports those
-- rows from the seed.

-- A view, so that the tests judge the tables as they are now and not as they were last built.
{{ config(materialized='view') }}

with register as (

    select * from {{ ref('espn_reconciliation_residuals') }}

),

league_seasons as (

    select league_id, season
    from {{ ref('int_fantasy__league_seasons') }}
    where platform = 'espn'

),

espn_matchups as (

    select distinct league_id, season, matchup_id
    from {{ ref('stg_espn__matchup_category_results') }}

),

differences as (

    select
        league_id,
        season,
        matchup_id,
        fantasy_team_id,
        stat_key,
        status
    from {{ ref('rec_espn__matchup_stat_differences') }}

)

select
    register.league_id,
    register.season,
    register.matchup_id,
    register.team_id,
    register.stat_id,
    register.expected_difference,
    register.cause,
    differences.status as reconciliation_status,
    case
        when espn_matchups.matchup_id is null then 'matchup_absent'
        when differences.status is null
            or differences.status not in ('registered', 'unverified') then 'explains_nothing'
    end as problem
from register
inner join league_seasons
    on league_seasons.league_id = register.league_id
    and league_seasons.season = register.season
left join espn_matchups
    on espn_matchups.league_id = register.league_id
    and espn_matchups.season = register.season
    and espn_matchups.matchup_id = register.matchup_id
left join differences
    on differences.league_id = register.league_id
    and differences.season = register.season
    and differences.matchup_id = register.matchup_id
    and differences.fantasy_team_id = register.team_id
    and differences.stat_key = register.stat_id
