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
--
-- The register-side rule is the problem column of rec_espn__register_rows, where a unit
-- test holds it. A row whose matchup ESPN lacks, or whose league-season is not loaded, is
-- left to rec_espn__register_matchups_exist (a warning).

select
    'stat' as finding,
    league_id,
    season,
    matchup_id,
    fantasy_team_id,
    stat_key,
    status
from {{ ref('rec_espn__matchup_stat_differences') }}
where status in ('unexplained', 'missing_ours', 'missing_espn', 'formula_mismatch')

union all

select
    'register row explains nothing' as finding,
    league_id,
    season,
    matchup_id,
    team_id,
    stat_id,
    coalesce(reconciliation_status, 'no such side or stat') as status
from {{ ref('rec_espn__register_rows') }}
where problem = 'explains_nothing'
