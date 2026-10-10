-- One row per MLB player, keyed by his MLB id, for every player the warehouse holds (#60,
-- ADR 0033, which amends ADR 0012): who he is, as a reference. Before this, the table had
-- one row per fantasy platform player, which made it a reference within ESPN only and left
-- most of the players in the MLB game logs, the production every number is measured from,
-- with no row and no name.
--
-- WHY the key is MLB's. Production is measured by MLB id, so every mart that names a player
-- joins through it. A platform's own id is a bridge to it, and that bridge lives in
-- dim_player_league_seasons (ADR 0034): the match is made per league-season (#28), so the
-- table at that grain is where an MLB id belongs next to a platform id. A platform player
-- with no MLB id in any league-season has no row here; he stays there as `unresolved`.
--
-- WHY everyone loaded. A free agent whose days build a replacement pool needs a name as
-- much as a rostered player does. The rows are every id in a landed player list, every id
-- with a played day, and every MLB id a league-season resolved a platform player to (four
-- of 2026's resolved players are in no list and have no game).
--
-- Name and attributes (ADR 0035). The name is the player list's, from the latest season
-- that lists him; failing that the name on his latest game line; failing that the latest
-- non-null name a league-season gave him. `name_source` says which. The five attributes
-- are MLB's, from the same list row, and null for a player no list holds: borrowing them
-- from another source would be inventing them. Each "latest" ends in a tie-break that does
-- not depend on input order (AGENTS.md rule 5).
--
-- It is defined over everything loaded, so a combined build and a single-league build
-- differ, which is why the tenant-isolation script exempts it by name and its own tests
-- run in every build.

{{ config(materialized='table') }}

with listed_players as (

    select
        mlbam_player_id,
        player_name,
        primary_position,
        bats,
        throws,
        birth_date,
        mlb_debut_date
    from {{ ref('stg_mlb__players') }}
    qualify row_number() over (
        partition by mlbam_player_id
        order by season desc
    ) = 1

),

game_names as (

    select
        logs.mlbam_player_id,
        logs.player_name,
        logs.game_pk,
        games.official_date
    from (
        select
            mlbam_player_id,
            player_name,
            game_pk
        from {{ ref('stg_mlb__batting_game_logs') }}
        union all
        select
            mlbam_player_id,
            player_name,
            game_pk
        from {{ ref('stg_mlb__pitching_game_logs') }}
    ) as logs
    inner join {{ ref('stg_mlb__games') }} as games
        on games.game_pk = logs.game_pk
    where logs.player_name is not null

),

latest_game_names as (

    select
        mlbam_player_id,
        player_name
    from game_names
    qualify row_number() over (
        partition by mlbam_player_id
        order by official_date desc, game_pk desc, player_name asc
    ) = 1

),

platform_names as (

    select
        mlbam_player_id,
        player_name
    from {{ ref('dim_player_league_seasons') }}
    where
        mlbam_player_id is not null
        and player_name is not null
    qualify row_number() over (
        partition by mlbam_player_id
        order by
            season desc, last_rostered_date desc nulls last,
            league_id asc, platform asc, platform_player_id asc
    ) = 1

),

known_players as (

    select mlbam_player_id from {{ ref('stg_mlb__players') }}
    union
    select mlbam_player_id from {{ ref('int_mlb__player_game_days') }}
    union
    select mlbam_player_id
    from {{ ref('dim_player_league_seasons') }}
    where mlbam_player_id is not null

)

select
    known_players.mlbam_player_id,
    coalesce(
        listed_players.player_name,
        latest_game_names.player_name,
        platform_names.player_name
    ) as player_name,
    case
        when listed_players.player_name is not null then 'mlb_players'
        when latest_game_names.player_name is not null then 'mlb_boxscore'
        when platform_names.player_name is not null then 'platform'
    end as name_source,
    listed_players.primary_position,
    listed_players.bats,
    listed_players.throws,
    listed_players.birth_date,
    listed_players.mlb_debut_date
from known_players
left join listed_players
    on listed_players.mlbam_player_id = known_players.mlbam_player_id
left join latest_game_names
    on latest_game_names.mlbam_player_id = known_players.mlbam_player_id
left join platform_names
    on platform_names.mlbam_player_id = known_players.mlbam_player_id
