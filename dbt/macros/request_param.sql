{#
  Recover a request parameter from the canonical request_key.

  Some responses do not contain their own identity: an MLB boxscore payload has no
  gamePk, because the id is a path segment. Ingestion records it in the request metadata,
  and this is how models read it back.
#}

{% macro fo_request_param(column, name) %}
    {{- return(adapter.dispatch('fo_request_param')(column, name)) -}}
{% endmacro %}

{% macro duckdb__fo_request_param(column, name) %}
    try_cast(regexp_extract({{ column }}, '{{ name }}=([0-9]+)', 1) as bigint)
{%- endmacro %}

{# With one capturing group BigQuery's regexp_extract returns the group. #}
{% macro bigquery__fo_request_param(column, name) %}
    safe_cast(regexp_extract({{ column }}, r'{{ name }}=([0-9]+)') as int64)
{%- endmacro %}
