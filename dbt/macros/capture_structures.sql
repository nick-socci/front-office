{#
  The declared structures of the heavy capture views, in one place.

  A heavy endpoint's capture view (stg_raw__espn_roster, stg_raw__espn_matchup_days,
  stg_raw__mlb_boxscore, stg_raw__mlb_schedule) parses its payload files into a declared
  structure as it reads them (fo_captures, spec 0150, ADRs 0066 and 0068). The structure is
  written once, here, and read by two callers: the views, which pass it to fo_captures, and
  the unit-test fixture macro fo_capture_rows (spec 0138, ADR 0111), which builds a mocked
  capture row from the same text. Both read it from here so that the structure a test
  mocks cannot drift from the one the view parses.

  fo_capture_structure(source_name, endpoint) returns the structure text for one of the four
  pairs and raises a compiler error for any other. A field a model reads that is not
  declared in a structure fails that model when it is compiled; to read a new field, add it
  here.
#}

{% macro fo_capture_structure(source_name, endpoint) %}
    {%- if source_name == 'espn' and endpoint == 'roster' -%}
        {#
          The union of what the roster readers take: stg_espn__roster_entries (the entry and
          the player's name, position and team), stg_espn__roster_entry_slots
          (eligibleSlots) and stg_espn__player_game_stats (the stat lines, whose `stats` is a
          map from stat id to its value as JSON: that model unnests its entries with
          fo_map_entries, since unnesting keys beside values as a subquery made DuckDB hold
          every parsed roster, spec 0156). `id` is read as text, as the models read the
          league id.
        #}
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
          "stats": {"__map__": "JSON"}
        }]
      }}
    }]}
  }]
}
{% endset %}
        {{- return(structure) -}}
    {%- elif source_name == 'espn' and endpoint == 'matchup_days' -%}
        {#
          The union of what the matchup-days readers take:
            * `id` (the league, read as text, as the models read the league id), `seasonId`
              and `scoringPeriodId` (the period ESPN says it answered, which
              stg_espn__matchup_days_answer_the_period_asked compares with the one asked for).
            * per matchup: `id` (the matchup's id) and `matchupPeriodId`.
            * per side (`home`, `away`): `teamId`; `rosterForCurrentScoringPeriod`, kept JSON
              because stg_espn__matchup_days reads only whether it is there (ADR 0055: ESPN
              marks the matchups of the period the day belongs to) and the roster inside it
              is never selected; and `rosterForMatchupPeriod.entries[]`, ESPN's own record of
              what each player was credited with in the matchup, which
              stg_espn__matchup_player_lines reads: the entry's `playerId` and its stat
              lines' `statSourceId`, `statSplitTypeId`, `scoringPeriodId` and `stats` (a map
              from stat id to its value as JSON: that model unnests its entries with
              fo_map_entries, since unnesting keys beside values as a subquery made DuckDB
              hold every parsed capture, spec 0156).
          A side with none of these keys (a playoff bye has an empty `away`) is a struct of
          nulls. No name, no `lineupSlotId` (0 on every entry) and nothing of `teams` or
          `settings` is declared (spec 0147, R1.4).
        #}
{% set structure %}
{
  "id": "VARCHAR",
  "seasonId": "BIGINT",
  "scoringPeriodId": "BIGINT",
  "schedule": [{
    "id": "BIGINT",
    "matchupPeriodId": "BIGINT",
    "home": {
      "teamId": "BIGINT",
      "rosterForCurrentScoringPeriod": "JSON",
      "rosterForMatchupPeriod": {"entries": [{
        "playerId": "BIGINT",
        "playerPoolEntry": {"player": {"stats": [{
          "statSourceId": "BIGINT",
          "statSplitTypeId": "BIGINT",
          "scoringPeriodId": "BIGINT",
          "stats": {"__map__": "JSON"}
        }]}}
      }]}
    },
    "away": {
      "teamId": "BIGINT",
      "rosterForCurrentScoringPeriod": "JSON",
      "rosterForMatchupPeriod": {"entries": [{
        "playerId": "BIGINT",
        "playerPoolEntry": {"player": {"stats": [{
          "statSourceId": "BIGINT",
          "statSplitTypeId": "BIGINT",
          "scoringPeriodId": "BIGINT",
          "stats": {"__map__": "JSON"}
        }]}}
      }]}
    }
  }]
}
{% endset %}
        {{- return(structure) -}}
    {%- elif source_name == 'mlb' and endpoint == 'boxscore' -%}
        {#
          Each side keeps its team id, its team batting totals (for the test that sums player
          rows against them) and its players, as a map keyed "ID669016". A player keeps only
          what the two game-log models read, each part as a small JSON value (person,
          position, batting order, game status, and the game's batting and pitching lines),
          so the models read them with fo_json_* exactly as before, from a shorter path. A
          player's season stats and fielding, most of a boxscore, are dropped while reading:
          kept as one JSON value per player, the batting model needed 4 GB for eight
          seasons; this shape reads them under 1 GB (spec 0150, Amendments).
        #}
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
        {{- return(structure) -}}
    {%- elif source_name == 'mlb' and endpoint == 'schedule' -%}
        {#
          Only the days and their games are kept. Each game stays one JSON value, because its
          readers read it with fo_json_*, from the same paths as before.
        #}
{% set structure %}
{"dates": [{"games": ["JSON"]}]}
{% endset %}
        {{- return(structure) -}}
    {%- else -%}
        {{- exceptions.raise_compiler_error(
            "fo_capture_structure: no declared structure for (" ~ source_name ~ ", " ~ endpoint
            ~ "); the heavy captures are espn/roster, espn/matchup_days, mlb/boxscore and"
            ~ " mlb/schedule"
        ) -}}
    {%- endif -%}
{% endmacro %}
