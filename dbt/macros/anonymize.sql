{#
  Replace identifying text with a stable alias when var('anonymize') is true.

  Fantasy team names and the league name are chosen by real people who never agreed to
  appear in a public repository, so CI and any published build run with this on. Local
  development keeps the real names, because a dashboard listing "Team 07" is useless.
#}

{% macro fo_anonymize(expression, alias_expression) %}
    {%- if var('anonymize', false) -%}
    {{ alias_expression }}
    {%- else -%}
    {{ expression }}
    {%- endif -%}
{%- endmacro %}
