-- One row per scored category in the league's format.
--
-- This league scores 17 categories, not a standard 5x5, which is exactly why the names
-- come from a seed rather than being hardcoded. is_reverse marks the lower-is-better
-- ones (ERA, WHIP): a mart that ranks teams must not assume bigger is better.

with latest as (

    {{ fo_espn_latest('settings') }}

),

items as (

    select
        {{ fo_json_text('payload', '$.id') }} as league_id,
        {{ fo_json_int('payload', '$.seasonId') }} as season,
        unnest({{ fo_json_array('payload', '$.settings.scoringSettings.scoringItems[*]') }}) as item,
        fetched_at
    from latest

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
