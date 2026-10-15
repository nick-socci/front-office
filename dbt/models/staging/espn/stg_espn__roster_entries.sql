-- One row per (league, season, scoring period, team, player): who was rostered, in which
-- lineup slot, on a given day of fantasy scoring.
--
-- Two things about this model are deliberate, and both were learned the hard way when
-- earlier versions exhausted 24 GB of memory:
--
-- 1. The roster is read from its capture view (stg_raw__espn_roster, spec 0150), which
--    parses each payload file with a declared structure as it reads: the few fields wanted
--    are kept and the rest of the ~2.3 MB document, nearly all of it every rostered
--    player's season stats, never becomes a value. No payload is ever a column here.
--
-- 2. Everything else is computed in the `header` CTE, BEFORE any unnest, so the unnest
--    sits in a SELECT with only small columns beside it. unnest duplicates every other
--    column in its SELECT once per output row: the earlier versions kept the whole payload
--    there and copied it twelve times per period (AGENTS.md rule 1).
--
-- For the BigQuery migration: the structure of `teams` is declared once, in the view, and
-- the BigQuery variant of the view parses it from the uploaded payload (ADR 0070).
--
-- A plain table: it reads every capture at once, as the view streams them (spec 0150).

{{ config(materialized='table') }}

with latest as (

    {{ fo_espn_latest('roster', extra_partition='scoringPeriodId') }}

),

header as (

    -- Everything derived from the capture is computed here, so that only these columns
    -- reach the unnest below (and the capture view's extra columns do not).
    select
        id as league_id,
        seasonId as season,
        {{ fo_request_param('request_key', 'scoringPeriodId') }} as scoring_period,
        fetched_at,
        teams as teams_list
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
    {{ fo_parse_fetched_at() }} as fetched_at
from entries
left join {{ ref('espn_lineup_slots') }} as slots
    on slots.lineup_slot_id = entry.lineupSlotId
left join {{ ref('espn_player_positions') }} as positions
    on positions.position_id = entry.playerPoolEntry.player.defaultPositionId
