-- dim_players must hold exactly the MLB ids the warehouse knows (R1.1): every id in a
-- landed player list, every id with a played day in the game logs, and every MLB id a
-- league-season resolved a platform player to; and no other id.
-- Returns each id present on one side only, with the side it is missing from.
--
-- It catches a free agent dropped by an inner join, a player with no game and no list
-- dropped for want of a name, and a row for an id nothing holds. The union is restated
-- here on purpose: it is the independent definition the model is checked against, not
-- a copy of the model's `known_players`.
--
-- dim_players is exempt from the isolation check's row comparison, because it is defined
-- over everything loaded; this test, run in every build, is what holds it instead.

with expected as (

    select mlbam_player_id from {{ ref('stg_mlb__players') }}
    union
    select mlbam_player_id from {{ ref('int_mlb__player_game_days') }}
    union
    select mlbam_player_id
    from {{ ref('dim_player_league_seasons') }}
    where mlbam_player_id is not null

)

select
    coalesce(players.mlbam_player_id, expected.mlbam_player_id) as mlbam_player_id,
    case
        when players.mlbam_player_id is null then 'missing from dim_players'
        else 'in dim_players but known to nothing'
    end as problem
from {{ ref('dim_players') }} as players
full outer join expected
    on expected.mlbam_player_id = players.mlbam_player_id
where
    players.mlbam_player_id is null
    or expected.mlbam_player_id is null
