{#
  The per-category arithmetic of player value (#11), as SQL expressions.

  Shared by fct_player_category_value and (later) fct_transaction_impact, because the two
  must put a player's season and a transaction's window on one scale, and a second copy of
  these formulas is how the two facts would drift. Each macro takes COLUMN EXPRESSIONS,
  not table names, so it works on any relation with the same column meanings:

    numerator, denominator  weighted sums of the category's numerator / denominator
                            components over the days being valued. The denominator is
                            NULL for a count (HR) and a number for a rate (ERA).
    played_days             days on the side the category belongs to (batting or pitching)
    replacement_numerator,
    replacement_denominator the same weighted sums of the replacement level, per played
                            day, for the group being compared against (NULL for a count's
                            denominator; NULL throughout for an empty pool)
    is_lower_better         true for ERA, WHIP, batter strikeouts and the like

  (A dbt macro is a Jinja function that returns text, here a SQL expression; it is pasted
  into the query where it is called.)

  value over replacement, ADR 0002:
    count  N - rN * played_days            hits above what a replacement gets in as many
                                           played days
    rate   N - (rN / rD) * D               earned runs saved over the same outs: the
                                           replacement's rate applied to the player's own
                                           denominator, never a difference of two rates
  times -1 when lower is better, so positive is always better.
    played_days = 0   -> 0: he neither helped nor hurt this category, even if the pool is
                         empty, so a pair is never nulled by a level it is not charged
    level is NULL     -> NULL: an empty pool means "unknown", not "replacement is zero"
                         (R3.4)
    a rate with D = 0 -> N (he allowed runs and recorded no outs: all of it is a cost)

  scaled value, ADR 0010: value over replacement in matchup margins, the usual gap between
  two teams in the category (int_fantasy__category_scales.margin_scale).
    count  value / margin_scale
    rate   value / side_denominator / margin_scale
                          a rate's value is in numerator units over the player's own
                          denominator; dividing by the typical side's denominator turns it
                          into the change he makes to a typical side's rate, the unit the
                          margin is in
    played_days = 0       -> 0
    value is NULL         -> NULL, not 0: an unknown level stays unknown
    margin_scale NULL or 0 -> 0: no measurable margin, no information
    a rate whose side_denominator is NULL or 0 -> 0, for the same reason
  Arguments are column expressions, as above; is_rate is true for a category with a
  denominator part.
#}

{% macro fo_contribution(numerator, denominator) %}
    case
        when {{ denominator }} is null then {{ numerator }}
        else {{ numerator }} / nullif({{ denominator }}, 0)
    end
{% endmacro %}

{% macro fo_value_over_replacement(
    numerator, denominator, played_days, replacement_numerator, replacement_denominator, is_lower_better
) %}
    case
        when {{ played_days }} = 0 then 0
        else
            case
                when {{ denominator }} is null
                    then {{ numerator }} - {{ replacement_numerator }} * {{ played_days }}
                else
                    {{ numerator }}
                    - ({{ replacement_numerator }} / nullif({{ replacement_denominator }}, 0)) * {{ denominator }}
            end
            * case when {{ is_lower_better }} then -1 else 1 end
    end
{% endmacro %}

{% macro fo_scaled_value(value_over_replacement, played_days, margin_scale, side_denominator, is_rate) %}
    case
        when {{ played_days }} = 0 then 0
        when {{ value_over_replacement }} is null then null
        when coalesce({{ margin_scale }}, 0) = 0 then 0
        when {{ is_rate }} and coalesce({{ side_denominator }}, 0) = 0 then 0
        when {{ is_rate }} then {{ value_over_replacement }} / {{ side_denominator }} / {{ margin_scale }}
        else {{ value_over_replacement }} / {{ margin_scale }}
    end
{% endmacro %}
