-- One row per (matchup side, scored category) at either end: our result against
-- ESPN's, and whether a difference is accounted for.
--
-- A full outer join, so a category scored at one end only is a row, not a silence. The
-- stat reconciliation covers all 24 stats whatever the scored list says, and a dropped
-- category need not change a winner -- this is the check that would catch our list of
-- scored categories disagreeing with ESPN's. Byes need no exclusion: ESPN reports their
-- stats but no results, so they have no scored categories.
--
-- status:
--   missing_ours scored at ESPN, absent from our marts.
--   missing_espn in our marts, not scored at ESPN.
--   match        same result.
--   unverified   the category rests on unverified inputs on either side (#25).
--   explained    the results differ, and so do the values, by residuals already
--                accounted for in rec_espn__matchup_stat_differences on either side
--                ('registered' or 'explained_by_component'). The flip is a consequence,
--                not a separate finding.
--   unexplained  anything else, including a category missing on either end.

{{ config(materialized='table') }}

with espn as (

    select league_id, season, matchup_id, team_id as fantasy_team_id, stat_id as category_key, result
    from {{ ref('stg_espn__matchup_category_results') }}
    where is_scored_category

),

ours as (

    select league_id, season, matchup_id, fantasy_team_id, opponent_team_id, category_key, result,
        has_unverified_inputs
    from {{ ref('fct_matchup_category_scores') }}
    where platform = 'espn'

),

accounted as (

    select matchup_id, fantasy_team_id, stat_key
    from {{ ref('rec_espn__matchup_stat_differences') }}
    where status in ('registered', 'explained_by_component')

)

select
    coalesce(ours.league_id, espn.league_id) as league_id,
    coalesce(ours.season, espn.season) as season,
    coalesce(ours.matchup_id, espn.matchup_id) as matchup_id,
    coalesce(ours.fantasy_team_id, espn.fantasy_team_id) as fantasy_team_id,
    coalesce(ours.category_key, espn.category_key) as category_key,
    ours.result as our_result,
    espn.result as espn_result,
    case
        when ours.category_key is null then 'missing_ours'
        when espn.category_key is null then 'missing_espn'
        when ours.has_unverified_inputs then 'unverified'
        when ours.result = espn.result then 'match'
        when exists (
            select 1 from accounted
            where accounted.matchup_id = ours.matchup_id
              and accounted.stat_key = ours.category_key
              and accounted.fantasy_team_id in (ours.fantasy_team_id, ours.opponent_team_id)
        ) then 'explained'
        else 'unexplained'
    end as status
from ours
full outer join espn
    on espn.league_id = ours.league_id
    and espn.season = ours.season
    and espn.matchup_id = ours.matchup_id
    and espn.fantasy_team_id = ours.fantasy_team_id
    and espn.category_key = ours.category_key
