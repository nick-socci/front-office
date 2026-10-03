-- The reconciliation (#10): every matchup side's every stat equals ESPN's scoreByStat,
-- or differs by exactly a registered, explained residual.
--
-- Fails on:
--   * any stat whose difference is not accounted for (status 'unexplained');
--   * a side or stat on one end only ('missing_ours', 'missing_espn');
--   * a rate our formula can't reproduce from ESPN's own components
--     ('formula_mismatch') -- that would be a wrong formula, not a data difference;
--   * a register row that no longer explains a live residual: the residual went away
--     (say, a refetch picked up MLB's correction) or changed size, or the row names a
--     side or stat that doesn't exist. A register that only grows would quietly widen
--     what counts as correct.
-- Byes are out of scope, and unverified sides are skipped (warned on separately).

select
    'stat' as finding,
    matchup_id,
    fantasy_team_id,
    stat_key,
    status
from {{ ref('rec_espn__matchup_stat_differences') }}
where status in ('unexplained', 'missing_ours', 'missing_espn', 'formula_mismatch')

union all

select
    'register row explains nothing' as finding,
    register.matchup_id,
    register.team_id,
    register.stat_id,
    coalesce(differences.status, 'no such side or stat') as status
from {{ ref('espn_reconciliation_residuals') }} as register
left join {{ ref('rec_espn__matchup_stat_differences') }} as differences
    on differences.matchup_id = register.matchup_id
    and differences.fantasy_team_id = register.team_id
    and differences.stat_key = register.stat_id
-- A register row is checked wherever its matchup exists at ESPN. One whose matchup is
-- absent altogether is left to rec_espn__register_matchups_exist, a warning: the CI
-- fixtures hold 2 of the season's matchups, so there every row is absent.
where register.matchup_id in (
        select matchup_id from {{ ref('stg_espn__matchup_category_results') }}
    )
  and coalesce(differences.status, 'missing') not in ('registered', 'unverified')
