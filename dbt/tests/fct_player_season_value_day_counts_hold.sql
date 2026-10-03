-- Identities between fct_player_season_value's day counts and the started-day grain it is
-- counted from. Returns each (player, team) that breaks one.
--
--   played_started_days <= started_days, started_days_outside_matchups <= started_days
--   first_started_date <= last_started_date
--   started_days equals the count of the pair's rows in int_fantasy__started_player_days
--   unverified_started_days equals the count of those whose input_status is neither
--     'played' nor 'verified_off', recomputed here from the day grain (R4.5)
--
-- Catches bye-week days vanishing, unverified zeroes counted as real days, and a count
-- taken from the wrong model.

with recomputed as (

    select
        platform_player_id,
        fantasy_team_id,
        count(*) as started_days,
        count(*) filter (where input_status not in ('played', 'verified_off')) as unverified_started_days
    from {{ ref('int_fantasy__started_player_days') }}
    group by platform_player_id, fantasy_team_id

)

select fact.platform_player_id, fact.fantasy_team_id
from {{ ref('fct_player_season_value') }} as fact
left join recomputed
    on recomputed.platform_player_id = fact.platform_player_id
    and recomputed.fantasy_team_id = fact.fantasy_team_id
where fact.played_started_days > fact.started_days
    or fact.started_days_outside_matchups > fact.started_days
    or fact.first_started_date > fact.last_started_date
    or fact.started_days is distinct from recomputed.started_days
    or fact.unverified_started_days is distinct from recomputed.unverified_started_days
