-- One row per platform player id, across every league and season loaded (#28, ADR 0012):
-- who he is, as a reference. It holds the MLBAM id, resolution and name of his LATEST
-- league-season (highest season, then latest last_rostered_date with nulls last, then lowest
-- league_id so the choice never depends on input order), all three copied from that one row
-- of dim_player_league_seasons. Building it from that table means the name shown and the
-- name matched on are the same observation, and that the two models hold the same players.
--
-- It is a reference. No league-season number reads from it: an MLBAM id, a replacement
-- group or a rostered date is true of a player in a league-season, and those live in
-- dim_player_league_seasons. The position, group and rostered dates that dim_players held
-- while it described one league-season moved there with the same values; keeping them here
-- would have told a 2026 query a 2027 answer.
--
-- A fact table joins to it to check a player exists (relationships tests); a latest
-- league-season's MLBAM id is not the id of any other league-season's row.

{{ config(materialized='table') }}

select
    platform,
    platform_player_id,
    mlbam_player_id,
    player_resolution,
    player_name
from {{ ref('dim_player_league_seasons') }}
qualify row_number() over (
    partition by platform, platform_player_id
    order by season desc, last_rostered_date desc nulls last, league_id
) = 1
