-- One row per committed roster capture (one scoring period of one league-season) that the
-- loader has listed, parsed as it is read into the fields the roster models use (spec
-- 0150, ADRs 0066 and 0068).
--
-- A roster payload is up to 2.5 MB, nearly all of it every rostered player's season
-- stats. Parsed from the file with this structure, the rest of each document is dropped
-- while reading, and no megabyte value ever passes through a query: eight seasons of
-- game lines read in 3 s and 0.18 GB, where the same parse over a JSON column needed
-- 12 GB for one season (spec 0150, C6 and C19).
--
-- The structure is the union of what its readers take: stg_espn__roster_entries (the
-- entry and the player's name, position and team), stg_espn__roster_entry_slots
-- (eligibleSlots) and stg_espn__player_game_stats (the stat lines, whose `stats` stays
-- JSON: that model reads its keys and values with fo_json_keys / fo_json_values, as it
-- did). `id` is read as text, as the models read the league id. A field a model reads
-- that is not declared here fails that model when it is compiled.

{% set structure %}
{
  "id": "VARCHAR",
  "seasonId": "BIGINT",
  "teams": [{
    "id": "BIGINT",
    "roster": {"entries": [{
      "playerId": "BIGINT",
      "lineupSlotId": "BIGINT",
      "injuryStatus": "VARCHAR",
      "acquisitionType": "VARCHAR",
      "playerPoolEntry": {"player": {
        "fullName": "VARCHAR",
        "defaultPositionId": "BIGINT",
        "proTeamId": "BIGINT",
        "eligibleSlots": ["BIGINT"],
        "stats": [{
          "scoringPeriodId": "BIGINT",
          "statSourceId": "BIGINT",
          "statSplitTypeId": "BIGINT",
          "externalId": "VARCHAR",
          "stats": "JSON"
        }]
      }}
    }]}
  }]
}
{% endset %}

{{ fo_captures('espn', 'roster', structure) }}
