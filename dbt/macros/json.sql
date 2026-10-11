{#
  JSON accessors, in one place.

  Models and singular tests never write DuckDB's JSON syntax directly (from_json,
  json_extract*, json_keys, ->>, ::JSON): ingestion/tests/test_dbt_json_rule.py fails the
  build when one does. Each accessor has a form per warehouse and dbt picks one by the
  target (adapter.dispatch, as in portable.sql): the duckdb__ forms are the SQL these
  macros always emitted, and the bigquery__ forms are at the end of this file. A model
  calls the one name and is the same file on both -- that is the whole point of routing
  every JSON read through here.

  Every path is a constant, written into the SQL text. BigQuery requires constant JSON
  paths, so a model that needs the same read for home and away generates one branch per
  side in Jinja; it never builds a path from a column.
#}

{% macro fo_json_array(column, path) %}
    {{- return(adapter.dispatch('fo_json_array')(column, path)) -}}
{% endmacro %}
{% macro duckdb__fo_json_array(column, path) %}
    json_extract({{ column }}, '{{ path }}')::JSON[]
{%- endmacro %}

{#
  The value at a path as text, exactly as stored: no empty-string-to-null step, no cast.

  fo_json_text turns '' into NULL, which is right for a field read as data. This is for a
  read whose result must stay what the raw operator gave -- a deduplication key, or a
  filter -- where treating '' as NULL could change which rows are kept.
#}
{% macro fo_json_string(column, path) %}
    {{- return(adapter.dispatch('fo_json_string')(column, path)) -}}
{% endmacro %}
{% macro duckdb__fo_json_string(column, path) %}
    {{ column }} ->> '{{ path }}'
{%- endmacro %}

{% macro fo_json_text(column, path) %}
    {{- return(adapter.dispatch('fo_json_text')(column, path)) -}}
{% endmacro %}
{% macro duckdb__fo_json_text(column, path) %}
    nullif({{ column }} ->> '{{ path }}', '')
{%- endmacro %}

{% macro fo_json_int(column, path) %}
    {{- return(adapter.dispatch('fo_json_int')(column, path)) -}}
{% endmacro %}
{% macro duckdb__fo_json_int(column, path) %}
    try_cast({{ column }} ->> '{{ path }}' as bigint)
{%- endmacro %}

{% macro fo_json_bool(column, path) %}
    {{- return(adapter.dispatch('fo_json_bool')(column, path)) -}}
{% endmacro %}
{% macro duckdb__fo_json_bool(column, path) %}
    try_cast({{ column }} ->> '{{ path }}' as boolean)
{%- endmacro %}

{% macro fo_json_date(column, path) %}
    {{- return(adapter.dispatch('fo_json_date')(column, path)) -}}
{% endmacro %}
{% macro duckdb__fo_json_date(column, path) %}
    try_cast({{ column }} ->> '{{ path }}' as date)
{%- endmacro %}

{% macro fo_json_timestamp(column, path) %}
    {{- return(adapter.dispatch('fo_json_timestamp')(column, path)) -}}
{% endmacro %}
{% macro duckdb__fo_json_timestamp(column, path) %}
    try_cast({{ column }} ->> '{{ path }}' as timestamptz)
{%- endmacro %}

{#
  Parse one part of a payload into a typed value, in a single pass.

  For payloads too large to read field by field: the caller names the fields it wants in
  an explicit schema and gets a typed list or struct back, so the payload can be dropped
  before any unnest (AGENTS.md rule 1). The schema string is DuckDB's: a JSON document
  whose lists and objects mirror the payload's and whose leaves are type names. The
  BigQuery form reads the same string and takes five leaves: BIGINT, VARCHAR, DOUBLE,
  BOOLEAN, and JSON for a value to be left as it is.
#}
{% macro fo_json_parse(column, path, schema) %}
    {{- return(adapter.dispatch('fo_json_parse')(column, path, schema)) -}}
{% endmacro %}
{% macro duckdb__fo_json_parse(column, path, schema) %}
    from_json(json_extract({{ column }}, '{{ path }}'), '{{ schema | trim }}')
{%- endmacro %}


{#
  The keys of the object at a path, as a list of text.

  For objects whose KEYS are the fact -- {"69": 12.0, "70": 8.0} maps scoring period to
  points. NULL when the path is absent, so unnest(...) of it yields no rows.
#}
{% macro fo_json_keys(column, path) %}
    {{- return(adapter.dispatch('fo_json_keys')(column, path)) -}}
{% endmacro %}
{% macro duckdb__fo_json_keys(column, path) %}
    json_keys({{ column }}, '{{ path }}')
{%- endmacro %}

{#
  The values of the object at a path, as a list of JSON, in the same order as
  fo_json_keys of the same path. Unnest both in one SELECT to get each key beside its
  value without building a path from the key; read a field of a value with the other
  accessors, using '$' for a value that is itself a number or string.
#}
{% macro fo_json_values(column, path) %}
    {{- return(adapter.dispatch('fo_json_values')(column, path)) -}}
{% endmacro %}
{% macro duckdb__fo_json_values(column, path) %}
    json_extract({{ column }}, '{{ path }}.*')::JSON[]
{%- endmacro %}

{#
  Whether anything is at a path (true even for a JSON null; false only when absent).
#}
{% macro fo_json_exists(column, path) %}
    {{- return(adapter.dispatch('fo_json_exists')(column, path)) -}}
{% endmacro %}
{% macro duckdb__fo_json_exists(column, path) %}
    json_extract({{ column }}, '{{ path }}') is not null
{%- endmacro %}


{#
  The BigQuery forms. `column` is of type JSON (ADR 0052).

  What differs from DuckDB, seen on BigQuery on 2026-10-11 (spec 0130): a path takes no
  wildcard; json_query gives SQL null for an absent path and JSON null for a null;
  json_value keeps a number's text; json_keys is recursive unless told a depth, and gives
  an object's keys sorted, not in document order. No model may depend on that order.
#}
{% macro bigquery__fo_json_string(column, path) %}
    json_value({{ column }}, '{{ path }}')
{%- endmacro %}

{% macro bigquery__fo_json_text(column, path) %}
    nullif(json_value({{ column }}, '{{ path }}'), '')
{%- endmacro %}

{% macro bigquery__fo_json_int(column, path) %}
    safe_cast(json_value({{ column }}, '{{ path }}') as int64)
{%- endmacro %}

{% macro bigquery__fo_json_bool(column, path) %}
    safe_cast(json_value({{ column }}, '{{ path }}') as bool)
{%- endmacro %}

{% macro bigquery__fo_json_date(column, path) %}
    safe_cast(json_value({{ column }}, '{{ path }}') as date)
{%- endmacro %}

{% macro bigquery__fo_json_timestamp(column, path) %}
    safe_cast(json_value({{ column }}, '{{ path }}') as timestamp)
{%- endmacro %}

{% macro bigquery__fo_json_exists(column, path) %}
    json_query({{ column }}, '{{ path }}') is not null
{%- endmacro %}

{% macro bigquery__fo_json_keys(column, path) %}
    json_keys(json_query({{ column }}, '{{ path }}'), 1)
{%- endmacro %}

{#
  The values in the order of json_keys, so that a key still sits beside its own value. A
  path cannot name a key that is not a constant; a subscript can.
#}
{% macro bigquery__fo_json_values(column, path) %}
    array(
        select json_query({{ column }}, '{{ path }}')[_key]
        from unnest(json_keys(json_query({{ column }}, '{{ path }}'), 1)) as _key with offset as _at
        order by _at
    )
{%- endmacro %}

{#
  The models' paths keep DuckDB's [*]. BigQuery's path has none, and json_query_array of
  the path before it gives the elements. One [*] at the end, or two, are what the project
  uses; anything else is refused here, when the project is compiled.
#}
{% macro bigquery__fo_json_array(column, path) %}
    {%- set parts = path.split('[*]') -%}
    {%- if '.*' in path or parts | length > 3 or parts[-1] != '' -%}
        {{ exceptions.raise_compiler_error(
            "fo_json_array on BigQuery takes one [*] at the end of a path, or two: " ~ path
        ) }}
    {%- elif parts | length == 2 %}
    json_query_array({{ column }}, '{{ parts[0] }}')
    {%- elif parts | length == 3 %}
    array(
        select _inner
        from unnest(json_query_array({{ column }}, '{{ parts[0] }}')) as _outer with offset as _outer_at
        cross join unnest(json_query_array(_outer, '${{ parts[1] }}')) as _inner with offset as _inner_at
        order by _outer_at, _inner_at
    )
    {%- else -%}
        {{ exceptions.raise_compiler_error(
            "fo_json_array on BigQuery needs a [*] in its path: " ~ path
        ) }}
    {%- endif -%}
{%- endmacro %}

{% macro bigquery__fo_json_parse(column, path, schema) %}
    {{ bigquery__fo_json_parse_value(
        "json_query(" ~ column ~ ", '" ~ path ~ "')", fromjson(schema | trim), 0
    ) }}
{%- endmacro %}

{#
  One value of a fo_json_parse schema, as typed BigQuery SQL: a list becomes an array, an
  object a struct with the schema's field names, a leaf a lax_* conversion. `value` is a
  JSON expression; `depth` keeps the element names of nested lists apart.
#}
{% macro bigquery__fo_json_parse_value(value, schema, depth) %}
    {%- if schema is mapping -%}
        struct(
        {%- for field, field_schema in schema.items() %}
            {{ bigquery__fo_json_parse_value(value ~ "['" ~ field ~ "']", field_schema, depth) }} as {{ field }}
            {{- ',' if not loop.last }}
        {%- endfor %}
        )
    {%- elif schema is string -%}
        {%- set leaves = {
            'BIGINT': 'lax_int64', 'VARCHAR': 'lax_string', 'DOUBLE': 'lax_float64',
            'BOOLEAN': 'lax_bool',
        } -%}
        {%- if schema == 'JSON' -%}
            {{ value }}
        {%- elif schema in leaves -%}
            {{ leaves[schema] }}({{ value }})
        {%- else -%}
            {{ exceptions.raise_compiler_error(
                "fo_json_parse on BigQuery has no form for the type " ~ schema
            ) }}
        {%- endif -%}
    {%- elif schema is sequence and schema | length == 1 -%}
        {%- set element = "_e" ~ depth -%}
        array(
            select {{ bigquery__fo_json_parse_value(element, schema[0], depth + 1) }}
            from unnest(json_query_array({{ value }})) as {{ element }} with offset as {{ element }}_at
            order by {{ element }}_at
        )
    {%- else -%}
        {{ exceptions.raise_compiler_error(
            "fo_json_parse on BigQuery cannot read this part of a schema: " ~ schema
        ) }}
    {%- endif -%}
{%- endmacro %}
