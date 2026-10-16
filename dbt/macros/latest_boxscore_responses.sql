{#
  The latest landed boxscore response for each game.

  A boxscore snapshot is the whole game as the official scorer last left it, so the
  newest one supersedes earlier ones entirely. Staging and the tests that compare against
  the source read games through this, so both judge the same snapshot.

  The newest fetched_at is found on the manifest's columns alone, and the capture view's
  rows are kept by a semi-join on file_path: ranking parsed captures in a window holds
  every snapshot in memory at once (spec 0150, R3.6). Every capture of a game at its
  newest fetched_at is kept, as before.
#}

{% macro fo_latest_boxscore_responses() %}

    select captures.*
    from {{ ref('stg_raw__mlb_boxscore') }} as captures
    where captures.file_path in (
        select keys.file_path
        from {{ fo_capture_keys() }} as keys
        inner join (
            select
                {{ fo_request_param('request_key', 'gamePk') }} as game_pk,
                max(fetched_at) as fetched_at
            from {{ fo_capture_keys() }}
            where source = 'mlb'
              and endpoint = 'boxscore'
            group by 1
        ) as latest
            on latest.game_pk = {{ fo_request_param('keys.request_key', 'gamePk') }}
            and latest.fetched_at = keys.fetched_at
        where keys.source = 'mlb'
          and keys.endpoint = 'boxscore'
    )

{%- endmacro %}
