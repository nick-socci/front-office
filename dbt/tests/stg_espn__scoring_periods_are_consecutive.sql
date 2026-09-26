-- Periods must map to consecutive calendar dates with no gaps and no repeats.
--
-- A gap or a duplicate would mean some fantasy day silently has no MLB stats, or two
-- days share one. Either produces a roster that looks plausible and is wrong.

with bounds as (

    select
        league_id,
        season,
        count(*) as periods,
        count(distinct scoring_date) as dates,
        (max(scoring_date) - min(scoring_date)) + 1 as span_days
    from {{ ref('stg_espn__scoring_periods') }}
    group by league_id, season

)

select *
from bounds
where periods != dates
   or periods != span_days
