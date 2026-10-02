-- One row per side of a played head-to-head matchup: a team and its opponent.
--
-- The platform seam for "who played whom". Marts score a side against its opponent, so
-- the long form -- each matchup twice, once from each team's view -- is the shape they
-- want, and it hides ESPN's home/away payload layout behind is_home.
--
-- Playoff byes are not here: stg_espn__matchups drops them, because a bye has no
-- opponent and no result. ESPN still reports a bye team's stats for the period; the
-- reconciliation scopes those 2 sides out explicitly rather than by omission.
--
-- A table, for the same reason as the other interfaces: a contract's not_null
-- constraints are silently dropped on a view.

{{ config(materialized='table') }}

select
    'espn' as platform,
    league_id,
    season,
    matchup_id,
    matchup_period,
    home_team_id as fantasy_team_id,
    away_team_id as opponent_team_id,
    true as is_home,
    playoff_tier
from {{ ref('stg_espn__matchups') }}

union all

select
    'espn' as platform,
    league_id,
    season,
    matchup_id,
    matchup_period,
    away_team_id as fantasy_team_id,
    home_team_id as opponent_team_id,
    false as is_home,
    playoff_tier
from {{ ref('stg_espn__matchups') }}
