{{ config(severity='warn') }}

-- A group whose pool has no played days has a null replacement level, and every player
-- in that group will be valued against nothing. Expected on tiny fixtures, never on the
-- real season, so it warns rather than fails: the number is an input to every
-- value-over-replacement, and an empty pool should be seen, not discovered later.
select
    replacement_group,
    max(pool_played_days) as pool_played_days
from {{ ref('int_fantasy__replacement_levels') }}
group by replacement_group
having max(pool_played_days) = 0
