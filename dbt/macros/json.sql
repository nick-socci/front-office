{#
  JSON accessors, in one place.

  Models and singular tests never write DuckDB's JSON syntax directly (from_json,
  json_extract*, json_keys, ->>, ::JSON): ingestion/tests/test_dbt_json_rule.py fails the
  build when one does. When the warehouse moves to BigQuery these macros gain an
  adapter.dispatch variant and the models stay untouched -- that is the whole point of
  routing every JSON read through here.

  Every path is a constant, written into the SQL text. BigQuery requires constant JSON
  paths, so a model that needs the same read for home and away generates one branch per
  side in Jinja; it never builds a path from a column.
#}

{% macro fo_json_array(column, path) %}
    json_extract({{ column }}, '{{ path }}')::JSON[]
{%- endmacro %}

{#
  The value at a path as text, exactly as stored: no empty-string-to-null step, no cast.

  fo_json_text turns '' into NULL, which is right for a field read as data. This is for a
  read whose result must stay what the raw operator gave -- a deduplication key, or a
  filter -- where treating '' as NULL could change which rows are kept.
#}
{% macro fo_json_string(column, path) %}
    {{ column }} ->> '{{ path }}'
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
  variant of this macro will need its own form of it (JSON_QUERY_ARRAY plus per-field
  extraction).
#}
{% macro fo_json_parse(column, path, schema) %}
    from_json(json_extract({{ column }}, '{{ path }}'), '{{ schema | trim }}')
{%- endmacro %}


{#
  The keys of the object at a path, as a list of text.

  For objects whose KEYS are the fact -- {"69": 12.0, "70": 8.0} maps scoring period to
  points. NULL when the path is absent, so unnest(...) of it yields no rows.
#}
{% macro fo_json_keys(column, path) %}
    json_keys({{ column }}, '{{ path }}')
{%- endmacro %}

{#
  The values of the object at a path, as a list of JSON, in the same order as
  fo_json_keys of the same path. Unnest both in one SELECT to get each key beside its
  value without building a path from the key; read a field of a value with the other
  accessors, using '$' for a value that is itself a number or string.
#}
{% macro fo_json_values(column, path) %}
    json_extract({{ column }}, '{{ path }}.*')::JSON[]
{%- endmacro %}

{#
  Whether anything is at a path (true even for a JSON null; false only when absent).
#}
{% macro fo_json_exists(column, path) %}
    json_extract({{ column }}, '{{ path }}') is not null
{%- endmacro %}
