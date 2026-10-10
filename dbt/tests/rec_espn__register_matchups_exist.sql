{{ config(severity='warn') }}

-- Register rows that fct_matchup_scores_match_espn can't check, with why. On the real
-- warehouse this should be empty:
--   league_season_not_loaded  the row's league and season are not a loaded ESPN
--                             league-season: a mistyped league id or season. Such a row is
--                             not in rec_espn__register_rows, which holds loaded
--                             league-seasons only, so it is read from the seed here.
--   matchup_absent            the league-season is loaded but ESPN has no such matchup in
--                             it: a mistyped matchup id.
-- A warning because in CI the register describes a league that is not loaded, so every
-- register row lands here.

select
    'league_season_not_loaded' as finding,
    register.league_id,
    register.season,
    register.matchup_id,
    register.team_id,
    register.stat_id
from {{ ref('espn_reconciliation_residuals') }} as register
where not exists (
    select 1
    from {{ ref('int_fantasy__league_seasons') }} as league_seasons
    where league_seasons.platform = 'espn'
        and league_seasons.league_id = register.league_id
        and league_seasons.season = register.season
)

union all

select
    'matchup_absent' as finding,
    league_id,
    season,
    matchup_id,
    team_id,
    stat_id
from {{ ref('rec_espn__register_rows') }}
where problem = 'matchup_absent'
