{{ config(severity='warn') }}

-- A day kind (of a league-season) whose pool has no played days has a null replacement
-- level, and every day of that kind will be valued against nothing. Expected on tiny
-- fixtures, never on the real season, so it warns rather than fails: the number is an input
-- to every value-over-replacement, and an empty pool should be seen, not discovered later.
--
-- The column is qualified: BigQuery reads a bare pool_played_days in HAVING as the output
-- alias, an aggregate, and refuses an aggregate of it.
select
    levels.platform,
    levels.league_id,
    levels.season,
    levels.day_kind,
    max(levels.pool_played_days) as pool_played_days
from {{ ref('int_fantasy__replacement_levels') }} as levels
group by levels.platform, levels.league_id, levels.season, levels.day_kind
having max(levels.pool_played_days) = 0
