{#
  SQL that DuckDB and BigQuery spell differently, in one place (ADR 0051).

  A model is written once. Where both warehouses accept a spelling it is plain SQL in the
  model: cast(x as integer), count(case when c then 1 end). Everything else is a macro
  here, or a JSON accessor in json.sql. Each has a form per warehouse and dbt picks one by
  the target: adapter.dispatch('fo_x') calls duckdb__fo_x or bigquery__fo_x. There is no
  default__ form, so an unknown warehouse fails when the project is compiled instead of
  being handed DuckDB's SQL.

  The DuckDB form of each emits the SQL the models had before the macro existed, so the
  DuckDB warehouse does not move. ingestion/tests/test_dbt_portable_sql_rule.py fails when
  a ported model, or a macro it reaches, holds one of these constructs outside a duckdb__
  form.
#}


{# The 64-bit floating-point type. Not dbt.type_float(): that is `float`, 32-bit on DuckDB. #}
{% macro fo_type_float() %}{{ return(adapter.dispatch('fo_type_float')()) }}{% endmacro %}
{% macro duckdb__fo_type_float() %}double{% endmacro %}
{% macro bigquery__fo_type_float() %}float64{% endmacro %}


{# The text type. #}
{% macro fo_type_text() %}{{ return(adapter.dispatch('fo_type_text')()) }}{% endmacro %}
{% macro duckdb__fo_type_text() %}varchar{% endmacro %}
{% macro bigquery__fo_type_text() %}string{% endmacro %}


{#
  A cast that gives null where the value cannot be read as the type. `type` is a type name
  both warehouses accept (bigint, integer, date, boolean) or one of the fo_type_* macros.
#}
{% macro fo_safe_cast(expression, type) %}
    {{- return(adapter.dispatch('fo_safe_cast')(expression, type)) -}}
{% endmacro %}
{% macro duckdb__fo_safe_cast(expression, type) -%}
    try_cast({{ expression }} as {{ type }})
{%- endmacro %}
{% macro bigquery__fo_safe_cast(expression, type) -%}
    safe_cast({{ expression }} as {{ type }})
{%- endmacro %}


{#
  One row per element of a list, written in the FROM clause after the relation that holds
  the list:

      select header.league_id, team from header {{ fo_unnest('header.teams_list', 'team') }}

  A null or empty list gives no rows, on both. BigQuery has no unnest in a SELECT list, so
  this is the only way a model unnests.

  Give it a column of a relation that holds nothing large, not an expression over a
  payload (AGENTS.md rule 1). DuckDB unnests a column in place. An expression in the FROM
  clause it plans as a join that carries what the expression reads: unnesting
  json_extract(responses.payload, ...) straight from the raw responses held each 3.5 MB
  schedule once per game and ran the real build out of memory (spec 0130, task 6). Compute
  the list in one CTE and unnest it in the next. A small expression, such as
  fo_int_series or the keys of one matchup, is fine.
#}
{% macro fo_unnest(list, alias) %}
    {{- return(adapter.dispatch('fo_unnest')(list, alias)) -}}
{% endmacro %}
{% macro duckdb__fo_unnest(list, alias) -%}
    cross join unnest({{ list }}) as _u_{{ alias }}({{ alias }})
{%- endmacro %}
{% macro bigquery__fo_unnest(list, alias) -%}
    cross join unnest({{ list }}) as {{ alias }}
{%- endmacro %}


{#
  Two lists of the same length unnested side by side, element i of one beside element i of
  the other: the keys of a JSON object beside its values (fo_json_keys, fo_json_values).
#}
{% macro fo_unnest_pair(first_list, first_alias, second_list, second_alias) %}
    {{- return(adapter.dispatch('fo_unnest_pair')(
        first_list, first_alias, second_list, second_alias
    )) -}}
{% endmacro %}
{% macro duckdb__fo_unnest_pair(first_list, first_alias, second_list, second_alias) -%}
    cross join (
        select
            unnest({{ first_list }}) as {{ first_alias }},
            unnest({{ second_list }}) as {{ second_alias }}
    ) as _u_{{ first_alias }}
{%- endmacro %}
{% macro bigquery__fo_unnest_pair(first_list, first_alias, second_list, second_alias) -%}
    cross join unnest({{ first_list }}) as {{ first_alias }} with offset as _o_{{ first_alias }}
    inner join unnest({{ second_list }}) as {{ second_alias }} with offset as _o_{{ second_alias }}
        on _o_{{ first_alias }} = _o_{{ second_alias }}
{%- endmacro %}


{#
  The elements of a list for which `condition` holds, as a list, in their order. `element`
  names one element inside `condition`, which may also read the columns of the row:

      {{ fo_list_filter('entry.lines', 'line', 'line.statSourceId = 0') }} as lines

  Filter a list of parsed captures this way, before fo_unnest, rather than with a WHERE
  over the unnested rows: DuckDB plans a WHERE comparing an unnested element's fields as a
  delim join, which holds every parsed capture before it emits a row (spec 0156, C9). The
  same holds for fo_unnest_pair, a subquery DuckDB also plans that way: over parsed
  captures, declare the object as a map and unnest fo_map_entries instead.
#}
{% macro fo_list_filter(list, element, condition) %}
    {{- return(adapter.dispatch('fo_list_filter')(list, element, condition)) -}}
{% endmacro %}
{% macro duckdb__fo_list_filter(list, element, condition) -%}
    list_filter({{ list }}, lambda {{ element }}: {{ condition }})
{%- endmacro %}
{% macro bigquery__fo_list_filter(list, element, condition) -%}
    array(
        select {{ element }}
        from unnest({{ list }}) as {{ element }} with offset as _at_{{ element }}
        where {{ condition }}
        order by _at_{{ element }}
    )
{%- endmacro %}


{# The whole numbers from `first` to `last`, both included, as a list: unnest it with fo_unnest. #}
{% macro fo_int_series(first, last) %}
    {{- return(adapter.dispatch('fo_int_series')(first, last)) -}}
{% endmacro %}
{% macro duckdb__fo_int_series(first, last) -%}
    generate_series({{ first }}, {{ last }})
{%- endmacro %}
{% macro bigquery__fo_int_series(first, last) -%}
    generate_array({{ first }}, {{ last }})
{%- endmacro %}


{#
  A floating-point sum or mean, in a stated order (ADR 0046). The last digit of a float
  aggregate depends on the order of its rows, so DuckDB is given the order and two DuckDB
  builds agree exactly. BigQuery has no way to state it, and its form leaves it out: a
  BigQuery build is held to a tolerance on float columns, not to equality (ADR 0053).
  `order_by` is what follows `order by`, on the grain's key.
#}
{% macro fo_sum_in_order(expression, order_by) %}
    {{- return(adapter.dispatch('fo_sum_in_order')(expression, order_by)) -}}
{% endmacro %}
{% macro duckdb__fo_sum_in_order(expression, order_by) -%}
    sum({{ expression }} order by {{ order_by }})
{%- endmacro %}
{% macro bigquery__fo_sum_in_order(expression, order_by) -%}
    sum({{ expression }})
{%- endmacro %}

{% macro fo_avg_in_order(expression, order_by) %}
    {{- return(adapter.dispatch('fo_avg_in_order')(expression, order_by)) -}}
{% endmacro %}
{% macro duckdb__fo_avg_in_order(expression, order_by) -%}
    avg({{ expression }} order by {{ order_by }})
{%- endmacro %}
{% macro bigquery__fo_avg_in_order(expression, order_by) -%}
    avg({{ expression }})
{%- endmacro %}


{# True if the condition is true for any row; null over no non-null input, on both. #}
{% macro fo_any_true(condition) %}
    {{- return(adapter.dispatch('fo_any_true')(condition)) -}}
{% endmacro %}
{% macro duckdb__fo_any_true(condition) -%}
    bool_or({{ condition }})
{%- endmacro %}
{% macro bigquery__fo_any_true(condition) -%}
    logical_or({{ condition }})
{%- endmacro %}


{#
  A correlation, with the order its float sum is taken in (ADR 0046) stated in DuckDB.
  BigQuery's corr takes no order, so its form leaves it out, and a BigQuery build is held to
  the float tolerance on the column, as for fo_sum_in_order. `order_by` is what follows
  `order by`, on the grain's key.
#}
{% macro fo_corr_in_order(y, x, order_by) %}
    {{- return(adapter.dispatch('fo_corr_in_order')(y, x, order_by)) -}}
{% endmacro %}
{% macro duckdb__fo_corr_in_order(y, x, order_by) -%}
    corr({{ y }}, {{ x }} order by {{ order_by }})
{%- endmacro %}
{% macro bigquery__fo_corr_in_order(y, x, order_by) -%}
    corr({{ y }}, {{ x }})
{%- endmacro %}


{#
  True if a number is neither NaN nor infinite; null for a null input, on both. DuckDB's
  isfinite and BigQuery's is_nan and is_inf are the same test. Neither accepts a string.
#}
{% macro fo_is_finite(expression) %}
    {{- return(adapter.dispatch('fo_is_finite')(expression)) -}}
{% endmacro %}
{% macro duckdb__fo_is_finite(expression) -%}
    isfinite({{ expression }})
{%- endmacro %}
{% macro bigquery__fo_is_finite(expression) -%}
    (not is_nan({{ expression }}) and not is_inf({{ expression }}))
{%- endmacro %}


{# The MD5 of text, as 32 characters of lower-case hex. BigQuery's md5 returns BYTES. #}
{% macro fo_md5_hex(text) %}
    {{- return(adapter.dispatch('fo_md5_hex')(text)) -}}
{% endmacro %}
{% macro duckdb__fo_md5_hex(text) -%}
    md5({{ text }})
{%- endmacro %}
{% macro bigquery__fo_md5_hex(text) -%}
    to_hex(md5({{ text }}))
{%- endmacro %}


{#
  The instant a count of milliseconds since 1970-01-01 UTC names, as DuckDB's timestamp with
  time zone. fo_timestamp_from_millis below is the same instant as a plain TIMESTAMP, for a
  value that is only read as a date or a time; this one keeps the type of a column that
  already holds `to_timestamp(ms / 1000)`.
#}
{% macro fo_instant_from_millis(ms) %}
    {{- return(adapter.dispatch('fo_instant_from_millis')(ms)) -}}
{% endmacro %}
{% macro duckdb__fo_instant_from_millis(ms) -%}
    to_timestamp({{ ms }} / 1000)
{%- endmacro %}
{% macro bigquery__fo_instant_from_millis(ms) -%}
    timestamp_millis({{ ms }})
{%- endmacro %}


{# The instant a count of milliseconds since 1970-01-01 UTC names. #}
{% macro fo_timestamp_from_millis(milliseconds) %}
    {{- return(adapter.dispatch('fo_timestamp_from_millis')(milliseconds)) -}}
{% endmacro %}
{% macro duckdb__fo_timestamp_from_millis(milliseconds) -%}
    epoch_ms({{ milliseconds }})
{%- endmacro %}
{% macro bigquery__fo_timestamp_from_millis(milliseconds) -%}
    timestamp_millis({{ milliseconds }})
{%- endmacro %}


{#
  Text with its accents removed, for matching one source's spelling of a name with
  another's ("Jose" for "José"). BigQuery has no function for it: the text is decomposed
  (NFD), which splits each accented letter into the letter and its marks, and the marks
  are removed. Whether the two agree on every name the season holds is checked by
  comparing the builds (spec 0130, R5.2), not assumed.
#}
{% macro fo_strip_accents(expression) %}
    {{- return(adapter.dispatch('fo_strip_accents')(expression)) -}}
{% endmacro %}
{% macro duckdb__fo_strip_accents(expression) -%}
    strip_accents({{ expression }})
{%- endmacro %}
{% macro bigquery__fo_strip_accents(expression) -%}
    regexp_replace(normalize({{ expression }}, NFD), r'\pM', '')
{%- endmacro %}


{#
  Whole days from one date to a later one. DuckDB subtracts dates to an integer; BigQuery
  gives an INTERVAL for the same spelling, which cannot be added to a number (found by the
  empty build, spec 0130 task 12).
#}
{% macro fo_days_between(earlier, later) %}
    {{- return(adapter.dispatch('fo_days_between')(earlier, later)) -}}
{% endmacro %}
{% macro duckdb__fo_days_between(earlier, later) -%}
    ({{ later }} - {{ earlier }})
{%- endmacro %}
{% macro bigquery__fo_days_between(earlier, later) -%}
    date_diff({{ later }}, {{ earlier }}, day)
{%- endmacro %}


{# The first of January of a year, as a date. `year` is an integer expression. #}
{% macro fo_year_start(year) %}{{ return(adapter.dispatch('fo_year_start')(year)) }}{% endmacro %}
{% macro duckdb__fo_year_start(year) %}make_date({{ year }}, 1, 1){% endmacro %}
{% macro bigquery__fo_year_start(year) %}date({{ year }}, 1, 1){% endmacro %}


{#
  A struct value from `fields`, a list of (expression, name) pairs:

      {{ fo_struct([('t.day', 'scoring_date'), ('t.id', 'player_id')]) }}

  DuckDB names the fields in struct_pack(name := expression), BigQuery in
  struct(expression as name). Fields are in the order given, which is the order the lineup
  solver function's signature declares them in (spec 0137).
#}
{% macro fo_struct(fields) %}
    {{- return(adapter.dispatch('fo_struct')(fields)) -}}
{% endmacro %}
{% macro duckdb__fo_struct(fields) -%}
    struct_pack(
        {%- for expression, name in fields %}{{ name }} := {{ expression }}{{ ', ' if not loop.last }}{% endfor -%}
    )
{%- endmacro %}
{% macro bigquery__fo_struct(fields) -%}
    struct(
        {%- for expression, name in fields %}{{ expression }} as {{ name }}{{ ', ' if not loop.last }}{% endfor -%}
    )
{%- endmacro %}


{#
  What to call the lineup solver by (spec 0137, ADR 0103). On DuckDB it is the function the
  fo_duckdb_functions plugin registers on dbt's connections, so the bare name. On BigQuery it
  is the dbt function resource dbt/functions/_functions.yml declares, which function() names
  in full and which makes the calling model depend on it on that warehouse only. Only
  int_fantasy__optimal_lineups calls it (a test holds that): the DuckDB function exists on
  dbt's connections alone, so a view calling it would fail anywhere else.
#}
{% macro fo_solve_lineup_period() %}
    {{- return(adapter.dispatch('fo_solve_lineup_period')()) -}}
{% endmacro %}
{% macro duckdb__fo_solve_lineup_period() -%}
    solve_lineup_period
{%- endmacro %}
{% macro bigquery__fo_solve_lineup_period() -%}
    {{ function('solve_lineup_period') }}
{%- endmacro %}


{#
  A text as a SQL string literal, quotes included (spec 0138, ADR 0111). For the unit-test
  fixtures that put text into SQL (fo_capture_rows, bigquery__safe_cast).

  DuckDB's string literals have no backslash escapes: only the quote is doubled. BigQuery
  unescapes backslashes inside a string literal, so JSON holding \" would reach parse_json
  as a bare quote and fail (spec 0138, C11 and C19): every backslash is doubled first, then
  every quote is written \'. A BigQuery literal in single quotes cannot hold a line break
  either, so newlines and carriage returns are written \n and \r.
#}
{% macro fo_sql_string(text) %}
    {{- return(adapter.dispatch('fo_sql_string')(text)) -}}
{% endmacro %}
{% macro duckdb__fo_sql_string(text) -%}
    '{{ text | replace("'", "''") }}'
{%- endmacro %}
{% macro bigquery__fo_sql_string(text) -%}
    '{{ text | replace("\\", "\\\\") | replace("'", "\\'") | replace("\n", "\\n") | replace("\r", "\\r") }}'
{%- endmacro %}
