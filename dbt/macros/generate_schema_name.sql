{#
  By default dbt prefixes a custom schema with the target schema, so `+schema: staging`
  would land models in `main_staging`. Overriding this hook -- the standard dbt recipe --
  uses the custom schema verbatim, giving a clean `staging` (and later `marts`) layout.
#}

{% macro generate_schema_name(custom_schema_name, node) -%}
    {%- if custom_schema_name is none -%}
        {{ target.schema }}
    {%- else -%}
        {{ custom_schema_name | trim }}
    {%- endif -%}
{%- endmacro %}
