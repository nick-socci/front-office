{{ config(severity='warn') }}

-- Warns when one platform player has more than one distinct non-null MLB id across his
-- league-seasons (R2.3). The match from a platform player to an MLB player is made per
-- league-season (#28), so a name fallback that resolved him differently in two leagues or
-- seasons would go unnoticed: each league-season keeps its own id, and both MLB players
-- have a dim_players row, so nothing else fails.
-- Returns one row per such platform player, with the ids and the seasons that carry them.
--
-- A warning, not an error: each league-season's number is right by its own match. 0 rows
-- are expected on the real 2026 season and in the fixtures.

select
    platform,
    platform_player_id,
    list(distinct mlbam_player_id order by mlbam_player_id) as mlbam_player_ids,
    list(distinct season order by season) as seasons
from {{ ref('dim_player_league_seasons') }}
where mlbam_player_id is not null
group by platform, platform_player_id
having count(distinct mlbam_player_id) > 1
