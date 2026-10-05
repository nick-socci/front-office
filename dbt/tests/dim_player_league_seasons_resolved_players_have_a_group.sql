-- A player with an MLBAM id in a league-season must have a replacement group there: it is
-- null only for the unresolved (R1.4). Returns every row that has an id and no group.
--
-- Catches the group rule falling through for a player whose default position is null
-- (a transaction-only player) or one that is neither SP, RP nor a position the rule
-- covers, which downstream would drop his value rows without a trace. Each row is a
-- league-season's own, so a group missing in one season is not hidden by another's.

select
    platform,
    league_id,
    season,
    platform_player_id,
    mlbam_player_id,
    default_position
from {{ ref('dim_player_league_seasons') }}
where mlbam_player_id is not null
  and replacement_group is null
