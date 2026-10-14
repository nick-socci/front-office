-- One row per (matchup period, calendar date): the days a head-to-head matchup covers.
--
-- Joins the matchup-to-period bridge onto real dates, so everything above this layer
-- can work in dates and never has to know that ESPN counts scoring periods.
--
-- Matchup periods are NOT a uniform length in this league -- 12, 14 and 7 days all
-- occur -- so no consumer may assume a week. That is exactly why this model exists
-- rather than a date_add somewhere.
--
-- The bridge has two sources (ADR 0055), and `mapping_source` says which gave each row.
-- stg_espn__matchup_periods reads each matchup side's `pointsByScoringPeriod`;
-- ESPN does not publish that for a past season, so stg_espn__matchup_days supplies the
-- scoring periods it has no row for, from the matchup period ESPN marked on that day.
-- The first source wins per scoring period: no row of a season that has it changes, and
-- a running season, whose `pointsByScoringPeriod` grows by the day, never depends on a
-- marker. A test (int_fantasy__matchup_period_sources_agree) checks the two sources
-- against each other where both speak.

-- Materialized as a table despite being tiny. A contract's not_null constraints are
-- silently dropped on a view -- dbt warns "Constraint types are not supported for view
-- materializations" and builds it anyway -- so a view here would enforce column names
-- and types while quietly abandoning the rest. Twelve rows is not worth a half-kept
-- promise.
{{ config(materialized='table') }}

with from_points as (

    select
        league_id,
        season,
        matchup_period,
        scoring_period,
        'points_by_scoring_period' as mapping_source
    from {{ ref('stg_espn__matchup_periods') }}

),

from_marker as (

    select
        days.league_id,
        days.season,
        days.matchup_period,
        days.scoring_period,
        'matchup_day_marker' as mapping_source
    from {{ ref('stg_espn__matchup_days') }} as days
    left join from_points
        on from_points.league_id = days.league_id
        and from_points.season = days.season
        and from_points.scoring_period = days.scoring_period
    where from_points.scoring_period is null

),

periods as (

    select * from from_points
    union all
    select * from from_marker

)

select
    'espn' as platform,
    periods.league_id,
    periods.season,
    periods.matchup_period,
    periods.scoring_period,
    days.scoring_date,
    periods.mapping_source
from periods
inner join {{ ref('stg_espn__scoring_periods') }} as days
    on days.league_id = periods.league_id
    and days.season = periods.season
    and days.scoring_period = periods.scoring_period
