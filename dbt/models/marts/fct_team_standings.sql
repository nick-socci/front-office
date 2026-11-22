-- One row per fantasy team per league-season: the regular-season record computed from the
-- marts, next to the record ESPN reports (spec 0232).
--
-- A matchup counts when it is finished: a regular-season matchup (playoff_tier NONE) with
-- no undecided category, whose matchup period's last scoring period is strictly below the
-- league-season's latest scoring period. The last clause is what keeps a matchup still
-- being played, which already has category totals, out of the record. A matchup period
-- with no scoring periods mapped is never finished. The record is read from
-- fct_matchup_results twice, once from each side, and summed.
--
-- The record is computed for head-to-head categories only (scoring_type
-- H2H_MOST_CATEGORIES); any other scoring type has no matchups, so the computed columns
-- are null there and ESPN's own are still carried. In a head-to-head league a team with no
-- finished matchup has 0s, not nulls: it has played none, which is a count.
--
-- is_regular_season_complete says whether the record is the final one: every regular-season
-- matchup of the league-season is finished, and there is at least one: a league-season with
-- no regular-season matchup has no final record to compare. It is the same on every row of the
-- league-season, and decides whether fct_team_standings_record_matches_espn is an error or
-- a warning (the in-season copy): a record of a season in progress is ahead of or behind
-- ESPN's by design.
--
-- reported_* are int_fantasy__teams' wins, losses, ties and playoff_seed, as ESPN reports
-- them, never recomputed. Every team of int_fantasy__teams has a row, as in dim_fantasy_teams:
-- one with no league-season row is kept, with a null scoring_type, and fails the not_null test
-- on it, rather than dropping out of the standings unseen. Reads
-- int_fantasy__* and marts only, through the seam (ADR 0148).

{{ config(materialized='table') }}

with last_periods as (

    select
        platform,
        league_id,
        season,
        matchup_period,
        max(scoring_period) as last_scoring_period
    from {{ ref('int_fantasy__matchup_periods') }}
    group by platform, league_id, season, matchup_period

),

regular_matchups as (

    select
        results.platform,
        results.league_id,
        results.season,
        results.home_team_id,
        results.away_team_id,
        results.winner,
        results.home_category_wins,
        results.away_category_wins,
        results.category_ties,
        coalesce(
            results.categories_undecided = 0
            and last_periods.last_scoring_period < league_seasons.latest_scoring_period,
            false
        ) as is_finished
    from {{ ref('fct_matchup_results') }} as results
    left join last_periods
        on last_periods.platform = results.platform
        and last_periods.league_id = results.league_id
        and last_periods.season = results.season
        and last_periods.matchup_period = results.matchup_period
    left join {{ ref('int_fantasy__league_seasons') }} as league_seasons
        on league_seasons.platform = results.platform
        and league_seasons.league_id = results.league_id
        and league_seasons.season = results.season
    where results.playoff_tier = 'NONE'

),

team_sides as (

    select
        platform,
        league_id,
        season,
        home_team_id as fantasy_team_id,
        is_finished,
        winner = 'HOME' as is_win,
        winner = 'AWAY' as is_loss,
        winner = 'TIE' as is_tie,
        home_category_wins as category_wins,
        away_category_wins as category_losses,
        category_ties
    from regular_matchups

    union all

    select
        platform,
        league_id,
        season,
        away_team_id as fantasy_team_id,
        is_finished,
        winner = 'AWAY' as is_win,
        winner = 'HOME' as is_loss,
        winner = 'TIE' as is_tie,
        away_category_wins as category_wins,
        home_category_wins as category_losses,
        category_ties
    from regular_matchups

),

records as (

    -- order-exempt: whole counts of at most a few hundred categories a team, far below 2^53.
    -- The cast is the contract's bigint: DuckDB sums bigint into hugeint.
    select
        platform,
        league_id,
        season,
        fantasy_team_id,
        count(*) as matchups,
        count(case when is_win then 1 end) as wins,
        count(case when is_loss then 1 end) as losses,
        count(case when is_tie then 1 end) as ties,
        cast(sum(category_wins) as bigint) as category_wins,
        cast(sum(category_losses) as bigint) as category_losses,
        cast(sum(category_ties) as bigint) as category_ties
    from team_sides
    where is_finished
    group by platform, league_id, season, fantasy_team_id

),

season_status as (

    select
        platform,
        league_id,
        season,
        count(case when not is_finished then 1 end) = 0 as is_regular_season_complete
    from regular_matchups
    group by platform, league_id, season

)

select
    teams.platform,
    teams.league_id,
    teams.season,
    teams.fantasy_team_id,
    league_seasons.scoring_type,
    case
        when league_seasons.scoring_type = 'H2H_MOST_CATEGORIES'
            then coalesce(records.matchups, 0)
    end as matchups,
    case
        when league_seasons.scoring_type = 'H2H_MOST_CATEGORIES'
            then coalesce(records.wins, 0)
    end as wins,
    case
        when league_seasons.scoring_type = 'H2H_MOST_CATEGORIES'
            then coalesce(records.losses, 0)
    end as losses,
    case
        when league_seasons.scoring_type = 'H2H_MOST_CATEGORIES'
            then coalesce(records.ties, 0)
    end as ties,
    case
        when league_seasons.scoring_type = 'H2H_MOST_CATEGORIES'
            then coalesce(records.category_wins, 0)
    end as category_wins,
    case
        when league_seasons.scoring_type = 'H2H_MOST_CATEGORIES'
            then coalesce(records.category_losses, 0)
    end as category_losses,
    case
        when league_seasons.scoring_type = 'H2H_MOST_CATEGORIES'
            then coalesce(records.category_ties, 0)
    end as category_ties,
    coalesce(season_status.is_regular_season_complete, false) as is_regular_season_complete,
    teams.wins as reported_wins,
    teams.losses as reported_losses,
    teams.ties as reported_ties,
    teams.playoff_seed as reported_playoff_seed
from {{ ref('int_fantasy__teams') }} as teams
left join {{ ref('int_fantasy__league_seasons') }} as league_seasons
    on league_seasons.platform = teams.platform
    and league_seasons.league_id = teams.league_id
    and league_seasons.season = teams.season
left join records
    on records.platform = teams.platform
    and records.league_id = teams.league_id
    and records.season = teams.season
    and records.fantasy_team_id = teams.fantasy_team_id
left join season_status
    on season_status.platform = teams.platform
    and season_status.league_id = teams.league_id
    and season_status.season = teams.season
