{#
  The newest landed ESPN response for one endpoint, one per league and season.

  Settings, teams, matchups and rosters are snapshot endpoints, so the raw table holds
  every version ever fetched. Staging wants the latest of each league-season (and of each
  scoring period, for rosters), which is what this filters to. Selecting the latest
  globally would let whichever league was fetched last hide every other league.

  league_id (text) and season (integer) come from the `partitions` the loader stored, not
  from the payload: they are the identity the capture was filed under. A singular test
  checks that the payload agrees.

  One pass with QUALIFY, deliberately. A first version of this change ranked narrow
  columns and joined the payloads back on file_path, as latest_boxscore_responses.sql
  does for boxscores. Measured on the 2026 season at dbt's default four threads, that
  form ran DuckDB out of memory (23.9 GiB) in stg_espn__player_game_stats and the MLB
  game logs building beside it, where this form builds in the same time and memory as
  before #28: the join keeps every roster payload of the endpoint on its build side
  while three roster models parse them at once. file_path is unique per response and is
  the deterministic tie-break.
#}

{% macro fo_espn_latest(endpoint, extra_partition=none) %}

    select
        payload,
        request_key,
        fetched_at,
        {{ fo_json_text('partitions', '$.league_id') }} as league_id,
        {{ fo_json_int('partitions', '$.season') }}::integer as season
    from {{ source('raw', 'api_responses') }}
    where source = 'espn'
      and endpoint = '{{ endpoint }}'
    qualify row_number() over (
        partition by
            {{ fo_json_text('partitions', '$.league_id') }},
            {{ fo_json_int('partitions', '$.season') }}
            {%- if extra_partition %},
            {{ fo_request_param('request_key', extra_partition) }}
            {%- endif %}
        order by fetched_at desc, file_path desc
    ) = 1

{%- endmacro %}
