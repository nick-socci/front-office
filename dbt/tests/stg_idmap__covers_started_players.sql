-- How many players who actually scored cannot be resolved to an MLBAM id.
--
-- Warns rather than fails, because the gap is real and outside our control: the SFBB
-- map lags for players called up late. On the 2026 season this returns 9 players out of
-- 493 rostered (99.41% of started entries resolve by id). They are genuine major
-- leaguers -- Michael Petersen pitched 64 games -- so consumers fall back to an
-- unambiguous name match (see docs/examples/roster_day_query.sql).
--
-- It errors if the gap grows past 25 players, which would mean the map itself broke
-- rather than lagging.

{{ config(severity='error', warn_if='>0', error_if='>25') }}

select distinct
    entries.espn_player_id,
    entries.player_name
from {{ ref('stg_espn__roster_entries') }} as entries
left join {{ ref('stg_idmap__players') }} as crosswalk
    on crosswalk.espn_player_id = entries.espn_player_id
where crosswalk.mlbam_player_id is null
  and entries.lineup_slot not in ('BE', 'IL')
