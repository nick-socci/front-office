-- One row per (matchup, team, scored category): what the team did, what it would have
-- done had it set the optimal lineup on every day of the matchup period, and what each
-- is worth against the opponent (#12).
--
-- THE OPTIMAL FIGURES ARE HINDSIGHT OPPORTUNITY, NOT MANAGER SKILL: they are known only
-- after the games. They follow one rule (ADR 0037): a starter who played is replaced only
-- by another player who played. The lineup maximises the summed day value across all the
-- categories -- not this category and not the matchup -- so a category can come out worse
-- under it than it did as played. Eligibility is ESPN's as fetched, not of the day (ADR
-- 0038), so a move that was not legal on the day can look legal. The league's limit on
-- pitcher starts is not applied. The opponent is held at what it actually did; two teams
-- both re-optimised is a different question and is not asked.
--
-- The actual figures are fct_matchup_category_scores', copied; this model sums nothing.
-- The optimal figure is the `optimal` row of int_fantasy__lineup_category_totals, which is
-- null where a team-day of the side's period is unvalued (R5.4); optimal_result is then
-- null with it.
--
-- optimal_result is decided by fo_category_result, the rule the fact uses (ADR 0084), with
-- the optimal lineup's own outs for the team's side and the opponent's actual outs (R3.2),
-- so the pitching minimum applies to it as to the fact. An unvalued optimal row has no outs
-- either and keeps a null result: the minimum never decides a lineup that has no totals.
--
-- has_unverified_inputs is the fact's flag, or any team-day of the side's matchup period
-- flagged in fct_lineup_decisions. A result on such a row rests on incomplete production.

{{ config(materialized='table') }}

with optimal_totals as (

    select
        platform,
        league_id,
        season,
        matchup_id,
        fantasy_team_id,
        category_key,
        category_value as optimal_value,
        outs_recorded as optimal_outs
    from {{ ref('int_fantasy__lineup_category_totals') }}
    where lineup = 'optimal'

),

unverified_days as (

    select
        platform,
        league_id,
        season,
        matchup_id,
        fantasy_team_id,
        bool_or(has_unverified_inputs) as has_unverified_day
    from {{ ref('fct_lineup_decisions') }}
    where matchup_id is not null
    group by platform, league_id, season, matchup_id, fantasy_team_id

),

compared as (

    select
        scores.*,
        optimal_totals.optimal_value,
        optimal_totals.optimal_outs,
        categories.is_bound_by_minimum,
        seasons.pitching_minimum_outs,
        coalesce(unverified_days.has_unverified_day, false) as has_unverified_day
    from {{ ref('fct_matchup_category_scores') }} as scores
    inner join {{ ref('int_fantasy__categories') }} as categories
        on categories.platform = scores.platform
        and categories.league_id = scores.league_id
        and categories.season = scores.season
        and categories.category_key = scores.category_key
    left join {{ ref('int_fantasy__league_seasons') }} as seasons
        on seasons.platform = scores.platform
        and seasons.league_id = scores.league_id
        and seasons.season = scores.season
    inner join optimal_totals
        on optimal_totals.platform = scores.platform
        and optimal_totals.league_id = scores.league_id
        and optimal_totals.season = scores.season
        and optimal_totals.matchup_id = scores.matchup_id
        and optimal_totals.fantasy_team_id = scores.fantasy_team_id
        and optimal_totals.category_key = scores.category_key
    left join unverified_days
        on unverified_days.platform = scores.platform
        and unverified_days.league_id = scores.league_id
        and unverified_days.season = scores.season
        and unverified_days.matchup_id = scores.matchup_id
        and unverified_days.fantasy_team_id = scores.fantasy_team_id

)

select
    platform,
    league_id,
    season,
    matchup_id,
    matchup_period,
    fantasy_team_id,
    opponent_team_id,
    category_key,
    category_label,
    is_lower_better,
    team_value as actual_value,
    opponent_value,
    result as actual_result,
    optimal_value,
    case
        when optimal_outs is null then null
        else {{ fo_category_result(
            'optimal_value',
            'opponent_value',
            'is_lower_better',
            'is_bound_by_minimum',
            'coalesce(optimal_outs < pitching_minimum_outs, false)',
            'is_opponent_below_minimum'
        ) }}
    end as optimal_result,
    (has_unverified_inputs or has_unverified_day) as has_unverified_inputs
from compared
