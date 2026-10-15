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
        {{ bigquery__fo_json_refuse(
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
        {{ bigquery__fo_json_refuse(
            "fo_json_array on BigQuery needs a [*] in its path: " ~ path
        ) }}
    {%- endif -%}
{%- endmacro %}

{#
  Refuse something the BigQuery forms cannot write, when the model that asks for it is
  compiled. Not while the project is parsed: dbt renders every model then, selected or
  not, and a model outside the BigQuery slice (spec 0130) may still ask for what only
  DuckDB has. Raising there would stop the `bq` target from parsing at all.
#}
{% macro bigquery__fo_json_refuse(message) %}
    {%- if execute -%}
        {{ exceptions.raise_compiler_error(message) }}
    {%- endif -%}
{% endmacro %}

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
    {%- if schema is mapping and schema | length == 1 and '__map__' in schema -%}
        {#- A map (duckdb__fo_structure_type): BigQuery has none, so an array of key-value structs. -#}
        {%- set key = "_k" ~ depth -%}
        array(
            select struct(
                {{ key }} as key,
                {{ bigquery__fo_json_parse_value(value ~ "[" ~ key ~ "]", schema['__map__'], depth + 1) }} as value
            )
            from unnest(json_keys({{ value }}, 1)) as {{ key }} with offset as {{ key }}_at
            order by {{ key }}_at
        )
    {%- elif schema is mapping -%}
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
            {{ bigquery__fo_json_refuse(
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
        {{ bigquery__fo_json_refuse(
            "fo_json_parse on BigQuery cannot read this part of a schema: " ~ schema
        ) }}
    {%- endif -%}
{%- endmacro %}


{#
  Captures: the landing zone's committed payloads, read where they lie (spec 0150).

  `raw.captures` is the loader's manifest: one row per committed capture, its key and its
  payload's path relative to the landing root, and no payload (ADR 0066). On DuckDB a
  capture view reads the payload files themselves, with DuckDB's file reader, and keeps
  the files the manifest lists (ADR 0067). Megabyte JSON values never pass through a query
  as values: a heavy endpoint is parsed while it is read, into the fields its models use,
  and the rest of each document is dropped there. That is the whole reason for this
  design: the same parse over a JSON column needed 12 GB for one season of rosters, and
  from the files under 1 GB for eight (spec 0150, C6).

  Only the capture views call fo_captures (ADR 0068), and no model names read_json, the
  manifest or a raw table: ingestion/tests/test_dbt_json_rule.py holds that.
#}

{#
  The landing root, as an absolute path.

  A view stores the text of its SQL, path included, and is read later by processes that
  run anywhere (the gates' scripts, a notebook), so a relative path would point somewhere
  else for each of them. FO_LANDING_ROOT (target dev) and FO_CI_LANDING_ROOT (target ci)
  must be absolute when set; the defaults are the repository's data/raw and
  fixtures/landing, found from the dbt project's own directory.
#}
{% macro fo_landing_root() %}
    {%- set variable = 'FO_CI_LANDING_ROOT' if target.name == 'ci' else 'FO_LANDING_ROOT' -%}
    {%- set default = 'fixtures/landing' if target.name == 'ci' else 'data/raw' -%}
    {%- set given = env_var(variable, '') -%}
    {%- if given -%}
        {%- if not given.startswith('/') -%}
            {{ exceptions.raise_compiler_error(variable ~ " must be an absolute path, not " ~ given) }}
        {%- endif -%}
        {{- return(given.rstrip('/')) -}}
    {%- endif -%}
    {%- set project_dir = invocation_args_dict.get('project_dir') or '.' -%}
    {%- if not project_dir.startswith('/') -%}
        {%- set project_dir = env_var('PWD') ~ '/' ~ project_dir -%}
    {%- endif -%}
    {{- return(project_dir.rstrip('/') ~ '/../' ~ default) -}}
{% endmacro %}

{#
  A structure, in the notation fo_json_parse takes, as a DuckDB type: an object is a
  STRUCT of its fields, a one-element list a list of its element, a leaf its own type
  name, and {"__map__": <value>} a MAP from text to the value (for objects whose keys are
  data: a boxscore's players by "ID669016", a game line's stats by stat id).
#}
{% macro duckdb__fo_structure_type(structure) %}
    {%- if structure is mapping and structure | length == 1 and '__map__' in structure -%}
        MAP(VARCHAR, {{ duckdb__fo_structure_type(structure['__map__']) }})
    {%- elif structure is mapping -%}
        STRUCT(
        {%- for field, inner in structure.items() -%}
            "{{ field }}" {{ duckdb__fo_structure_type(inner) }}{{ ', ' if not loop.last }}
        {%- endfor -%}
        )
    {%- elif structure is string -%}
        {{ structure }}
    {%- elif structure is sequence and structure | length == 1 -%}
        {{ duckdb__fo_structure_type(structure[0]) }}[]
    {%- else -%}
        {{ exceptions.raise_compiler_error("duckdb__fo_structure_type cannot read this part of a structure: " ~ structure) }}
    {%- endif -%}
{% endmacro %}

{#
  One endpoint's captures: one row per committed capture the manifest lists, with the
  manifest's columns, and either

    structure = none   `payload`, the whole document as one JSON value; or
    structure = '{…}'  one column per top-level field of the structure (a JSON object in
                       fo_json_parse's notation), parsed as the file is read.

  `source_name` and `endpoint` name the landing directory <root>/<source>/<endpoint>/.
#}
{% macro fo_captures(source_name, endpoint, structure=none) %}
    {{- return(adapter.dispatch('fo_captures')(source_name, endpoint, structure)) -}}
{% endmacro %}

{#
  DuckDB: the files, joined to the manifest.

  The glob matches published captures only: a capture is written in
  fetched_at=<stamp>.tmp-<pid>/ and published by renaming it to fetched_at=<stamp>/
  (ADR 0014), and a stamp ends in Z (the loader refuses one that does not), so
  `fetched_at=*Z` never matches a capture being written, at any depth (C11). A filter on
  the file name would not do: DuckDB opens the file before filtering it (C12). The join
  then keeps only files the manifest lists, so the manifest stays the authority on what
  was loaded; it decides which rows count, not which files are opened, so a payload that
  does not parse fails the view and names its file either way.

  read_json errors on a glob that matches nothing, and an endpoint can have no captures
  (the CI fixtures have no matchup days), so the glob is counted first, when dbt runs the
  model, and an empty endpoint gives the same columns and no rows. hive_partitioning is
  off: the partition levels differ in depth within one endpoint (espn/transactions).
#}
{% macro duckdb__fo_captures(source_name, endpoint, structure) %}
    {%- set root = fo_landing_root() -%}
    {%- set pattern = root ~ '/' ~ source_name ~ '/' ~ endpoint ~ '/**/fetched_at=*Z/payload.json' -%}
    {%- set fields = fromjson(structure | trim) if structure else none -%}
    {%- set has_files = true -%}
    {%- if execute -%}
        {%- set found = run_query("select count(*) from glob('" ~ pattern ~ "')") -%}
        {%- set has_files = found.columns[0].values()[0] > 0 -%}
    {%- endif %}
    with manifest as (
        select source, endpoint, request_path, request_key, fetched_at, partitions, file_path
        from {{ source('raw', 'captures') }}
        where source = '{{ source_name }}' and endpoint = '{{ endpoint }}'
    ),

    files as (
        {%- if not has_files %}
        select
            cast(null as varchar) as file_path,
            {%- if fields %}
            {%- for field, inner in fields.items() %}
            cast(null as {{ duckdb__fo_structure_type(inner) }}) as "{{ field }}"{{ ',' if not loop.last }}
            {%- endfor %}
            {%- else %}
            cast(null as json) as payload
            {%- endif %}
        where false
        {%- elif fields %}
        select
            substr(filename, {{ root | length + 2 }}) as file_path,
            {%- for field in fields %}
            "{{ field }}"{{ ',' if not loop.last }}
            {%- endfor %}
        from read_json(
            '{{ pattern }}',
            columns = {
            {%- for field, inner in fields.items() %}
                '{{ field }}': '{{ duckdb__fo_structure_type(inner) }}'{{ ',' if not loop.last }}
            {%- endfor %}
            },
            format = 'auto',
            records = true,
            filename = true,
            hive_partitioning = false
        )
        {%- else %}
        select
            substr(filename, {{ root | length + 2 }}) as file_path,
            json as payload
        from read_json_objects(
            '{{ pattern }}',
            format = 'unstructured',
            filename = true,
            hive_partitioning = false
        )
        {%- endif %}
    )

    select
        manifest.source,
        manifest.endpoint,
        manifest.request_path,
        manifest.request_key,
        manifest.fetched_at,
        manifest.partitions,
        manifest.file_path,
        {%- if fields %}
        {%- for field in fields %}
        files."{{ field }}"{{ ',' if not loop.last }}
        {%- endfor %}
        {%- else %}
        files.payload
        {%- endif %}
    from manifest
    inner join files on files.file_path = manifest.file_path
{%- endmacro %}

{#
  BigQuery: the uploaded table, which holds the payloads (ADR 0070). The same columns:
  the structure is parsed from the JSON payload with bigquery__fo_json_parse_value, field
  by field.
#}
{% macro bigquery__fo_captures(source_name, endpoint, structure) %}
    {%- set fields = fromjson(structure | trim) if structure else none %}
    select
        source,
        endpoint,
        request_path,
        request_key,
        fetched_at,
        partitions,
        file_path,
        {%- if fields %}
        {%- for field, inner in fields.items() %}
        {{ bigquery__fo_json_parse_value("json_query(payload, '$." ~ field ~ "')", inner, 0) }} as {{ field }}
            {{- ',' if not loop.last }}
        {%- endfor %}
        {%- else %}
        payload
        {%- endif %}
    from {{ source('raw', 'api_responses') }}
    where source = '{{ source_name }}' and endpoint = '{{ endpoint }}'
{%- endmacro %}

{#
  A map's values, and its entries as structs of `key` and `value`, from a column a
  structure declared as {"__map__": …}. DuckDB has a MAP; on BigQuery the same column is
  an array of key-value structs (bigquery__fo_json_parse_value). No model may depend on
  the order: BigQuery's json_keys sorts keys, DuckDB keeps the document's order.
#}
{% macro fo_map_values(column) %}
    {{- return(adapter.dispatch('fo_map_values')(column)) -}}
{% endmacro %}
{% macro duckdb__fo_map_values(column) %}
    map_values({{ column }})
{%- endmacro %}
{% macro bigquery__fo_map_values(column) %}
    array(select _entry.value from unnest({{ column }}) as _entry with offset as _at order by _at)
{%- endmacro %}

{% macro fo_map_entries(column) %}
    {{- return(adapter.dispatch('fo_map_entries')(column)) -}}
{% endmacro %}
{% macro duckdb__fo_map_entries(column) %}
    map_entries({{ column }})
{%- endmacro %}
{% macro bigquery__fo_map_entries(column) %}
    {{ column }}
{%- endmacro %}

{#
  The manifest's rows, to choose captures on narrow columns (spec 0150, R3.6): raw.captures
  on DuckDB; on BigQuery the uploaded table, whose key columns and file_path are the same
  (ADR 0070). Only the latest-capture macros and the capture views read it.
#}
{% macro fo_capture_keys() %}
    {{- return(adapter.dispatch('fo_capture_keys')()) -}}
{% endmacro %}
{% macro duckdb__fo_capture_keys() %}{{ source('raw', 'captures') }}{% endmacro %}
{% macro bigquery__fo_capture_keys() %}{{ source('raw', 'api_responses') }}{% endmacro %}
