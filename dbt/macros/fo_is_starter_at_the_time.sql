{#
  Whether a pitcher was a starter on the day of one of his starts, from what he had done
  before that day: the rule behind the start replacement level (ADR 0029, amended by
  ADR 0031, #92).

  A start counts as a starter's when, on his MLB days of the same season before it, any
  of these holds:
    - he had not pitched yet (a debut: there is nothing to judge him by, and every
      rotation's first turn would otherwise be left out);
    - fo_replacement_group says SP over those days (at least half his games pitched were
      starts), the rule ADR 0029 began with;
    - his two most recent pitching days were both starts (a pitcher who changed role is
      taking his turn in a rotation; one start after relief is as often an opener).
  Nothing from the outing itself is looked at: a start cut short is a bad start, and the
  pool must keep it.

  In 2026 this takes 1,518 free-agent starts by 182 pitchers (14.78 outs a start, ERA
  4.89, WHIP 1.404): the 1,290 the count alone takes, 120 admitted by a first appearance
  and 108 by two starts running. 357 stay out, a reliever's first starts among them: no
  fact known before the game tells those from an opener's. A role carried from a previous
  season would help and needs more than one MLB season landed (#83).

  The arguments are already-computed values for the day, not columns to aggregate:
    earlier_pitching_days     -- how many days he pitched before this one, this season;
    replacement_group_to_date -- fo_replacement_group over his earlier MLB days;
    last_was_start            -- whether his most recent earlier pitching day was a start;
    one_before_was_start      -- whether the one before that was.
  The two flags are null when there is no such day, and null counts as false. They are
  taken over pitching days only: a day on which he only batted is not an appearance.

  Called once, by int_fantasy__replacement_levels. It is a macro so that the rule has one
  home, with its reasons, beside fo_replacement_group, which keeps labelling players
  elsewhere and does not change: the two no longer say the same about a pitcher, by design.
#}

{% macro fo_is_starter_at_the_time(earlier_pitching_days, replacement_group_to_date, last_was_start, one_before_was_start) %}
    (
        {{ earlier_pitching_days }} = 0
        or {{ replacement_group_to_date }} = 'SP'
        or (coalesce({{ last_was_start }}, false) and coalesce({{ one_before_was_start }}, false))
    )
{% endmacro %}
