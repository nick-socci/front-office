{#
  JSON accessors, in one place.

  Models never write DuckDB's JSON syntax directly. When the warehouse moves to
  BigQuery these macros gain an adapter.dispatch variant and the models stay
  untouched -- that is the whole point of routing every JSON read through here.
#}

{% macro fo_json_array(column, path) %}
    json_extract({{ column }}, '{{ path }}')::JSON[]
{%- endmacro %}

{% macro fo_json_text(column, path) %}
    nullif({{ column }} ->> '{{ path }}', '')
{%- endmacro %}

{% macro fo_json_int(column, path) %}
    try_cast({{ column }} ->> '{{ path }}' as bigint)
{%- endmacro %}

{% macro fo_json_bool(column, path) %}
    try_cast({{ column }} ->> '{{ path }}' as boolean)
{%- endmacro %}

{% macro fo_json_date(column, path) %}
    try_cast({{ column }} ->> '{{ path }}' as date)
{%- endmacro %}

{% macro fo_json_timestamp(column, path) %}
    try_cast({{ column }} ->> '{{ path }}' as timestamptz)
{%- endmacro %}
