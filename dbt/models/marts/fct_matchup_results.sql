-- One row per head-to-head matchup: category wins, losses and ties for each side, and
-- the winner they imply.
--
-- The winner is the side that won more categories; equal wins is a tie. That is ESPN's
-- rule as observed in 2026: 7 regular-season matchups tied. No playoff matchup tied, so
-- how ESPN breaks a playoff tie (seeding is H2H record) is unobserved. A playoff tie is
-- emitted as TIE and the reconciliation would flag it, rather than guessing here.
--
-- scored_categories is carried so a test can check the tally adds up. A category with
-- no result (a null rate, only possible with unverified inputs) is counted as
-- undecided, and then there is no winner: a winner called on some categories would
-- read like a real result.

{{ config(materialized='table') }}

with tallies as (

    select
        platform,
        league_id,
        season,
        matchup_id,
        matchup_period,
        fantasy_team_id,
        opponent_team_id,
        is_home,
        count(*) as scored_categories,
        count(*) filter (where result = 'WIN') as category_wins,
        count(*) filter (where result = 'LOSS') as category_losses,
        count(*) filter (where result = 'TIE') as category_ties,
        count(*) filter (where result is null) as categories_undecided,
        bool_or(has_unverified_inputs) as has_unverified_inputs
    from {{ ref('fct_matchup_category_scores') }}
    group by
        platform,
        league_id,
        season,
        matchup_id,
        matchup_period,
        fantasy_team_id,
        opponent_team_id,
        is_home

)

select
    home.platform,
    home.league_id,
    home.season,
    home.matchup_id,
    home.matchup_period,
    sides.playoff_tier,
    home.fantasy_team_id as home_team_id,
    home.opponent_team_id as away_team_id,
    home.scored_categories,
    home.category_wins as home_category_wins,
    home.category_losses as away_category_wins,
    home.category_ties,
    home.categories_undecided,
    case
        when home.categories_undecided > 0 then null
        when home.category_wins > home.category_losses then 'HOME'
        when home.category_wins < home.category_losses then 'AWAY'
        else 'TIE'
    end as winner,
    home.has_unverified_inputs
from tallies as home
inner join {{ ref('int_fantasy__matchup_sides') }} as sides
    on sides.platform = home.platform
    and sides.league_id = home.league_id
    and sides.season = home.season
    and sides.matchup_id = home.matchup_id
    and sides.fantasy_team_id = home.fantasy_team_id
where home.is_home
