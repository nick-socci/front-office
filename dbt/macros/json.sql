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

{#
  Parse one part of a payload into a typed value, in a single pass.

  For payloads too large to read field by field: the caller names the fields it wants in
  an explicit schema and gets a typed list or struct back, so the payload can be dropped
  before any unnest (AGENTS.md rule 1). The schema string is DuckDB's; the BigQuery
  variant of this macro will need its own form of it.
#}
{% macro fo_json_parse(column, path, schema) %}
    from_json(json_extract({{ column }}, '{{ path }}'), '{{ schema | trim }}')
{%- endmacro %}
