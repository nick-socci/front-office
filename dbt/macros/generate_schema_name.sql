{#
  By default dbt prefixes a custom schema with the target schema, so `+schema: staging`
  would land models in `main_staging`. Overriding this hook -- the standard dbt recipe --
  uses the custom schema verbatim, giving a clean `staging` (and later `marts`) layout.

  On BigQuery only, the variable `fo_schema_suffix` is appended to every schema name
  (dataset, there), so that a second build of the slice can sit beside the first and the
  two be compared (spec 0130, R5.5): --vars '{fo_schema_suffix: _b}' builds into
  staging_b, marts_b and so on. On DuckDB the variable does nothing, whatever it is set to.
#}

{% macro generate_schema_name(custom_schema_name, node) -%}
    {%- set suffix = var('fo_schema_suffix', '') if target.type == 'bigquery' else '' -%}
    {%- if custom_schema_name is none -%}
        {{ target.schema }}{{ suffix }}
    {%- else -%}
        {{ custom_schema_name | trim }}{{ suffix }}
    {%- endif -%}
{%- endmacro %}
