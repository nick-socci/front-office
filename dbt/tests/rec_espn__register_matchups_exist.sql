{{ config(severity='warn') }}

-- Register rows whose matchup isn't in ESPN's data at all, so
-- fct_matchup_scores_match_espn can't check them. On the real warehouse this should be
-- empty: a row here is a mistyped matchup id. A warning because the CI fixtures hold
-- only 2 matchups, so every register row lands here in CI.

select register.matchup_id, register.team_id, register.stat_id
from {{ ref('espn_reconciliation_residuals') }} as register
where register.matchup_id not in (
    select matchup_id from {{ ref('stg_espn__matchup_category_results') }}
)
