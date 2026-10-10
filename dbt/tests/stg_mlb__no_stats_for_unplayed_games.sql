-- No batting or pitching line belongs to a game that was never played.
--
-- A cancelled game still has a boxscore (rosters, no stats), and ingestion skips it
-- (#36). The audit checks that on the landed files; this checks the warehouse, so a
-- line that slipped through can't be summed into a fantasy day as real production.

select
    'batting' as side,
    logs.game_pk,
    logs.mlbam_player_id
from {{ ref('stg_mlb__batting_game_logs') }} as logs
inner join {{ ref('stg_mlb__games') }} as games
    on games.game_pk = logs.game_pk
where not games.is_played

union all

select
    'pitching' as side,
    logs.game_pk,
    logs.mlbam_player_id
from {{ ref('stg_mlb__pitching_game_logs') }} as logs
inner join {{ ref('stg_mlb__games') }} as games
    on games.game_pk = logs.game_pk
where not games.is_played
