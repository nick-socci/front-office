-- Fails when the actual lineup cannot be reproduced from the options (R2.4): an actual
-- lineup the solver could not reproduce.
--
-- Every started roster day that has a day value on the side its slot's role credits (a
-- hitter slot takes the batting row, a pitcher slot the pitching row) must have exactly one
-- option marked is_actual: the slot he sat in. Zero means the slot is not among the
-- eligible slots ESPN lists (or not one the league uses), so the solver would be unable to
-- keep him where he was; more than one means the option rows duplicate. A row comes back
-- for each such roster day, with how many actual options it has.

with started_days as (

    select
        days.platform,
        days.league_id,
        days.season,
        days.scoring_date,
        days.fantasy_team_id,
        days.platform_player_id,
        days.roster_slot_id,
        case days.slot_role when 'hitter' then 'batting' when 'pitcher' then 'pitching' end as side
    from {{ ref('int_fantasy__roster_days') }} as days
    where days.is_started

),

played_starters as (

    select started_days.*
    from started_days
    inner join {{ ref('int_fantasy__candidate_day_values') }} as day_values
        on day_values.platform = started_days.platform
        and day_values.league_id = started_days.league_id
        and day_values.season = started_days.season
        and day_values.scoring_date = started_days.scoring_date
        and day_values.fantasy_team_id = started_days.fantasy_team_id
        and day_values.platform_player_id = started_days.platform_player_id
        and day_values.side = started_days.side

),

actual_options as (

    select
        platform,
        league_id,
        season,
        scoring_date,
        fantasy_team_id,
        platform_player_id,
        count(*) as actual_options
    from {{ ref('int_fantasy__lineup_options') }}
    where is_actual
    group by 1, 2, 3, 4, 5, 6

)

select
    played_starters.platform,
    played_starters.league_id,
    played_starters.season,
    played_starters.scoring_date,
    played_starters.fantasy_team_id,
    played_starters.platform_player_id,
    played_starters.roster_slot_id,
    coalesce(actual_options.actual_options, 0) as actual_options
from played_starters
left join actual_options
    on actual_options.platform = played_starters.platform
    and actual_options.league_id = played_starters.league_id
    and actual_options.season = played_starters.season
    and actual_options.scoring_date = played_starters.scoring_date
    and actual_options.fantasy_team_id = played_starters.fantasy_team_id
    and actual_options.platform_player_id = played_starters.platform_player_id
where coalesce(actual_options.actual_options, 0) != 1
