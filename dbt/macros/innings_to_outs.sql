{#
  Baseball writes innings in a notation that is NOT decimal: "6.1" means 6 and 1/3
  innings, "6.2" means 6 and 2/3. Treating it as a number understates work by up to two
  thirds of an inning and silently corrupts every rate stat built on it (ERA, WHIP, K/9).

  Outs are the honest unit, so everything downstream stores outs.

  MLB's boxscore helpfully provides `outs` directly, so this macro is used to CROSS-CHECK
  that field. It becomes load-bearing for ESPN, which reports only the notation.
#}

{% macro fo_innings_to_outs(column) %}
    (
        floor(try_cast({{ column }} as double))::bigint * 3
        + round((try_cast({{ column }} as double) - floor(try_cast({{ column }} as double))) * 10)::bigint
    )
{%- endmacro %}
