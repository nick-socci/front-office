{#
  The newest landed ESPN response for one endpoint.

  Settings, teams and rosters are snapshot endpoints, so the raw table holds every
  version ever fetched. Staging wants the latest per league/season (and per scoring
  period for rosters), which is what this filters to.
#}

{% macro fo_espn_latest(endpoint, extra_partition=none) %}

    select
        payload,
        request_key,
        fetched_at
    from {{ source('raw', 'api_responses') }}
    where source = 'espn'
      and endpoint = '{{ endpoint }}'
    {%- if extra_partition %}
    qualify row_number() over (
        partition by {{ fo_request_param('request_key', extra_partition) }}
        order by fetched_at desc
    ) = 1
    {%- else %}
    qualify row_number() over (order by fetched_at desc) = 1
    {%- endif %}

{%- endmacro %}
