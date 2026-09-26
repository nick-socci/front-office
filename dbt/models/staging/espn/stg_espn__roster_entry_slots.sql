-- One row per (scoring period, team, player, eligible slot): where a player COULD have
-- been started that day, as opposed to where he actually was.
--
-- Without this, "you should have started someone else" is guesswork. Eligibility is a
-- daily snapshot in ESPN -- a player picks up second-base eligibility mid-season once he
-- has played enough games there -- so this is captured per scoring period rather than
-- once per season, and consumers must use the day's own eligibility.
--
-- Parsed from the raw payload rather than derived from stg_espn__roster_entries, so that
-- model keeps its one-row-per-player grain instead of carrying an array column. Both
-- models select the same response via fo_espn_latest, so they cannot disagree about
-- which snapshot they read; a relationships test enforces that they agree about rows.
--
-- The schema below is deliberately smaller than the one in stg_espn__roster_entries: the
-- fewer fields declared, the less of each 2.3 MB payload DuckDB has to materialise. The
-- payload is projected away in `header` before any unnest, for the reason documented at
-- length in stg_espn__roster_entries.

{{ config(materialized='table') }}

{% set slots_schema %}
[{
  "id": "BIGINT",
  "roster": {"entries": [{
    "playerId": "BIGINT",
    "playerPoolEntry": {"player": {"eligibleSlots": ["BIGINT"]}}
  }]}
}]
{% endset %}

with latest as (

    {{ fo_espn_latest('roster', extra_partition='scoringPeriodId') }}

),

header as (

    select
        {{ fo_json_text('payload', '$.id') }} as league_id,
        {{ fo_json_int('payload', '$.seasonId') }} as season,
        {{ fo_request_param('request_key', 'scoringPeriodId') }} as scoring_period,
        fetched_at,
        from_json(json_extract(payload, '$.teams'), '{{ slots_schema | trim }}') as teams_list
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

),

eligible as (

    select
        league_id,
        season,
        scoring_period,
        fetched_at,
        team_id,
        entry.playerId as espn_player_id,
        unnest(entry.playerPoolEntry.player.eligibleSlots) as lineup_slot_id
    from entries

)

select
    eligible.league_id,
    eligible.season,
    eligible.scoring_period,
    eligible.team_id,
    eligible.espn_player_id,
    eligible.lineup_slot_id,
    slots.slot_abbrev as lineup_slot,
    slots.is_starting_slot,
    {{ fo_parse_fetched_at('eligible.fetched_at') }} as fetched_at
from eligible
left join {{ ref('espn_lineup_slots') }} as slots
    on slots.lineup_slot_id = eligible.lineup_slot_id
