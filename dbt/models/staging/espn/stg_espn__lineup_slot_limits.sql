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

{%- set counts_path = '$.settings.rosterSettings.lineupSlotCounts' %}

with latest as (

    {{ fo_espn_latest('settings') }}

),

header as (

    select
        {{ fo_json_text('payload', '$.id') }} as league_id,
        {{ fo_json_int('payload', '$.seasonId') }} as season,
        fetched_at,
        {{ fo_json_keys('payload', counts_path) }} as slot_keys,
        {{ fo_json_values('payload', counts_path) }} as slot_values
    from latest

),

slot_keys as (

    select
        header.league_id,
        header.season,
        header.fetched_at,
        -- slot_key and slot_value are the names fo_unnest_pair gives the two unnested
        -- values; what they would be qualified with differs by warehouse, so they stay bare.
        -- Keys and values are unnested together, so no path is built from a key. The
        -- payload is projected away in `header` first (AGENTS.md, rule 1).
        slot_key,  -- noqa: RF02
        slot_value  -- noqa: RF02
    from header
    {{ fo_unnest_pair('header.slot_keys', 'slot_key', 'header.slot_values', 'slot_value') }}

)

select
    slot_keys.league_id,
    slot_keys.season,
    {{ fo_safe_cast('slot_keys.slot_key', 'bigint') }} as lineup_slot_id,
    slots.slot_abbrev as lineup_slot,
    slots.is_starting_slot,
    {{ fo_json_int('slot_keys.slot_value', '$') }} as slot_count,
    {{ fo_parse_fetched_at('slot_keys.fetched_at') }} as fetched_at
from slot_keys
left join {{ ref('espn_lineup_slots') }} as slots
    on slots.lineup_slot_id = {{ fo_safe_cast('slot_keys.slot_key', 'bigint') }}
