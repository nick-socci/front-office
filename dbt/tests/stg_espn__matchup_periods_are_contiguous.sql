-- The scoring periods inside one matchup period are consecutive, with no gaps.
--
-- Matchup periods vary in length here (12, 14 and 7 days), so their length cannot be
-- asserted -- but a matchup covering days 69-72 and then 75 would mean two days of
-- production belong to no matchup at all, which is exactly the hole the companion test
-- looks for from the other side.

with spans as (

    select
        league_id,
        season,
        matchup_period,
        count(*) as days,
        count(distinct scoring_period) as distinct_days,
        (max(scoring_period) - min(scoring_period)) + 1 as span
    from {{ ref('stg_espn__matchup_periods') }}
    group by league_id, season, matchup_period

)

select *
from spans
where days != distinct_days
   or days != span
