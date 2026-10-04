-- A replacement pool holds at most one player per fantasy team: N is the number of
-- teams, so a larger pool means the top-N cut was made at the wrong size (or not made).
-- Returns the offending day kinds.
select
    day_kind,
    max(pool_players) as pool_players
from {{ ref('int_fantasy__replacement_levels') }}
group by day_kind
having max(pool_players) > (select count(*) from {{ ref('int_fantasy__teams') }})
