-- One row per (league, season, scoring period, team, player): who was rostered, in which
-- lineup slot, on a given day of fantasy scoring.
--
-- Two things about this model are deliberate, and both were learned the hard way when
-- earlier versions exhausted 24 GB of memory:
--
-- 1. The payload is parsed with an explicit schema (from_json with a structure), not
--    with repeated json_extract calls. ESPN embeds every rostered player's full season
--    stats, so each payload is ~2.3 MB; declaring the few fields we want lets DuckDB
--    discard the rest while parsing.
--
-- 2. `payload` is projected away in the `header` CTE, BEFORE any unnest. unnest
--    duplicates every other column in its SELECT once per output row, so extracting
--    league_id alongside unnest(teams) copies a 2.3 MB blob twelve times per period --
--    about 5 GB for one season. Keeping the unnest in a SELECT that no longer mentions
--    payload is the whole difference between 2.8 seconds and running out of memory.
--
-- For the BigQuery migration: from_json with a structure string is DuckDB-specific; the
-- equivalent there is JSON_QUERY_ARRAY plus per-field extraction.

{{ config(materialized='table') }}

{% set roster_schema %}
[{
  "id": "BIGINT",
  "roster": {"entries": [{
    "playerId": "BIGINT",
    "lineupSlotId": "BIGINT",
    "injuryStatus": "VARCHAR",
    "acquisitionType": "VARCHAR",
    "playerPoolEntry": {"player": {
      "fullName": "VARCHAR",
      "defaultPositionId": "BIGINT",
      "proTeamId": "BIGINT"
    }}
  }]}
}]
{% endset %}

with latest as (

    {{ fo_espn_latest('roster', extra_partition='scoringPeriodId') }}

),

header as (

    -- Everything derived from payload is computed here so the payload itself does not
    -- survive into the unnest below.
    select
        {{ fo_json_text('payload', '$.id') }} as league_id,
        {{ fo_json_int('payload', '$.seasonId') }} as season,
        {{ fo_request_param('request_key', 'scoringPeriodId') }} as scoring_period,
        fetched_at,
        from_json(json_extract(payload, '$.teams'), '{{ roster_schema | trim }}') as teams_list
    from latest

),

teams as (

    select
        league_id,
        season,
        scoring_period,
        fetched_at,
        unnest(teams_list) as team
    from header

),

entries as (

    select
        league_id,
        season,
        scoring_period,
        fetched_at,
        team.id as team_id,
        unnest(team.roster.entries) as entry
    from teams

)

select
    league_id,
    season,
    scoring_period,
    team_id,
    entry.playerId as espn_player_id,
    entry.playerPoolEntry.player.fullName as player_name,
    entry.lineupSlotId as lineup_slot_id,
    slots.slot_abbrev as lineup_slot,
    entry.playerPoolEntry.player.defaultPositionId as default_position_id,
    positions.position_abbrev as default_position,
    entry.playerPoolEntry.player.proTeamId as pro_team_id,
    nullif(entry.injuryStatus, '') as injury_status,
    nullif(entry.acquisitionType, '') as acquisition_type,
    {{ fo_parse_fetched_at() }} as fetched_at
from entries
left join {{ ref('espn_lineup_slots') }} as slots
    on slots.lineup_slot_id = entry.lineupSlotId
left join {{ ref('espn_player_positions') }} as positions
    on positions.position_id = entry.playerPoolEntry.player.defaultPositionId
