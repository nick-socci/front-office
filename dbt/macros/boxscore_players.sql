{#
  One row per (game, team side, player) from landed boxscores.

  Two shapes make this awkward enough to keep in one place:
  * `teams.home.players` is a JSON *object* keyed "ID669016", not an array, so the keys
    are listed with json_keys and joined back onto the payload.
  * the payload has no gamePk, so it comes from the request metadata.

  Both batting and pitching models build on this; each then reads its own stats block.
#}

{% macro fo_boxscore_players() %}

with responses as (

    select
        payload,
        fetched_at,
        request_key
    from {{ source('raw', 'api_responses') }}
    where source = 'mlb'
      and endpoint = 'boxscore'

),

sides as (

    select
        payload,
        fetched_at,
        request_key,
        unnest(['home', 'away']) as side
    from responses

),

player_keys as (

    select
        payload,
        fetched_at,
        request_key,
        side,
        unnest(json_keys(payload, '$.teams.' || side || '.players')) as player_key
    from sides

)

select
    {{ fo_request_param('request_key', 'gamePk') }} as game_pk,
    side,
    try_cast(json_extract_string(payload, '$.teams.' || side || '.team.id') as bigint) as team_id,
    json_extract(payload, '$.teams.' || side || '.players.' || player_key) as player,
    fetched_at
from player_keys

{%- endmacro %}
