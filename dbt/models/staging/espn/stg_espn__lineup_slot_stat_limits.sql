-- One row per (league, season, lineup slot) that ESPN limits a stat for: the settings'
-- lineupSlotStatLimits, an object keyed by slot id.
--
-- Not stg_espn__lineup_slot_limits, which says how many players fill each slot. This says
-- how much of one stat a slot may credit; the 2025 league has one entry, slot 22 on stat
-- 33 (games started) at 1.857 a day. The key is kept as ESPN files it and is not
-- interpreted here, nor is the stat: every entry is read as given, and what a limit means
-- is decided one level up (ADR 0071). A league-season whose object is empty has no row.
--
-- Keys and values are unnested together (fo_unnest_pair), so each key stays paired with
-- its own value. In the BigQuery slice, so written once for both warehouses (ADR 0051).
-- The payload is projected away in `header` before the unnest (AGENTS.md, rule 1).

{%- set limits_path = '$.settings.rosterSettings.lineupSlotStatLimits' %}

with latest as (

    {{ fo_espn_latest('settings') }}

),

header as (

    select
        {{ fo_json_text('payload', '$.id') }} as league_id,
        {{ fo_json_int('payload', '$.seasonId') }} as season,
        {{ fo_parse_fetched_at() }} as fetched_at,
        {{ fo_json_keys('payload', limits_path) }} as slot_keys,
        {{ fo_json_values('payload', limits_path) }} as limit_entries
    from latest

),

entries as (

    select
        header.league_id,
        header.season,
        header.fetched_at,
        -- slot_key and limit_entry are the names fo_unnest_pair gives the two unnested
        -- values; what they would be qualified with differs by warehouse, so they stay bare.
        slot_key,  -- noqa: RF02
        limit_entry  -- noqa: RF02
    from header
    {{ fo_unnest_pair('header.slot_keys', 'slot_key', 'header.limit_entries', 'limit_entry') }}

)

select
    league_id,
    season,
    {{ fo_safe_cast('slot_key', 'bigint') }} as lineup_slot_id,
    {{ fo_json_int('limit_entry', '$.statId') }} as stat_id,
    {{ fo_safe_cast(
        fo_json_string('limit_entry', '$.limitValue'), fo_type_float()
    ) }} as limit_value,
    fetched_at
from entries
