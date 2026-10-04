{#
  The replacement group of an MLB player, from his appearances: hitter, SP or RP.

  Shared by int_fantasy__replacement_levels (over a player's free-agent days) and
  dim_players (over his whole season, for a player with no default position), because
  the two must agree on what makes someone a starter and a second copy of the rule is
  how they would drift.

  The arguments are already-summed totals, not columns of a day:
    hitter -- he recorded no outs, or had more plate appearances than batters faced
              (a position player who pitched a mop-up inning, or a pitcher who bats a
              lot, is judged by the side he mostly did);
    SP     -- otherwise, at least half his games pitched were starts;
    RP     -- otherwise.
  Null totals count as 0. A player with no appearances at all has no outs, so he is a
  hitter; callers that care must not ask about players they hold no rows for.
#}

{% macro fo_replacement_group(plate_appearances, batters_faced, outs_recorded, games_pitched, games_started) %}
    case
        when coalesce({{ outs_recorded }}, 0) = 0
            or coalesce({{ plate_appearances }}, 0) > coalesce({{ batters_faced }}, 0)
            then 'hitter'
        when coalesce({{ games_started }}, 0) * 2 >= coalesce({{ games_pitched }}, 0) then 'SP'
        else 'RP'
    end
{% endmacro %}
