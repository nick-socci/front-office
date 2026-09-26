{#
  Recover a request parameter from the canonical request_key.

  Some responses do not contain their own identity: an MLB boxscore payload has no
  gamePk, because the id is a path segment. Ingestion records it in the request metadata,
  and this is how models read it back.
#}

{% macro fo_request_param(column, name) %}
    try_cast(regexp_extract({{ column }}, '{{ name }}=([0-9]+)', 1) as bigint)
{%- endmacro %}
