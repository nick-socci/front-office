{#
  The kind of a pitcher's day: start or relief, from that day's own appearances.

  A pitcher's day is measured against a replacement day of the same kind (ADR 0008, #52):
  a start against what a free agent produced in a start, a relief appearance against
  what one produced in relief. The kind belongs to the outing, never to the player, so a
  swingman's starts and relief days each meet their own level.

  Shared by int_fantasy__replacement_levels, fct_player_category_value and
  fct_transaction_impact, so the three cannot drift on what counts as a start.

  The arguments are a day's column expressions, not totals:
    start  -- he started a game that date (games_started > 0);
    relief -- otherwise, he pitched (games_pitched > 0);
    null   -- he did not pitch that date.
  A date with both a start and a relief appearance (a doubleheader) is a start; there
  is none in 2026, so only a unit test holds the rule. Null counts as 0.
#}

{% macro fo_pitching_day_kind(games_pitched, games_started) %}
    case
        when coalesce({{ games_started }}, 0) > 0 then 'start'
        when coalesce({{ games_pitched }}, 0) > 0 then 'relief'
    end
{% endmacro %}
