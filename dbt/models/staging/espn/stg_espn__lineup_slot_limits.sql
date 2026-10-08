-- One row per lineup slot with how many of that slot a team fills each day.
--
-- The shape of a legal lineup. This league runs 1 C, 1 of each infield position, 3 OF,
-- 1 UTIL, 4 SP, 2 RP, 3 generic P, plus 5 bench and 4 IL -- but none of that is
-- hardcoded anywhere, because a different league has a different shape and the whole
-- point of reading settings as data is that the models do not care.
--
-- Read from `settings.rosterSettings.lineupSlotCounts`, another object where the keys
-- are the fact: {"0": 1, "5": 3, "16": 5, ...} maps slot id to count. ESPN emits an
-- entry for every slot it knows about, including the ones this league does not use, so
-- rows with slot_count = 0 are kept and left for consumers to filter -- "this league
-- explicitly has no DH slot" is information, not noise.

with latest as (

    {{ fo_espn_latest('settings') }}

),

header as (

    select
        {{ fo_json_text('payload', '$.id') }} as league_id,
        {{ fo_json_int('payload', '$.seasonId') }} as season,
        fetched_at,
        payload as settings_payload
    from latest

),

slot_keys as (

    select
        league_id,
        season,
        fetched_at,
        -- keys and values unnested together stay paired, so no path is built from a key
        unnest(
            {{ fo_json_keys('settings_payload', '$.settings.rosterSettings.lineupSlotCounts') }}
        ) as slot_key,
        unnest(
            {{ fo_json_values('settings_payload', '$.settings.rosterSettings.lineupSlotCounts') }}
        ) as slot_value
    from header

)

select
    slot_keys.league_id,
    slot_keys.season,
    try_cast(slot_keys.slot_key as bigint) as lineup_slot_id,
    slots.slot_abbrev as lineup_slot,
    slots.is_starting_slot,
    {{ fo_json_int('slot_keys.slot_value', '$') }} as slot_count,
    {{ fo_parse_fetched_at('slot_keys.fetched_at') }} as fetched_at
from slot_keys
left join {{ ref('espn_lineup_slots') }} as slots
    on slots.lineup_slot_id = try_cast(slot_keys.slot_key as bigint)
