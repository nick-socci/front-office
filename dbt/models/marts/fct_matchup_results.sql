-- One row per head-to-head matchup: category wins, losses and ties for each side, and
-- the winner they imply.
--
-- The winner is who advanced (ADR 0080). The side that won more categories wins. When the
-- categories are level, a regular-season matchup is a tie (47 of them in the real league,
-- as ESPN records them), and a playoff matchup goes to the higher seed. That is ESPN's
-- default, the setting "NONE" for playoffMatchupTieRule, and
-- stg_espn__league_settings_tie_rules_are_understood fails the build on any other value.
-- The higher seed is the home side, because ESPN seats it there (ADR 0081): the model reads
-- no seeds, so it stays in the BigQuery slice, and
-- fct_matchup_results_home_is_the_better_seed fails the build if a lower seed is ever at
-- home. is_decided_by_tiebreak marks those matchups, so the category tie is not hidden.
-- A matchup with an undecided category is never decided by the tiebreak.
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
        count(case when result = 'WIN' then 1 end) as category_wins,
        count(case when result = 'LOSS' then 1 end) as category_losses,
        count(case when result = 'TIE' then 1 end) as category_ties,
        count(case when result is null then 1 end) as categories_undecided,
        {{ fo_any_true('has_unverified_inputs') }} as has_unverified_inputs
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
        when sides.playoff_tier != 'NONE' then 'HOME'
        else 'TIE'
    end as winner,
    (
        home.categories_undecided = 0
        and home.category_wins = home.category_losses
        and sides.playoff_tier != 'NONE'
    ) as is_decided_by_tiebreak,
    home.has_unverified_inputs
from tallies as home
inner join {{ ref('int_fantasy__matchup_sides') }} as sides
    on sides.platform = home.platform
    and sides.league_id = home.league_id
    and sides.season = home.season
    and sides.matchup_id = home.matchup_id
    and sides.fantasy_team_id = home.fantasy_team_id
where home.is_home
