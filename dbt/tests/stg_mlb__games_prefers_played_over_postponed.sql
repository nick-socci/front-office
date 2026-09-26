-- A game_pk whose source data contains a non-postponed entry must not be represented in
-- the model by the postponed placeholder. Guards the dedupe tie-break in
-- stg_mlb__games: without it, 29 makeup games in 2026 lose to their postponements.

with source_games as (

    select
        unnest({{ fo_json_array('payload', '$.dates[*].games[*]') }}) as game
    from {{ source('raw', 'api_responses') }}
    where source = 'mlb'
      and endpoint = 'schedule'

),

played_game_pks as (

    select distinct {{ fo_json_int('game', '$.gamePk') }} as game_pk
    from source_games
    where {{ fo_json_text('game', '$.status.detailedState') }} != 'Postponed'

)

select g.game_pk
from {{ ref('stg_mlb__games') }} as g
inner join played_game_pks as p on p.game_pk = g.game_pk
where g.is_postponed
