-- One row per committed boxscore capture (one game) that the loader has listed, parsed as
-- it is read (spec 0150, ADRs 0066 and 0068).
--
-- A boxscore is up to 0.3 MB, and there are 24,385 of them for eight seasons. Each side
-- keeps its team id, its team batting totals (for the test that sums player rows against
-- them) and its players, as a map keyed "ID669016" whose values stay JSON: the two game-log
-- models read a player's fields with fo_json_* as they did, and take the players with
-- fo_map_values where they took fo_json_values of the payload.

{% set structure %}
{
  "teams": {
    "home": {
      "team": {"id": "BIGINT"},
      "teamStats": {"batting": "JSON"},
      "players": {"__map__": "JSON"}
    },
    "away": {
      "team": {"id": "BIGINT"},
      "teamStats": {"batting": "JSON"},
      "players": {"__map__": "JSON"}
    }
  }
}
{% endset %}

{{ fo_captures('mlb', 'boxscore', structure) }}
