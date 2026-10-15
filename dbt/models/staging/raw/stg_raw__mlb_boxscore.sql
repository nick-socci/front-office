-- One row per committed boxscore capture (one game) that the loader has listed, parsed as
-- it is read (spec 0150, ADRs 0066 and 0068).
--
-- A boxscore is up to 0.3 MB, and there are 24,385 of them for eight seasons. Each side
-- keeps its team id, its team batting totals (for the test that sums player rows against
-- them) and its players, as a map keyed "ID669016". A player keeps only what the two
-- game-log models read, each part as a small JSON value (person, position, batting order,
-- game status, and the game's batting and pitching lines), so the models read them with
-- fo_json_* exactly as before, from a shorter path. A player's season stats and fielding,
-- most of a boxscore, are dropped while reading: kept as one JSON value per player, the
-- batting model needed 4 GB for eight seasons; this shape reads them under 1 GB (spec 0150,
-- Amendments).

{% set structure %}
{
  "teams": {
    "home": {
      "team": {"id": "BIGINT"},
      "teamStats": {"batting": "JSON"},
      "players": {"__map__": {
        "person": "JSON",
        "position": "JSON",
        "battingOrder": "JSON",
        "gameStatus": "JSON",
        "stats": {"batting": "JSON", "pitching": "JSON"}
      }}
    },
    "away": {
      "team": {"id": "BIGINT"},
      "teamStats": {"batting": "JSON"},
      "players": {"__map__": {
        "person": "JSON",
        "position": "JSON",
        "battingOrder": "JSON",
        "gameStatus": "JSON",
        "stats": {"batting": "JSON", "pitching": "JSON"}
      }}
    }
  }
}
{% endset %}

{{ fo_captures('mlb', 'boxscore', structure) }}
