-- Every category result and every matchup winner equals ESPN's (#10).
--
-- A category result may differ only where the values differ by an accounted-for
-- residual on either side ('explained'), and a category scored at one end only fails. A winner may not differ at all: no 2026
-- residual flips one, and if a future one does, that is worth a person's attention
-- rather than an automatic pass. Sides with unverified inputs are skipped.

select
    'category' as finding,
    matchup_id,
    fantasy_team_id as team_id,
    category_key,
    our_result || ' vs ESPN ' || coalesce(espn_result, 'none') as detail
from {{ ref('rec_espn__category_result_differences') }}
where status in ('unexplained', 'missing_ours', 'missing_espn')

union all

select
    'winner' as finding,
    coalesce(ours.matchup_id, espn.matchup_id) as matchup_id,
    null as team_id,
    null as category_key,
    coalesce(ours.winner, 'none') || ' vs ESPN ' || coalesce(espn.winner, 'none') as detail
from {{ ref('fct_matchup_results') }} as ours
full outer join {{ ref('stg_espn__matchups') }} as espn
    on espn.league_id = ours.league_id
    and espn.season = ours.season
    and espn.matchup_id = ours.matchup_id
where ours.matchup_id is null
   or espn.matchup_id is null
   or (not ours.has_unverified_inputs and ours.winner is distinct from espn.winner)
