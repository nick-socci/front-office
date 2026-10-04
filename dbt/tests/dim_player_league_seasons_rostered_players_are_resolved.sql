{{ config(severity='warn') }}

-- A player who sat on a roster in a league-season but has no MLBAM id there is a gap to
-- investigate (R4.10): his started days produce no MLB numbers and his value is zeroes.
-- Warns on every build, naming him, rather than failing: the id map lags for late call-ups,
-- and the name fallback can fail for a name two MLB players share. Transaction-only players
-- are out of scope (their resolution is by id alone and is reported by their own tests).
-- 0 rows on the 2026 season.

select
    platform,
    league_id,
    season,
    platform_player_id,
    player_name
from {{ ref('dim_player_league_seasons') }}
where not is_transaction_only
  and player_resolution = 'unresolved'
