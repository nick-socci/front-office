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

{#
  A structure part as the JSON that DuckDB's from_json reads as a type: the same part, with
  each {"__map__": X} replaced by the type string "MAP(VARCHAR, <X's type>)" (a MAP is the
  one part from_json cannot be given as JSON; the string is the type duckdb__fo_structure_type
  writes for the view). tojson escapes the quotes inside that type string.
#}
{% macro duckdb__fo_structure_as_json(structure) %}
    {%- if structure is mapping and structure | length == 1 and '__map__' in structure -%}
        {{ duckdb__fo_structure_type(structure) | trim | tojson }}
    {%- elif structure is mapping -%}
        { {%- for field, inner in structure.items() -%}
            {{ field | tojson }}: {{ duckdb__fo_structure_as_json(inner) }}{{ ', ' if not loop.last }}
        {%- endfor -%} }
    {%- elif structure is string -%}
        {{ structure | tojson }}
    {%- else -%}
        [{{ duckdb__fo_structure_as_json(structure[0]) }}]
    {%- endif -%}
{% endmacro %}

{# JSON text as a JSON value: json() on DuckDB, parse_json() on BigQuery. #}
{% macro fo_capture_json(text) %}
    {{- return(adapter.dispatch('fo_capture_json')(text)) -}}
{% endmacro %}
{% macro duckdb__fo_capture_json(text) -%}
    json({{ fo_sql_string(text) }})
{%- endmacro %}
{% macro bigquery__fo_capture_json(text) -%}
    parse_json({{ fo_sql_string(text) }})
{%- endmacro %}

{#
  One top-level field of a payload, parsed with its part of the structure, as the capture
  view parses it. `payload_sql` is a SQL expression holding the payload as a JSON value.
  DuckDB uses from_json, not a cast: from_json ignores a key the structure does not name,
  as the view's read_json does, and a cast refuses it (spec 0138, C12). BigQuery uses the
  view's own expression, bigquery__fo_json_parse_value.
#}
{% macro fo_capture_field(payload_sql, field, structure) %}
    {{- return(adapter.dispatch('fo_capture_field')(payload_sql, field, structure)) -}}
{% endmacro %}
{% macro duckdb__fo_capture_field(payload_sql, field, structure) -%}
    from_json(json_extract({{ payload_sql }}, '$."{{ field }}"'), {{ fo_sql_string(duckdb__fo_structure_as_json(structure) | trim) }}) as "{{ field }}"
{%- endmacro %}
{% macro bigquery__fo_capture_field(payload_sql, field, structure) -%}
    {{ bigquery__fo_json_parse_value("json_query(" ~ payload_sql ~ ", '$." ~ field ~ "')", structure, 0) }} as {{ field }}
{%- endmacro %}

{#
  Mocked capture rows for a unit test of a capture view that declares a structure (spec
  0138, ADR 0111): the rows fo_captures gives for those captures, built from the payload
  text a fixture holds, with the view's own structure (fo_capture_structure), so the
  columns and types are the view's on each warehouse.

  captures is a list of mappings; request_key, fetched_at and file_path (text),
  partitions and payload (JSON text) are required, request_path defaults to '/fixture'.
  The columns are fo_captures' in its order: the manifest's, then each top-level field of
  the structure. An empty list gives the same columns and no rows, by a select over the
  payload '{}' with `limit 0`: BigQuery refuses a WHERE with no FROM.

  A field the payload lacks is read as the view reads it (null; on BigQuery an empty list
  or a struct of nulls, spec 0138 C20), and a key the structure does not declare is dropped
  (ingestion/tests/test_capture_glob.py holds both against the view itself).
#}
{% macro fo_capture_rows(source_name, endpoint, captures) %}
    {%- set fields = fromjson(fo_capture_structure(source_name, endpoint) | trim) -%}
    {%- for c in captures -%}
        {%- set number = loop.index -%}
        {%- for key in ['request_key', 'fetched_at', 'file_path', 'partitions', 'payload'] -%}
            {%- if key not in c -%}
                {{- exceptions.raise_compiler_error("fo_capture_rows: capture " ~ number ~ " lacks '" ~ key ~ "'") -}}
            {%- endif -%}
        {%- endfor -%}
    {%- endfor -%}
    {%- set empty = captures | length == 0 -%}
    {%- set rows = [{'request_key': 'none', 'fetched_at': 'none', 'file_path': 'none', 'partitions': '{}', 'payload': '{}'}] if empty else captures -%}
    {%- for c in rows %}
    select
        {{ fo_sql_string(source_name) }} as source,
        {{ fo_sql_string(endpoint) }} as endpoint,
        {{ fo_sql_string(c.get('request_path', '/fixture')) }} as request_path,
        {{ fo_sql_string(c.request_key) }} as request_key,
        {{ fo_sql_string(c.fetched_at) }} as fetched_at,
        {{ fo_capture_json(c.partitions) }} as partitions,
        {{ fo_sql_string(c.file_path) }} as file_path,
        {%- for field, inner in fields.items() %}
        {{ fo_capture_field(fo_capture_json(c.payload), field, inner) }}{{ ',' if not loop.last }}
        {%- endfor %}
    {{ 'union all' if not loop.last }}
    {%- endfor %}
    {{ 'limit 0' if empty }}
{% endmacro %}
