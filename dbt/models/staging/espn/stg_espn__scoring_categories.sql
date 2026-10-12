-- One row per scored category in the league's format.
--
-- This league scores 17 categories, not a standard 5x5, which is exactly why the names
-- come from a seed rather than being hardcoded. is_reverse marks the lower-is-better
-- ones (ERA, WHIP): a mart that ranks teams must not assume bigger is better.

with latest as (

    {{ fo_espn_latest('settings') }}

),

header as (

    -- the payload is left behind here, before the unnest (AGENTS.md rule 1)
    select
        {{ fo_json_text('payload', '$.id') }} as league_id,
        {{ fo_json_int('payload', '$.seasonId') }} as season,
        {{ fo_json_array('payload', '$.settings.scoringSettings.scoringItems[*]') }}
            as scoring_items,
        fetched_at
    from latest

),

items as (

    select
        league_id,
        season,
        item,
        fetched_at
    from header
    {{ fo_unnest('header.scoring_items', 'item') }}

)

select
    items.league_id,
    items.season,
    {{ fo_json_int('item', '$.statId') }} as stat_id,
    stats.stat_abbrev,
    stats.display_label,
    {{ fo_json_bool('item', '$.isReverseItem') }} as is_reverse,
    {{ fo_json_int('item', '$.points') }} as points,
    {{ fo_parse_fetched_at('items.fetched_at') }} as fetched_at
from items
left join {{ ref('espn_stat_ids') }} as stats
    on stats.stat_id = {{ fo_json_int('item', '$.statId') }}
