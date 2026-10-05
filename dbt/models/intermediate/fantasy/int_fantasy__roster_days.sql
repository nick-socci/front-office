-- One row per (fantasy team, player, calendar date): who was rostered, in which slot,
-- and whether that slot scored.
--
-- Every roster day, not just the starts -- the bench is the whole point of the lineup
-- marts later on. is_started separates them, and comes from the seed rather than a
-- string comparison against 'BE' and 'IL', because whether a slot scores is a property
-- of the slot. slot_role is the same kind of fact: which side of a player's game the
-- slot credits (hitter, pitcher, or bench for neither).
--
-- mlbam_player_id is left nullable even though nothing is null in 2026. The crosswalk
-- resolves 55,315 of 55,653 roster days by id and the unambiguous-name fallback covers
-- the remaining 338, including the nine players the crosswalk test warns about -- so
-- every roster day currently resolves. Making the column NOT NULL would encode that as
-- a guarantee, and it is not one: the SFBB map lags for late call-ups, so next season a
-- player can appear here with no id. Keeping it nullable with player_resolution marked
-- 'unresolved' means such a player shows up as a gap to investigate rather than
-- failing the build or, worse, being dropped and quietly shrinking a roster.

{{ config(materialized='table') }}

select
    'espn' as platform,
    entries.league_id,
    entries.season,
    days.scoring_date,
    entries.scoring_period,
    entries.team_id as fantasy_team_id,
    entries.espn_player_id as platform_player_id,
    crosswalk.mlbam_player_id,
    crosswalk.resolution as player_resolution,
    entries.player_name,
    entries.lineup_slot_id as roster_slot_id,
    entries.lineup_slot as roster_slot,
    slots.is_starting_slot as is_started,
    slots.slot_role,
    entries.default_position,
    entries.injury_status,
    entries.acquisition_type
from {{ ref('stg_espn__roster_entries') }} as entries
inner join {{ ref('stg_espn__scoring_periods') }} as days
    on days.league_id = entries.league_id
    and days.season = entries.season
    and days.scoring_period = entries.scoring_period
inner join {{ ref('espn_lineup_slots') }} as slots
    on slots.lineup_slot_id = entries.lineup_slot_id
left join {{ ref('int_fantasy__player_crosswalk') }} as crosswalk
    on crosswalk.league_id = entries.league_id
    and crosswalk.season = entries.season
    and crosswalk.platform_player_id = entries.espn_player_id
