{#
  fetched_at is stored as the compact string used in landing filenames
  (20260926T142726Z). This turns it into a real timestamp for freshness checks and
  ordering.
#}

{% macro fo_parse_fetched_at(column='fetched_at') %}
    strptime({{ column }}, '%Y%m%dT%H%M%SZ')
{%- endmacro %}
