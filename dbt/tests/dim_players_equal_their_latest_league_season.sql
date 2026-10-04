-- Each dim_players row must equal the league-season row it is taken from: his latest
-- (highest season, then latest last_rostered_date with nulls last, then lowest league_id).
-- Returns the players whose MLBAM id, resolution or name differs from that row, or who have
-- no row in dim_player_league_seasons at all.
--
-- dim_players is exempt from the isolation check's row comparison, because it is defined
-- over everything loaded (R5.3); this test holds it to R4.9 instead. It catches a name taken
-- from one observation and an id from another, and a dim_players row for a player no
-- league-season holds. It restates the ordering on purpose: it is the independent
-- definition the model is checked against.

with latest as (

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

)

select
    coalesce(players.platform, latest.platform) as platform,
    coalesce(players.platform_player_id, latest.platform_player_id) as platform_player_id
from {{ ref('dim_players') }} as players
full outer join latest
    on latest.platform = players.platform
    and latest.platform_player_id = players.platform_player_id
where players.platform_player_id is null
    or latest.platform_player_id is null
    or players.mlbam_player_id is distinct from latest.mlbam_player_id
    or players.player_resolution is distinct from latest.player_resolution
    or players.player_name is distinct from latest.player_name
