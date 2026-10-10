-- Fails when an optimal lineup is not a legal one (R6.2, R3.5): an illegal lineup from a
-- wrong matrix.
--
-- The solver builds a cost matrix; a mistake in it (a missing infinity, a slot row counted
-- wrong) would not raise, it would hand back a lineup that cannot exist. Each rule is
-- checked here from the options and slots models, not from the solver's own view. A row
-- comes back for each breach, labelled with the rule it broke:
--   player_twice       a player appears more than once on one team-day
--   slot_over_count    a slot holds more players than the league's slot_count
--   not_an_option      a (player, slot) pair that is not a row of the options model
--   unvalued_team_day  a team-day with a null option value has rows (it must have none)

with lineups as (

    select * from {{ ref('int_fantasy__optimal_lineups') }}

),

player_twice as (

    select
        'player_twice' as broken_rule,
        platform,
        league_id,
        season,
        scoring_date,
        fantasy_team_id,
        platform_player_id,
        cast(null as bigint) as lineup_slot_id,
        count(*) as row_count
    from lineups
    group by platform, league_id, season, scoring_date, fantasy_team_id, platform_player_id
    having count(*) > 1

),

slot_over_count as (

    select
        'slot_over_count' as broken_rule,
        lineups.platform,
        lineups.league_id,
        lineups.season,
        lineups.scoring_date,
        lineups.fantasy_team_id,
        cast(null as bigint) as platform_player_id,
        lineups.lineup_slot_id,
        count(*) as row_count
    from lineups
    left join {{ ref('int_fantasy__lineup_slots') }} as slots
        on slots.platform = lineups.platform
        and slots.league_id = lineups.league_id
        and slots.season = lineups.season
        and slots.lineup_slot_id = lineups.lineup_slot_id
    group by
        lineups.platform, lineups.league_id, lineups.season, lineups.scoring_date,
        lineups.fantasy_team_id, lineups.lineup_slot_id, slots.slot_count
    having count(*) > coalesce(slots.slot_count, 0)

),

not_an_option as (

    select
        'not_an_option' as broken_rule,
        lineups.platform,
        lineups.league_id,
        lineups.season,
        lineups.scoring_date,
        lineups.fantasy_team_id,
        lineups.platform_player_id,
        lineups.lineup_slot_id,
        1 as row_count
    from lineups
    left join {{ ref('int_fantasy__lineup_options') }} as options
        on options.platform = lineups.platform
        and options.league_id = lineups.league_id
        and options.season = lineups.season
        and options.scoring_date = lineups.scoring_date
        and options.fantasy_team_id = lineups.fantasy_team_id
        and options.platform_player_id = lineups.platform_player_id
        and options.lineup_slot_id = lineups.lineup_slot_id
    where options.platform_player_id is null

),

unvalued_team_days as (

    select distinct
        platform,
        league_id,
        season,
        scoring_date,
        fantasy_team_id
    from {{ ref('int_fantasy__lineup_options') }}
    where option_value is null

),

unvalued_team_day as (

    select
        'unvalued_team_day' as broken_rule,
        lineups.platform,
        lineups.league_id,
        lineups.season,
        lineups.scoring_date,
        lineups.fantasy_team_id,
        lineups.platform_player_id,
        lineups.lineup_slot_id,
        1 as row_count
    from lineups
    inner join unvalued_team_days
        on unvalued_team_days.platform = lineups.platform
        and unvalued_team_days.league_id = lineups.league_id
        and unvalued_team_days.season = lineups.season
        and unvalued_team_days.scoring_date = lineups.scoring_date
        and unvalued_team_days.fantasy_team_id = lineups.fantasy_team_id

)

select * from player_twice
union all
select * from slot_over_count
union all
select * from not_an_option
union all
select * from unvalued_team_day
