-- Each league-season's scoring periods are exactly 1..final_scoring_period, no more, no
-- fewer, no gaps.
--
-- The periods are generated from each league's own settings. If they were generated to
-- the longest league's final period instead (a global maximum), a shorter season would
-- get days that never existed; if a period went missing, the roster for that day would
-- have no calendar date. Compared on count and max so both a short and a long series
-- show up.

with periods as (

    select
        league_id,
        season,
        count(*) as periods,
        max(scoring_period) as max_period,
        min(scoring_period) as min_period
    from {{ ref('stg_espn__scoring_periods') }}
    group by league_id, season

)

-- Driven from settings so a league-season with no periods at all is a failure too.
select
    settings.league_id,
    settings.season,
    settings.final_scoring_period,
    periods.periods,
    periods.max_period,
    periods.min_period
from {{ ref('stg_espn__league_settings') }} as settings
left join periods
    on periods.league_id = settings.league_id
    and periods.season = settings.season
where periods.periods is null
   or periods.periods != settings.final_scoring_period
   or periods.max_period != settings.final_scoring_period
   or periods.min_period != 1
