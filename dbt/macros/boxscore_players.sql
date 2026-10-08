{#
  One row per (game, team side, player) from landed boxscores.

  Two shapes make this awkward enough to keep in one place:
  * `teams.home.players` is a JSON *object* keyed "ID669016", not an array. Its values
    are the players, so they are taken as a list (fo_json_values) and unnested; the key
    repeats the player id that is inside each value, and is not needed.
  * the payload has no gamePk, so it comes from the request metadata.

  One branch per side, so every JSON path is a constant (the fo_json_* rule: BigQuery
  needs constant paths). Each branch reads what it needs from the payload and drops it;
  the unnest happens afterwards, on the list alone (AGENTS.md rule 1).

  Only each game's latest snapshot is read (fo_latest_boxscore_responses). Deduplicating
  per player instead would keep an older row for a player a correction removed.

  Both batting and pitching models build on this; each then reads its own stats block.
#}

{% macro fo_boxscore_players() %}

with responses as (

    {{ fo_latest_boxscore_responses() }}

),

sides as (

    {% for side in ['home', 'away'] %}
    select
        fetched_at,
        request_key,
        '{{ side }}' as side,
        {{ fo_json_int('payload', '$.teams.' ~ side ~ '.team.id') }} as team_id,
        {{ fo_json_values('payload', '$.teams.' ~ side ~ '.players') }} as players
    from responses
    {{ 'union all' if not loop.last }}
    {% endfor %}

)

select
    {{ fo_request_param('request_key', 'gamePk') }} as game_pk,
    side,
    team_id,
    unnest(players) as player,
    fetched_at
from sides

{%- endmacro %}
