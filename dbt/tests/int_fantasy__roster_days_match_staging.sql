-- The neutral layer loses nobody and invents nobody.
--
-- int_fantasy__roster_days joins staging rosters to the period->date bridge and to the
-- lineup-slot seed. Every one of those is an inner join, and an inner join is how rows
-- quietly disappear: one scoring period missing from the bridge, or one slot id absent
-- from the seed, and a chunk of the season stops existing with no error anywhere.
--
-- Counted per scoring period rather than in total, so a failure says WHICH day broke.

with staged as (

    select scoring_period, count(*) as entries
    from {{ ref('stg_espn__roster_entries') }}
    group by scoring_period

),

neutral as (

    select scoring_period, count(*) as entries
    from {{ ref('int_fantasy__roster_days') }}
    group by scoring_period

)

select
    coalesce(staged.scoring_period, neutral.scoring_period) as scoring_period,
    staged.entries as staged_entries,
    neutral.entries as neutral_entries
from staged
full outer join neutral
    on neutral.scoring_period = staged.scoring_period
where coalesce(staged.entries, -1) != coalesce(neutral.entries, -1)
