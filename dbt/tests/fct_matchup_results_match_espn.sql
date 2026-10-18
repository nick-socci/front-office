-- Every category result and every matchup winner equals ESPN's (#10).
--
-- A category result may differ only where the values differ by an accounted-for
-- residual on either side ('explained'), and a category scored at one end only fails. A
-- matchup ESPN does not play (a bye) has no result of ours to compare ('bye'). A winner
-- that differs is returned unless it flips only through category results that are all
-- explained (ADR 0078): that is the rule of rec_espn__winner_differences, where a unit
-- test holds it. A winner that differs with no category behind it (level categories, a
-- tied playoff matchup: #159), or through a result that is not explained, still fails.
-- Sides with unverified inputs are skipped.
--
-- ESPN's matchups are those of league-seasons with rosters (ADR 0026), as the
-- reconciliation's are: a season loaded for its matchup totals alone has ESPN's winners
-- and none of ours, by design.

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
    matchup_id,
    null as team_id,
    null as category_key,
    coalesce(our_winner, 'none') || ' vs ESPN ' || coalesce(espn_winner, 'none')
    || ' (' || problem || ')' as detail
from {{ ref('rec_espn__winner_differences') }}
where problem is not null
