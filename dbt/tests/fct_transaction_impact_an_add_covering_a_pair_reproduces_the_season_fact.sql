-- A (player, team) pair with exactly one add, whose started days all lie inside that add's
-- window, has the same started days and the same total value as in fct_player_season_value:
-- the window then holds the whole of what the season fact sums. Proves the window sums, the
-- replacement levels and the standard deviation agree across the two facts. Returns pairs
-- where started_days differ, or total_value differs by more than 1e-9 (or is null on one
-- side only).

-- Scoped by league and season (#28): a pair is one player on one team of one league-season.

with single_adds as (

    select
        platform,
        league_id,
        season,
        platform_player_id,
        fantasy_team_id,
        max(transaction_id) as transaction_id
    from {{ ref('fct_transaction_impact') }}
    where movement = 'add'
    group by platform, league_id, season, platform_player_id, fantasy_team_id
    having count(*) = 1

),

covered as (

    select
        impact.platform,
        impact.league_id,
        impact.season,
        impact.platform_player_id,
        impact.fantasy_team_id,
        impact.started_days as add_started_days,
        impact.total_value as add_total_value,
        season.started_days as season_started_days,
        season.total_value as season_total_value
    from single_adds
    inner join {{ ref('fct_transaction_impact') }} as impact
        on impact.transaction_id = single_adds.transaction_id
    inner join {{ ref('fct_player_season_value') }} as season
        on season.platform = single_adds.platform
        and season.league_id = single_adds.league_id
        and season.season = single_adds.season
        and season.platform_player_id = single_adds.platform_player_id
        and season.fantasy_team_id = single_adds.fantasy_team_id
        and season.first_started_date >= impact.window_start
        and season.last_started_date <= impact.window_end

)

select *
from covered
where add_started_days <> season_started_days
    or (add_total_value is null) <> (season_total_value is null)
    or abs(add_total_value - season_total_value) > 1e-9
