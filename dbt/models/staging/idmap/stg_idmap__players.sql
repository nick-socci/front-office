-- The ESPN <-> MLBAM crosswalk.
--
-- Rows missing either id are dropped: a crosswalk entry that maps nothing is not a
-- mapping. Roughly half of the source rows are historical players with no ESPN id.

with latest as (

    select
        payload,
        fetched_at
    from {{ ref('stg_raw__idmap_player_id_map') }}
    qualify row_number() over (order by fetched_at desc) = 1

),

header as (

    select
        fetched_at,
        {{ fo_json_array('payload', '$[*]') }} as rows_json
    from latest

),

mapped as (

    select
        fetched_at,
        row_json
    from header
    {{ fo_unnest('header.rows_json', 'row_json') }}

)

select
    {{ fo_json_int('row_json', '$.ESPNID') }} as espn_player_id,
    {{ fo_json_int('row_json', '$.MLBID') }} as mlbam_player_id,
    {{ fo_json_text('row_json', '$.PLAYERNAME') }} as player_name,
    {{ fo_json_text('row_json', '$.TEAM') }} as team,
    {{ fo_json_text('row_json', '$.POS') }} as position,
    {{ fo_json_int('row_json', '$.IDFANGRAPHS') }} as fangraphs_id,
    {{ fo_parse_fetched_at() }} as fetched_at
from mapped
where
    {{ fo_json_int('row_json', '$.ESPNID') }} is not null
    and {{ fo_json_int('row_json', '$.MLBID') }} is not null
-- The map lists a two-way player once per position under one ESPN id (Shohei Ohtani as P
-- and as DH), in one capture, so recency cannot choose. The later position in text order
-- wins, P before DH: a rule to make the choice the same on every warehouse, not a claim
-- about the player (the owner, 2026-10-11; spec 0130).
{{ fo_latest_by_entity(
    [fo_json_string('row_json', '$.ESPNID') | trim],
    order_by="fetched_at desc, " ~ fo_json_text('row_json', '$.POS') ~ " desc"
) }}
