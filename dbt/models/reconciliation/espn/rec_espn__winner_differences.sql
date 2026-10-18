-- One row per matchup whose winner differs from ESPN's, with the category results behind
-- it, and a problem column that is null when the difference is explained (spec 0147, R4;
-- ADR 0078). The rule behind the winner branch of the singular test
-- fct_matchup_results_match_espn, held here so that a unit test can reach it (dbt can
-- unit-test a model and not a singular test; the pattern of rec_espn__register_rows).
--
-- A winner is a count of category results, so it flips only when a category result does.
-- When every category result of the matchup that differs is already 'explained' (by a
-- value that differs for an accounted-for reason, in rec_espn__category_result_differences)
-- and there is at least one, the winner's difference adds nothing to find. Five past-season
-- winners are of this kind (C15). problem is, in this order:
--   no_category_differs   no category result of the matchup differs: the winner differs on
--                         its own (level categories, a tied playoff matchup: #159), or the
--                         matchup is at one end only. A person has to look.
--   category_unexplained  at least one differing category result is not 'explained'.
--   null                  every differing result is explained.
--
-- Same population as the test always had: ESPN's matchups are those of league-seasons with
-- rosters (ADR 0026), a matchup on one end only differs, and a matchup of ours that rests
-- on unverified inputs (#25) is skipped. A result differs when its status is explained,
-- unexplained, missing_ours or missing_espn (not match, unverified or bye). Counts are of
-- category results, one per side and category, so a flipped category counts twice.
--
-- A view, so that the test judges the table as it is now and not as it was last built.

{{ config(materialized='view') }}

with espn_matchups as (

    select
        matchups.league_id,
        matchups.season,
        matchups.matchup_id,
        matchups.winner
    from {{ ref('stg_espn__matchups') }} as matchups
    inner join {{ ref('int_fantasy__league_seasons') }} as league_seasons
        on league_seasons.platform = 'espn'
        and league_seasons.league_id = matchups.league_id
        and league_seasons.season = matchups.season
        and league_seasons.has_rosters

),

winners as (

    select
        coalesce(ours.league_id, espn.league_id) as league_id,
        coalesce(ours.season, espn.season) as season,
        coalesce(ours.matchup_id, espn.matchup_id) as matchup_id,
        ours.winner as our_winner,
        espn.winner as espn_winner
    from {{ ref('fct_matchup_results') }} as ours
    full outer join espn_matchups as espn
        on espn.league_id = ours.league_id
        and espn.season = ours.season
        and espn.matchup_id = ours.matchup_id
    where
        ours.matchup_id is null
        or espn.matchup_id is null
        or (not ours.has_unverified_inputs and ours.winner is distinct from espn.winner)

),

differing_results as (

    select
        league_id,
        season,
        matchup_id,
        count(*) as differing_categories,
        count(case when status = 'explained' then 1 end) as explained_categories
    from {{ ref('rec_espn__category_result_differences') }}
    where status in ('explained', 'unexplained', 'missing_ours', 'missing_espn')
    group by league_id, season, matchup_id

)

select
    winners.league_id,
    winners.season,
    winners.matchup_id,
    winners.our_winner,
    winners.espn_winner,
    coalesce(differing_results.differing_categories, 0) as differing_categories,
    coalesce(differing_results.explained_categories, 0) as explained_categories,
    case
        when differing_results.differing_categories is null then 'no_category_differs'
        when differing_results.explained_categories < differing_results.differing_categories
            then 'category_unexplained'
    end as problem
from winners
left join differing_results
    on differing_results.league_id = winners.league_id
    and differing_results.season = winners.season
    and differing_results.matchup_id = winners.matchup_id
