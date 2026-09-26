-- One row per (matchup period, calendar date): the days a head-to-head matchup covers.
--
-- Joins the matchup-to-period bridge onto real dates, so everything above this layer
-- can work in dates and never has to know that ESPN counts scoring periods.
--
-- Matchup periods are NOT a uniform length in this league -- 12, 14 and 7 days all
-- occur -- so no consumer may assume a week. That is exactly why this model exists
-- rather than a date_add somewhere.

-- Materialized as a table despite being tiny. A contract's not_null constraints are
-- silently dropped on a view -- dbt warns "Constraint types are not supported for view
-- materializations" and builds it anyway -- so a view here would enforce column names
-- and types while quietly abandoning the rest. Twelve rows is not worth a half-kept
-- promise.
{{ config(materialized='table') }}

select
    'espn' as platform,
    periods.league_id,
    periods.season,
    periods.matchup_period,
    periods.scoring_period,
    days.scoring_date
from {{ ref('stg_espn__matchup_periods') }} as periods
inner join {{ ref('stg_espn__scoring_periods') }} as days
    on days.league_id = periods.league_id
    and days.season = periods.season
    and days.scoring_period = periods.scoring_period
