{#
  The two sides of a player's day, as columns of int_mlb__player_game_days.

  One list per slot role: a hitter slot credits only the batting columns and a pitcher
  slot only the pitching ones (#10). Kept here, not in a model, because every layer that
  carries credited production -- started player-days, matchup side totals -- has to
  agree on exactly this set, and a second copy of the list is how they would drift.
#}

{% macro fo_batting_columns() %}
    {{ return([
        'games_batted',
        'plate_appearances',
        'at_bats',
        'hits',
        'doubles',
        'triples',
        'home_runs',
        'runs',
        'runs_batted_in',
        'batter_walks',
        'batter_strikeouts',
        'stolen_bases',
        'caught_stealing',
        'hit_by_pitch',
        'sacrifice_flies',
        'total_bases',
    ]) }}
{% endmacro %}

{% macro fo_pitching_columns() %}
    {{ return([
        'games_pitched',
        'games_started',
        'outs_recorded',
        'batters_faced',
        'hits_allowed',
        'runs_allowed',
        'earned_runs',
        'home_runs_allowed',
        'pitcher_walks',
        'pitcher_strikeouts',
        'hit_batsmen',
        'wins',
        'losses',
        'saves',
        'holds',
        'blown_saves',
    ]) }}
{% endmacro %}
