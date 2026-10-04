{#
  The newest landed ESPN response for one endpoint, one per league and season.

  Settings, teams, matchups and rosters are snapshot endpoints, so the raw table holds
  every version ever fetched. Staging wants the latest of each league-season (and of each
  scoring period, for rosters), which is what this filters to. Selecting the latest
  globally would let whichever league was fetched last hide every other league.

  league_id (text) and season (integer) come from the `partitions` the loader stored, not
  from the payload: they are the identity the capture was filed under. A singular test
  checks that the payload agrees.

  The newest response is chosen from narrow columns first and the payloads joined after:
  ranking whole payloads in a window function holds every snapshot in memory at once
  (see latest_boxscore_responses.sql). file_path is unique per response, so it is the
  deterministic tie-break and the join key.
#}

{% macro fo_espn_latest(endpoint, extra_partition=none) %}

    select
        responses.payload,
        responses.request_key,
        responses.fetched_at,
        responses.league_id,
        responses.season
    from (
        select
            file_path,
            payload,
            request_key,
            fetched_at,
            {{ fo_json_text('partitions', '$.league_id') }} as league_id,
            {{ fo_json_int('partitions', '$.season') }}::integer as season
        from {{ source('raw', 'api_responses') }}
        where source = 'espn'
          and endpoint = '{{ endpoint }}'
    ) as responses
    inner join (
        select
            file_path
        from (
            select
                file_path,
                row_number() over (
                    partition by
                        {{ fo_json_text('partitions', '$.league_id') }},
                        {{ fo_json_int('partitions', '$.season') }}
                        {%- if extra_partition %},
                        {{ fo_request_param('request_key', extra_partition) }}
                        {%- endif %}
                    order by fetched_at desc, file_path desc
                ) as recency
            from {{ source('raw', 'api_responses') }}
            where source = 'espn'
              and endpoint = '{{ endpoint }}'
        )
        where recency = 1
    ) as newest
        on newest.file_path = responses.file_path

{%- endmacro %}
