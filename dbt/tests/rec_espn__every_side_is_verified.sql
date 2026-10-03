{{ config(severity='warn') }}

-- Sides the reconciliation skipped because their inputs are unverified (#25). On the
-- real warehouse this should be empty: a skipped side is one the reconciliation proves
-- nothing about. A warning, not an error, because the CI fixtures are incomplete on
-- purpose and every fixture side is unverified.

select distinct matchup_id, fantasy_team_id
from {{ ref('rec_espn__matchup_stat_differences') }}
where status = 'unverified'
