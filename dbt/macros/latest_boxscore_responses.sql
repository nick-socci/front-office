{#
  The latest landed boxscore response for each game.

  A boxscore snapshot is the whole game as the official scorer last left it, so the
  newest one supersedes earlier ones entirely. Staging and the tests that compare against
  the source read games through this, so both judge the same snapshot.

  The newest fetched_at is found from narrow columns first and the payloads joined after:
  ranking whole payloads in a window function holds every snapshot in memory at once.

  `relation` is what to read instead of the raw source, on both sides of the join. The
  models built a season at a time pass ref('stg_raw__season_responses'), so dbt can filter
  each batch to one season on its event time and both sides see the same season;
  season_start is carried out only then (spec 0143).
#}

{% macro fo_latest_boxscore_responses(relation=none) %}

    select
        responses.payload,
        responses.fetched_at,
        responses.request_key
        {%- if relation %},
        responses.season_start
        {%- endif %}
    from {{ relation or source('raw', 'api_responses') }} as responses
    inner join (
        select
            {{ fo_request_param('request_key', 'gamePk') }} as game_pk,
            max(fetched_at) as fetched_at
        from {{ relation or source('raw', 'api_responses') }}
        where source = 'mlb'
          and endpoint = 'boxscore'
        group by 1
    ) as latest
        on latest.game_pk = {{ fo_request_param('responses.request_key', 'gamePk') }}
        and latest.fetched_at = responses.fetched_at
    where responses.source = 'mlb'
      and responses.endpoint = 'boxscore'

{%- endmacro %}
