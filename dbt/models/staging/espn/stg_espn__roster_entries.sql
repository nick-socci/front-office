-- One row per (league, season, scoring period, team, player): who was rostered, in which
-- lineup slot, on a given day of fantasy scoring.
--
-- Two things about this model are deliberate, and both were learned the hard way when
-- earlier versions exhausted 24 GB of memory:
--
-- 1. The payload is parsed with an explicit schema (fo_json_parse, which is DuckDB's
--    from_json with a structure), not with repeated per-field extraction. ESPN embeds every
--    rostered player's full season stats, so each payload is ~2.3 MB; declaring the few
--    fields we want lets DuckDB discard the rest while parsing.
--
-- 2. `payload` is projected away in the `header` CTE, BEFORE any unnest. unnest
--    duplicates every other column in its SELECT once per output row, so extracting
--    league_id alongside unnest(teams) copies a 2.3 MB blob twelve times per period --
--    about 5 GB for one season. Keeping the unnest in a SELECT that no longer mentions
--    payload is the whole difference between 2.8 seconds and running out of memory.
--
-- For the BigQuery migration: the structure string is DuckDB-specific. It is passed to
-- fo_json_parse, which is where the DuckDB form (from_json) lives; its BigQuery variant
-- will be JSON_QUERY_ARRAY plus per-field extraction.
--
-- 3. Built a season at a time. DuckDB holds every parsed payload of a run at once, and two
--    seasons took the build to its memory limit, so dbt runs this model once per calendar
--    year (microbatch), reading one season's captures through stg_raw__season_responses.
--    Every build redoes every season. On BigQuery it is a plain table (spec 0143, ADRs
--    0058 to 0060). season_start, the column dbt batches on, is small and is carried
--    beside the other header columns; the payload is still dropped in `header`.

{{ config(
    materialized=('incremental' if target.type == 'duckdb' else 'table'),
    incremental_strategy=('microbatch' if target.type == 'duckdb' else none),
    event_time='season_start',
    batch_size='year',
    begin=var('first_season_start'),
    lookback=fo_batches_back_to_first_season(),
    concurrent_batches=false,
    on_schema_change='fail'
) }}

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

    {{ fo_espn_latest(
        'roster',
        extra_partition='scoringPeriodId',
        relation=ref('stg_raw__season_responses')
    ) }}

),

header as (

    -- Everything derived from payload is computed here so the payload itself does not
    -- survive into the unnest below.
    select
        {{ fo_json_text('payload', '$.id') }} as league_id,
        {{ fo_json_int('payload', '$.seasonId') }} as season,
        {{ fo_request_param('request_key', 'scoringPeriodId') }} as scoring_period,
        fetched_at,
        season_start,
        {{ fo_json_parse('payload', '$.teams', roster_schema) }} as teams_list
    from latest

),

teams as (

    -- A team's entries are taken out as a column of their own here: fo_unnest is given a
    -- column, never an expression. DuckDB unnests a column in place; an expression in the
    -- FROM clause it plans as a join, and this model took two and a half times as long.
    select
        league_id,
        season,
        scoring_period,
        fetched_at,
        season_start,
        team.id as team_id,
        team.roster.entries as roster_entries
    from header
    {{ fo_unnest('header.teams_list', 'team') }}

),

entries as (

    select
        league_id,
        season,
        scoring_period,
        fetched_at,
        season_start,
        team_id,
        entry
    from teams
    {{ fo_unnest('teams.roster_entries', 'entry') }}

)

select
    entries.league_id,
    entries.season,
    entries.scoring_period,
    entries.team_id,
    entry.playerId as espn_player_id,
    entry.playerPoolEntry.player.fullName as player_name,
    entry.lineupSlotId as lineup_slot_id,
    slots.slot_abbrev as lineup_slot,
    entry.playerPoolEntry.player.defaultPositionId as default_position_id,
    positions.position_abbrev as default_position,
    entry.playerPoolEntry.player.proTeamId as pro_team_id,
    nullif(entry.injuryStatus, '') as injury_status,
    nullif(entry.acquisitionType, '') as acquisition_type,
    {{ fo_parse_fetched_at() }} as fetched_at,
    entries.season_start
from entries
left join {{ ref('espn_lineup_slots') }} as slots
    on slots.lineup_slot_id = entry.lineupSlotId
left join {{ ref('espn_player_positions') }} as positions
    on positions.position_id = entry.playerPoolEntry.player.defaultPositionId
