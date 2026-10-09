{#
  The bridge from a credited component to the platform stat that is exactly it: one row
  per stat whose rule is a single component, as numerator, with weight 1. Hits allowed
  is not ESPN's WHIP, but at-bats is ESPN's AB and outs recorded is ESPN's OUTS.

  It is how a platform's own reported total for a component is found without naming a
  stat id: the reconciliation uses it to rebuild a rate from ESPN's components, and
  int_fantasy__reported_matchup_margins uses it to read a rate's reported denominator.
  One definition, so the two cannot come to mean different things.

  `rules` is a relation or CTE with the columns of int_fantasy__stat_components, already
  restricted to one platform.
#}

{% macro fo_single_component_stats(rules) %}
    select stat_key, max(component) as component
    from {{ rules }}
    group by stat_key
    having count(*) = 1 and max(part) = 'numerator' and max(weight) = 1
{% endmacro %}
