-- Fails when an "optimal" lineup is worse than the actual one (R4.7).
--
-- Two ways it can happen, labelled in broken_rule:
--   gap_below_zero      the value_gap of a team-period, summed over its days, is below -1e-9
--                       (the tolerance is for the order of a floating-point sum). The actual
--                       lineup is itself a legal lineup within the start cap, so an optimum
--                       below it is a wrong matrix or a wrong sum. It is judged per
--                       team-period, not per team-day (R4.1, ADR 0092): the optimal lineup
--                       is chosen over the period, so a day's gap may be negative where the
--                       period gains. Unvalued team-periods have no gap and are not tested.
--                       The row has no day: scoring_date is null, and matchup_period names
--                       the period.
--   fewer_than_played   in a role (hitter, pitcher), fewer players are assigned than the
--                       actual lineup had starters who played on that role's side, on a
--                       team-day (R4.2). That is R3.1's constraint; breaking it is how an
--                       unrestricted optimum would sit a played starter with nobody to
--                       replace him. matchup_period is carried so that both branches have
--                       the same columns.
-- Role counts come from the options and the optimal lineups, not from the fact's columns.

with actual_by_role as (

    select
        platform,
        league_id,
        season,
        scoring_date,
        fantasy_team_id,
        slot_role,
        count(*) as played_starters
    from {{ ref('int_fantasy__lineup_options') }}
    where is_actual
    group by platform, league_id, season, scoring_date, fantasy_team_id, slot_role

),

assigned_by_role as (

    select
        lineups.platform,
        lineups.league_id,
        lineups.season,
        lineups.scoring_date,
        lineups.fantasy_team_id,
        options.slot_role,
        count(*) as assigned_players
    from {{ ref('int_fantasy__optimal_lineups') }} as lineups
    inner join {{ ref('int_fantasy__lineup_options') }} as options
        on options.platform = lineups.platform
        and options.league_id = lineups.league_id
        and options.season = lineups.season
        and options.scoring_date = lineups.scoring_date
        and options.fantasy_team_id = lineups.fantasy_team_id
        and options.platform_player_id = lineups.platform_player_id
        and options.lineup_slot_id = lineups.lineup_slot_id
    group by
        lineups.platform, lineups.league_id, lineups.season, lineups.scoring_date,
        lineups.fantasy_team_id, options.slot_role

),

gap_below_zero as (

    select
        'gap_below_zero' as broken_rule,
        platform,
        league_id,
        season,
        matchup_period,
        cast(null as date) as scoring_date,
        fantasy_team_id,
        cast(null as varchar) as slot_role,
        sum(value_gap order by scoring_date) as measured,
        cast(null as bigint) as expected_at_least
    from {{ ref('fct_lineup_decisions') }}
    where not is_unvalued
    group by platform, league_id, season, matchup_period, fantasy_team_id
    having sum(value_gap order by scoring_date) < -1e-9

),

fewer_than_played as (

    select
        'fewer_than_played' as broken_rule,
        actual.platform,
        actual.league_id,
        actual.season,
        decisions.matchup_period,
        actual.scoring_date,
        actual.fantasy_team_id,
        actual.slot_role,
        cast(coalesce(assigned.assigned_players, 0) as double) as measured,
        actual.played_starters as expected_at_least
    from actual_by_role as actual
    -- Unvalued team-days have no optimal lineup by design (R3.5); they are not a breach.
    inner join {{ ref('fct_lineup_decisions') }} as decisions
        on decisions.platform = actual.platform
        and decisions.league_id = actual.league_id
        and decisions.season = actual.season
        and decisions.scoring_date = actual.scoring_date
        and decisions.fantasy_team_id = actual.fantasy_team_id
        and not decisions.is_unvalued
    left join assigned_by_role as assigned
        on assigned.platform = actual.platform
        and assigned.league_id = actual.league_id
        and assigned.season = actual.season
        and assigned.scoring_date = actual.scoring_date
        and assigned.fantasy_team_id = actual.fantasy_team_id
        and assigned.slot_role = actual.slot_role
    where coalesce(assigned.assigned_players, 0) < actual.played_starters

)

select * from gap_below_zero
union all
select * from fewer_than_played
