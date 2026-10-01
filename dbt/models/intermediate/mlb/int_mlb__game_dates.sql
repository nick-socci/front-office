-- One row per MLB official date: how many games were played, and how many of those
-- have landed boxscores.
--
-- This is what lets a started player-day with no stats be called a real day off. If
-- every played game on a date is loaded, a resolved player who appears in none of them
-- did not play -- there is no game he could be missing from. If one isn't loaded, he
-- might be in it, so the day can't be called verified (#25).
--
-- "Loaded" means the game has batting logs. Every played game has batters on both
-- sides, so a played game with none has no usable boxscore. Postponed and cancelled
-- games are counted out of both numbers: they never had stats to load.
--
-- A date with no MLB games at all has no row here, which downstream reads as complete.
--
-- A table: it is tiny, and every started roster-day joins to it.

{{ config(materialized='table') }}

with loaded as (

    select distinct game_pk
    from {{ ref('stg_mlb__batting_game_logs') }}

)

select
    games.official_date,
    count(*) filter (where games.is_played) as played_games,
    count(*) filter (where games.is_played and loaded.game_pk is not null) as loaded_games,
    count(*) filter (where games.is_played and loaded.game_pk is null) = 0 as is_complete
from {{ ref('stg_mlb__games') }} as games
left join loaded
    on loaded.game_pk = games.game_pk
group by games.official_date
