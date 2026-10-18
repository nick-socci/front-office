{#
  The result of one category for one side against its opponent: 'WIN', 'LOSS', 'TIE' or null
  (ADR 0084).

  Every place that decides a category result calls this, so the rule has one copy: the
  matchup fact, the lineup mart's actual and optimal results, and the rescoring check.

  The pitching minimum is applied first (ADR 0083; the null rule comes after it, R2.5). A
  side below the league-season's minimum outs loses every category the minimum binds
  (is_bound), its opponent wins them, and both below is a tie, whatever the values. So a
  side with no outs at all, whose rate is null, loses a bound category rather than getting
  a null. Only then the values decide: a null on either side gives a null result, equal
  values at 9 decimals tie (float noise must not decide a category), and otherwise the
  lower value wins when the category is lower-is-better and the higher wins when not.

  Arguments are SQL expressions, given as strings. team_below and opponent_below must never
  be null: the caller coalesces them to false. Plain SQL both warehouses accept, so it is
  not dispatched.
#}
{% macro fo_category_result(team_value, opponent_value, is_lower_better, is_bound, team_below, opponent_below) %}
case
    when {{ is_bound }} and {{ team_below }} and {{ opponent_below }} then 'TIE'
    when {{ is_bound }} and {{ team_below }} then 'LOSS'
    when {{ is_bound }} and {{ opponent_below }} then 'WIN'
    when {{ team_value }} is null or {{ opponent_value }} is null then null
    when round({{ team_value }}, 9) = round({{ opponent_value }}, 9) then 'TIE'
    when (round({{ team_value }}, 9) < round({{ opponent_value }}, 9)) = {{ is_lower_better }} then 'WIN'
    else 'LOSS'
end
{% endmacro %}
