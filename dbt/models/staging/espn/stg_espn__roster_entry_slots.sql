-- One row per (scoring period, team, player, eligible slot): the slots ESPN said a player
-- was eligible for WHEN THE PAYLOAD WAS FETCHED, attached to the roster of that scoring
-- period. Where he actually was is stg_espn__roster_entries.
--
-- This is not the day's eligibility unless the payload was fetched on the day. ESPN
-- returns a player's current eligibility whatever scoringPeriodId is requested (#52):
--   * every period of 2026 was fetched in one backfill (2026-09-26), and no player's
--     eligible slots change once across its 180 periods -- 493 players, 227 of them
--     hitters, who gain positions in-season;
--   * a pre-pipeline capture of the same periods five days earlier disagrees with it for
--     4 players (494 player-periods of 59,930): three pitchers are P,SP there and P,SP,RP
--     here, one hitter gains 2B, on periods as early as 1.
-- So for a backfilled period this is eligibility as of fetched_at, which is why that
-- column is carried. Eligibility only grows within a season, so the slot a player was
-- actually started in is always inside it (stg_espn__started_slot_is_always_eligible),
-- but a "could have started" reading of 2026 would allow moves that were not legal on
-- the day. Only a capture made on the day itself (#27) can carry that day's eligibility.
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
