-- The places in a lineup a league-season fills (#12, R2.1): one row per starting slot it uses.
--
-- The lineup decisions ask where else a player could have started, so they need the shape of
-- a legal lineup as data: which slots score (is_starting_slot) and how many of each a team
-- fills a day (slot_count, from the league's settings, not hardcoded -- another league has
-- another shape). A starting slot with slot_count 0 is one the league explicitly does not
-- use (stg_espn__lineup_slot_limits keeps those as information) and is not a place to put
-- anyone, so it is left out here. Bench and injured-list slots are not places in a lineup.
--
-- slot_role (hitter or pitcher) is the seed's fact about which side of a player's game the
-- slot credits; the options model reads it to pick the side whose day value applies.
-- Staging has no platform, so it is the literal 'espn', as int_fantasy__roster_days does.

{{ config(materialized='view') }}

select
    'espn' as platform,
    limits.league_id,
    limits.season,
    limits.lineup_slot_id,
    limits.lineup_slot,
    slots.slot_role,
    limits.slot_count
from {{ ref('stg_espn__lineup_slot_limits') }} as limits
inner join {{ ref('espn_lineup_slots') }} as slots
    on slots.lineup_slot_id = limits.lineup_slot_id
where limits.is_starting_slot
    and limits.slot_count > 0
