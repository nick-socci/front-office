-- Fails when a day value is on a different scale from the facts (R1.5).
--
-- For every (player, team) pair of fct_player_season_value, the day values of his STARTED
-- days, on the side his slot credits that day (a hitter slot takes the batting row, a
-- pitcher slot the pitching row), must add up to his total_value. The two are the same
-- arithmetic at different grains: the season fact sums a pair's components and values the
-- total, the day model values each day, and the value is linear in the days, so any gap
-- means one of them used a different level, scale, sign, kind or category set.
--
-- A pair with no valued started day sums to 0, as the season fact says for a pair with no
-- played day. The day sum is null if any of its day values is null, as total_value is. A
-- row comes back when the two differ by more than 1e-9, or when exactly one is null.

with started_days as (

    select
        platform,
        league_id,
        season,
        scoring_date,
        fantasy_team_id,
        platform_player_id,
        case slot_role when 'hitter' then 'batting' when 'pitcher' then 'pitching' end as side
    from {{ ref('int_fantasy__roster_days') }}
    where is_started

),

day_sums as (

    select
        started_days.platform,
        started_days.league_id,
        started_days.season,
        started_days.platform_player_id,
        started_days.fantasy_team_id,
        count(*) filter (where day_values.day_value is null) as null_days,
        coalesce(sum(day_values.day_value), 0) as day_total
    from started_days
    inner join {{ ref('int_fantasy__candidate_day_values') }} as day_values
        on day_values.platform = started_days.platform
        and day_values.league_id = started_days.league_id
        and day_values.season = started_days.season
        and day_values.scoring_date = started_days.scoring_date
        and day_values.fantasy_team_id = started_days.fantasy_team_id
        and day_values.platform_player_id = started_days.platform_player_id
        and day_values.side = started_days.side
    group by 1, 2, 3, 4, 5

)

select
    seasons.platform,
    seasons.league_id,
    seasons.season,
    seasons.platform_player_id,
    seasons.fantasy_team_id,
    seasons.total_value,
    case when sums.null_days > 0 then null else coalesce(sums.day_total, 0) end as day_total
from {{ ref('fct_player_season_value') }} as seasons
left join day_sums as sums
    on sums.platform = seasons.platform
    and sums.league_id = seasons.league_id
    and sums.season = seasons.season
    and sums.platform_player_id = seasons.platform_player_id
    and sums.fantasy_team_id = seasons.fantasy_team_id
where (seasons.total_value is null) != (coalesce(sums.null_days, 0) > 0)
    or abs(seasons.total_value - coalesce(sums.day_total, 0)) > 1e-9
