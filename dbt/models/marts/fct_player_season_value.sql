-- One row per (player, fantasy team): how long he was started and what he was worth in
-- total (#11). The narrow companion of fct_player_category_value (ADR 0007): day counts
-- have no category, so they live here once, where summing them gives the truth rather than
-- 17 times it.
--
-- The day counts are counted from int_fantasy__started_player_days, never from the
-- category fact:
--   started_days                  every started day (ADR 0006: value counts all of them);
--   played_started_days           days with an appearance on the side the slot credits:
--                                 hitter-slot days with games_batted > 0 plus pitcher-slot
--                                 days with games_pitched > 0 (not the grain's `played`);
--   started_days_outside_matchups started days whose TEAM has no side in the matchup
--                                 period its date maps to (int_fantasy__matchup_periods
--                                 gives the period, int_fantasy__matchup_sides the sides).
--                                 Every date is in some period, so it is the team that
--                                 is missing: a bye week. Reported so no one reads these
--                                 days as scored;
--   unverified_started_days       input_status neither 'played' nor 'verified_off': a
--                                 missing boxscore or an unresolved player, so his zeroes
--                                 are not known to be real (R4.5).
--
-- total_value is the matchup margins the pair added over a free agent, summed across every
-- scored category: the sum of its scaled values (ADR 0010; the sum itself, with no mean
-- subtracted, is ADR 0003; which matchups a margin is measured from, ADR 0027). It is NULL if any category's scaled value is NULL, which
-- happens only when a played side faces an empty replacement pool: a partial total would
-- look complete.

{{ config(materialized='table') }}

with team_matchup_dates as (

    select distinct
        periods.platform,
        periods.league_id,
        periods.season,
        sides.fantasy_team_id,
        periods.scoring_date
    from {{ ref('int_fantasy__matchup_periods') }} as periods
    inner join {{ ref('int_fantasy__matchup_sides') }} as sides
        on sides.platform = periods.platform
        and sides.league_id = periods.league_id
        and sides.season = periods.season
        and sides.matchup_period = periods.matchup_period

),

started_days as (

    select
        days.platform,
        days.league_id,
        days.season,
        days.platform_player_id,
        days.fantasy_team_id,
        days.scoring_date,
        days.input_status,
        (days.slot_role = 'hitter' and days.games_batted > 0)
            or (days.slot_role = 'pitcher' and days.games_pitched > 0) as played_on_credited_side,
        (team_matchup_dates.scoring_date is not null) as in_matchup
    from {{ ref('int_fantasy__started_player_days') }} as days
    left join team_matchup_dates
        on team_matchup_dates.platform = days.platform
        and team_matchup_dates.league_id = days.league_id
        and team_matchup_dates.season = days.season
        and team_matchup_dates.fantasy_team_id = days.fantasy_team_id
        and team_matchup_dates.scoring_date = days.scoring_date

),

day_counts as (

    select
        platform,
        league_id,
        season,
        platform_player_id,
        fantasy_team_id,
        count(*) as started_days,
        count(*) filter (where played_on_credited_side) as played_started_days,
        count(*) filter (where not in_matchup) as started_days_outside_matchups,
        count(*) filter (where input_status not in ('played', 'verified_off')) as unverified_started_days,
        min(scoring_date) as first_started_date,
        max(scoring_date) as last_started_date
    from started_days
    group by platform, league_id, season, platform_player_id, fantasy_team_id

),

total_values as (

    select
        platform,
        league_id,
        season,
        platform_player_id,
        fantasy_team_id,
        case
            when count(*) filter (where scaled_value is null) > 0 then null
            -- in category order: a sum of doubles is only reproducible in a fixed order (#28)
            else sum(scaled_value order by category_key)
        end as total_value
    from {{ ref('fct_player_category_value') }}
    group by platform, league_id, season, platform_player_id, fantasy_team_id

)

select
    day_counts.platform,
    day_counts.league_id,
    day_counts.season,
    day_counts.platform_player_id,
    day_counts.fantasy_team_id,
    day_counts.started_days,
    day_counts.played_started_days,
    day_counts.started_days_outside_matchups,
    day_counts.unverified_started_days,
    day_counts.first_started_date,
    day_counts.last_started_date,
    total_values.total_value
from day_counts
left join total_values
    on total_values.platform = day_counts.platform
    and total_values.league_id = day_counts.league_id
    and total_values.season = day_counts.season
    and total_values.platform_player_id = day_counts.platform_player_id
    and total_values.fantasy_team_id = day_counts.fantasy_team_id
