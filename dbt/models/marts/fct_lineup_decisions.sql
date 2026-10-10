-- What each team could have had from the players it held, one row per team-day (#12).
--
-- Each row sets the actual lineup's value beside the best lineup's, their gap, and what
-- changed between the two: players brought in, sat and moved, and the largest missed start.
--
-- THE FIGURES ARE HINDSIGHT OPPORTUNITY, NOT MANAGER SKILL. Every value is known only after
-- the games; nothing here says a manager could have known it. The best lineup follows the
-- rule of R3.1 (ADR 0037): a starter who played is replaced only by another player who
-- played, so the gap counts choices between players and not days that went badly;
-- injured-list slots are not candidates; and a tie keeps the actual lineup. The solver
-- (int_fantasy__optimal_lineups) returns only who goes where; every sum is made here, in
-- player order, because a sum of doubles is reproducible only in a fixed order.
--
-- ELIGIBILITY IS ESPN'S AS FETCHED (ADR 0038): as of eligibility_fetched_at, not of the day,
-- so a move that was not legal on the day can look legal. For the 2026 backfill that is
-- 2026-09-26 for scoring periods 1 to 178 and 2026-10-07 for periods 179 and 180; measured
-- there, it overstates the season's gap by at most about 8%. The league's limit on pitcher
-- starts is NOT applied (ADR 0037). That is why actual_pitcher_starts and
-- optimal_pitcher_starts are carried: summed by team and matchup period they show a period
-- over the limit, whatever it is.
--
-- The spine is the roster days, not the options, so a team-day with no option still has a
-- row: not unvalued, both values 0, every count 0. is_unvalued is read from the options
-- (R3.5), never from whether the optimal lineups have rows for the day: no rows mean
-- "nobody assigned" when it is false and "not solved" when it is true. When it is true,
-- what rests on the solver is null (R4.6). actual_value is null only when an actual option
-- has no value, since a sum would skip it and report a part as the whole.
--
-- A player moved is one who started and is assigned to a slot other than his own: his option
-- there is not is_actual. A team-day in a matchup period where the team has no matchup (a
-- bye) keeps its row with a null matchup_id.

{{ config(materialized='table') }}

with team_days as (

    select distinct
        platform, league_id, season, scoring_date, scoring_period, fantasy_team_id
    from {{ ref('int_fantasy__roster_days') }}

),

candidate_counts as (

    select
        days.platform,
        days.league_id,
        days.season,
        days.scoring_date,
        days.fantasy_team_id,
        count(*) as candidates,
        bool_or(days.mlbam_player_id is null) as has_unresolved_candidate
    from {{ ref('int_fantasy__roster_days') }} as days
    inner join {{ ref('espn_lineup_slots') }} as slots
        on slots.lineup_slot_id = days.roster_slot_id
    where days.is_started or (days.slot_role = 'bench' and not slots.is_injured_list_slot)
    group by days.platform, days.league_id, days.season, days.scoring_date, days.fantasy_team_id

),

option_totals as (

    select
        platform, league_id, season, scoring_date, fantasy_team_id,
        count(*) filter (where is_actual) as played_starters,
        bool_or(option_value is null) as is_unvalued,
        bool_or(is_actual and option_value is null) as has_unvalued_actual,
        sum(option_value order by platform_player_id) filter (where is_actual) as actual_sum,
        count(*) filter (
            where is_actual and slot_role = 'pitcher' and day_kind = 'start'
        ) as actual_pitcher_starts
    from {{ ref('int_fantasy__lineup_options') }}
    group by platform, league_id, season, scoring_date, fantasy_team_id

),

optimal_options as (

    select
        lineups.platform,
        lineups.league_id,
        lineups.season,
        lineups.scoring_date,
        lineups.fantasy_team_id,
        lineups.platform_player_id,
        options.lineup_slot,
        options.slot_role,
        options.option_value,
        options.day_kind,
        options.is_started,
        options.is_actual
    from {{ ref('int_fantasy__optimal_lineups') }} as lineups
    inner join {{ ref('int_fantasy__lineup_options') }} as options
        on options.platform = lineups.platform
        and options.league_id = lineups.league_id
        and options.season = lineups.season
        and options.scoring_date = lineups.scoring_date
        and options.fantasy_team_id = lineups.fantasy_team_id
        and options.platform_player_id = lineups.platform_player_id
        and options.lineup_slot_id = lineups.lineup_slot_id

),

optimal_totals as (

    select
        platform, league_id, season, scoring_date, fantasy_team_id,
        count(*) as optimal_starters,
        sum(option_value order by platform_player_id) as optimal_sum,
        count(*) filter (where not is_started) as players_brought_in,
        count(*) filter (where is_started and not is_actual) as players_moved,
        count(*) filter (
            where slot_role = 'pitcher' and day_kind = 'start'
        ) as optimal_pitcher_starts
    from optimal_options
    group by platform, league_id, season, scoring_date, fantasy_team_id

),

sat_totals as (

    select
        actual.platform, actual.league_id, actual.season, actual.scoring_date,
        actual.fantasy_team_id,
        count(*) as players_sat
    from {{ ref('int_fantasy__lineup_options') }} as actual
    left join {{ ref('int_fantasy__optimal_lineups') }} as lineups
        on lineups.platform = actual.platform
        and lineups.league_id = actual.league_id
        and lineups.season = actual.season
        and lineups.scoring_date = actual.scoring_date
        and lineups.fantasy_team_id = actual.fantasy_team_id
        and lineups.platform_player_id = actual.platform_player_id
    where actual.is_actual and lineups.platform_player_id is null
    group by actual.platform, actual.league_id, actual.season, actual.scoring_date, actual.fantasy_team_id

),

ranked_missed_starts as (

    select
        *,
        row_number() over (
            partition by platform, league_id, season, scoring_date, fantasy_team_id
            order by option_value desc, platform_player_id
        ) as missed_start_rank
    from optimal_options
    where not is_started

),

missed_starts as (

    select * from ranked_missed_starts where missed_start_rank = 1

),

roster_fetches as (

    select
        league_id, season, scoring_period, team_id,
        max(fetched_at) as eligibility_fetched_at
    from {{ ref('stg_espn__roster_entry_slots') }}
    group by league_id, season, scoring_period, team_id

)

select
    team_days.platform,
    team_days.league_id,
    team_days.season,
    team_days.scoring_date,
    team_days.fantasy_team_id,
    team_days.scoring_period,
    periods.matchup_period,
    sides.matchup_id,

    coalesce(candidate_counts.candidates, 0) as candidates,
    coalesce(option_totals.played_starters, 0) as played_starters,
    case when coalesce(option_totals.is_unvalued, false) then null
        else coalesce(optimal_totals.optimal_starters, 0) end as optimal_starters,

    case when coalesce(option_totals.has_unvalued_actual, false) then null
        else coalesce(option_totals.actual_sum, 0) end as actual_value,
    case when coalesce(option_totals.is_unvalued, false) then null
        else coalesce(optimal_totals.optimal_sum, 0) end as optimal_value,
    case when coalesce(option_totals.is_unvalued, false) then null
        else coalesce(optimal_totals.optimal_sum, 0) end
        - case when coalesce(option_totals.has_unvalued_actual, false) then null
            else coalesce(option_totals.actual_sum, 0) end as value_gap,

    case when coalesce(option_totals.is_unvalued, false) then null
        else coalesce(optimal_totals.players_brought_in, 0) end as players_brought_in,
    case when coalesce(option_totals.is_unvalued, false) then null
        else coalesce(sat_totals.players_sat, 0) end as players_sat,
    case when coalesce(option_totals.is_unvalued, false) then null
        else coalesce(optimal_totals.players_moved, 0) end as players_moved,

    coalesce(option_totals.actual_pitcher_starts, 0) as actual_pitcher_starts,
    case when coalesce(option_totals.is_unvalued, false) then null
        else coalesce(optimal_totals.optimal_pitcher_starts, 0) end as optimal_pitcher_starts,

    missed_starts.platform_player_id as missed_start_platform_player_id,
    league_seasons.mlbam_player_id as missed_start_mlbam_player_id,
    missed_starts.lineup_slot as missed_start_slot,
    missed_starts.option_value as missed_start_value,

    roster_fetches.eligibility_fetched_at,
    coalesce(option_totals.is_unvalued, false) as is_unvalued,
    (
        not coalesce(game_dates.is_complete, true)
        or coalesce(candidate_counts.has_unresolved_candidate, false)
    ) as has_unverified_inputs
from team_days
left join candidate_counts
    on candidate_counts.platform = team_days.platform
    and candidate_counts.league_id = team_days.league_id
    and candidate_counts.season = team_days.season
    and candidate_counts.scoring_date = team_days.scoring_date
    and candidate_counts.fantasy_team_id = team_days.fantasy_team_id
left join option_totals
    on option_totals.platform = team_days.platform
    and option_totals.league_id = team_days.league_id
    and option_totals.season = team_days.season
    and option_totals.scoring_date = team_days.scoring_date
    and option_totals.fantasy_team_id = team_days.fantasy_team_id
left join optimal_totals
    on optimal_totals.platform = team_days.platform
    and optimal_totals.league_id = team_days.league_id
    and optimal_totals.season = team_days.season
    and optimal_totals.scoring_date = team_days.scoring_date
    and optimal_totals.fantasy_team_id = team_days.fantasy_team_id
left join sat_totals
    on sat_totals.platform = team_days.platform
    and sat_totals.league_id = team_days.league_id
    and sat_totals.season = team_days.season
    and sat_totals.scoring_date = team_days.scoring_date
    and sat_totals.fantasy_team_id = team_days.fantasy_team_id
left join missed_starts
    on missed_starts.platform = team_days.platform
    and missed_starts.league_id = team_days.league_id
    and missed_starts.season = team_days.season
    and missed_starts.scoring_date = team_days.scoring_date
    and missed_starts.fantasy_team_id = team_days.fantasy_team_id
left join {{ ref('dim_player_league_seasons') }} as league_seasons
    on league_seasons.platform = missed_starts.platform
    and league_seasons.league_id = missed_starts.league_id
    and league_seasons.season = missed_starts.season
    and league_seasons.platform_player_id = missed_starts.platform_player_id
left join roster_fetches
    on roster_fetches.league_id = team_days.league_id
    and roster_fetches.season = team_days.season
    and roster_fetches.scoring_period = team_days.scoring_period
    and roster_fetches.team_id = team_days.fantasy_team_id
left join {{ ref('int_fantasy__matchup_periods') }} as periods
    on periods.platform = team_days.platform
    and periods.league_id = team_days.league_id
    and periods.season = team_days.season
    and periods.scoring_period = team_days.scoring_period
left join {{ ref('int_fantasy__matchup_sides') }} as sides
    on sides.platform = team_days.platform
    and sides.league_id = team_days.league_id
    and sides.season = team_days.season
    and sides.matchup_period = periods.matchup_period
    and sides.fantasy_team_id = team_days.fantasy_team_id
left join {{ ref('int_mlb__game_dates') }} as game_dates
    on game_dates.official_date = team_days.scoring_date
