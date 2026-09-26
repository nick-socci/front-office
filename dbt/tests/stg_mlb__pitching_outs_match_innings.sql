-- MLB reports both `outs` and `inningsPitched` ("6.1" = 6 and 1/3). They must agree.
--
-- This is the cross-check that makes storing outs safe, and it exercises
-- fo_innings_to_outs against every real pitching line in the season. That macro becomes
-- load-bearing for ESPN, which reports only the notation.

select
    game_pk,
    mlbam_player_id,
    innings_pitched,
    outs_recorded,
    {{ fo_innings_to_outs('innings_pitched') }} as outs_from_innings
from {{ ref('stg_mlb__pitching_game_logs') }}
where innings_pitched is not null
  and {{ fo_innings_to_outs('innings_pitched') }} != outs_recorded
