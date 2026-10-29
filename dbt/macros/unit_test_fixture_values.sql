{#
  How dbt's unit-test fixtures write a JSON value on BigQuery (spec 0138, R4).

  A unit test's fixture rows are turned into SQL by dbt, and for a column of type JSON it
  calls safe_cast(<value>, 'json'). dbt-bigquery answers with cast(<value> as JSON), which
  BigQuery refuses for a string ("Invalid cast from STRING to JSON"); a mapping it would
  take, but fixtures here keep JSON as text (ADR 0113). So this overrides dbt-bigquery's
  safe_cast, which dbt dispatches in its own `dbt` namespace: the root project's
  bigquery__safe_cast wins over the adapter's.

  A JSON string reaches here already quoted by dbt-bigquery as '''...''' with every ' inside
  written \'. The override takes the original text back (strip the triple quotes, turn \'
  into ', which is unambiguous because \' is not valid inside JSON) and writes it again with
  fo_sql_string, because BigQuery unescapes backslashes in a string literal: a \" or \\ in
  the JSON would otherwise lose its escape (claim C11) and the text would no longer parse
  to the same value.

  A string for any other type has the same flaw when its text holds a backslash: an expected
  name with one in it fails as "Illegal escape sequence" (spec 0138, Amendments). Such a
  value is written again the same way and cast to its type as the adapter would. Taking
  the text back is exact for any text, since dbt only puts a backslash before each '.

  Every other call (no backslash, null, a mapping, a value not quoted that way) goes to the
  adapter's own form, reached as dbt.bigquery__safe_cast: `dbt_bigquery.` is undefined.

  Only dbt's fixture SQL calls safe_cast in this project (C17), so nothing else changes.
  DuckDB needs no override: its default cast takes JSON text, so there is no duckdb__ form.
#}

{% macro bigquery__safe_cast(field, type) %}
    {%- if type | lower == 'json' and field is string and field.startswith("'''") and field.endswith("'''") and field | length >= 6 -%}
        {%- set text = field[3:-3] | replace("\\'", "'") -%}
        parse_json({{ fo_sql_string(text) }})
    {%- elif field is string and field.startswith("'''") and field.endswith("'''") and field | length >= 6 and "\\" in field[3:-3] | replace("\\'", "'") -%}
        safe_cast({{ fo_sql_string(field[3:-3] | replace("\\'", "'")) }} as {{ type }})
    {%- else -%}
        {{ dbt.bigquery__safe_cast(field, type) }}
    {%- endif -%}
{% endmacro %}
