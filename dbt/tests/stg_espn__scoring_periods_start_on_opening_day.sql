-- Cross-source check: fantasy scoring period 1 is MLB's opening day.
--
-- The mapping is derived purely from ESPN's own status block, so agreeing with the MLB
-- schedule -- a source with no knowledge of the fantasy league -- is real evidence that
-- the anchor and the Eastern-time boundary are right.

with fantasy_day_one as (

    select scoring_date
    from {{ ref('stg_espn__scoring_periods') }}
    where scoring_period = 1

),

mlb_opening_day as (

    select min(official_date) as official_date
    from {{ ref('stg_mlb__games') }}

)

-- Driven from the MLB side, which always has one row: a missing period 1 or an empty
-- schedule is a failure, not a comparison against nothing.
select
    fantasy_day_one.scoring_date,
    mlb_opening_day.official_date
from mlb_opening_day
left join fantasy_day_one on true
where fantasy_day_one.scoring_date is null
   or mlb_opening_day.official_date is null
   or fantasy_day_one.scoring_date != mlb_opening_day.official_date
