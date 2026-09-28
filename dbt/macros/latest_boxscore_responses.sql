{#
  The latest landed boxscore response for each game.

  A boxscore snapshot is the whole game as the official scorer last left it, so the
  newest one supersedes earlier ones entirely. Staging and the tests that compare against
  the source read games through this, so both judge the same snapshot.

  The newest fetched_at is found from narrow columns first and the payloads joined after:
  ranking whole payloads in a window function holds every snapshot in memory at once.
#}

{% macro fo_latest_boxscore_responses() %}

    select
        responses.payload,
        responses.fetched_at,
        responses.request_key
    from {{ source('raw', 'api_responses') }} as responses
    inner join (
        select
            {{ fo_request_param('request_key', 'gamePk') }} as game_pk,
            max(fetched_at) as fetched_at
        from {{ source('raw', 'api_responses') }}
        where source = 'mlb'
          and endpoint = 'boxscore'
        group by 1
    ) as latest
        on latest.game_pk = {{ fo_request_param('responses.request_key', 'gamePk') }}
        and latest.fetched_at = responses.fetched_at
    where responses.source = 'mlb'
      and responses.endpoint = 'boxscore'

{%- endmacro %}
