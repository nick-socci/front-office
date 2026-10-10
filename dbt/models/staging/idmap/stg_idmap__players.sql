-- The ESPN <-> MLBAM crosswalk.
--
-- Rows missing either id are dropped: a crosswalk entry that maps nothing is not a
-- mapping. Roughly half of the source rows are historical players with no ESPN id.

with latest as (

    select
        payload,
        fetched_at
    from {{ source('raw', 'api_responses') }}
    where
        source = 'idmap'
        and endpoint = 'player_id_map'
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
        unnest(rows_json) as row_json
    from header

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
where         {{ fo_json_int('row_json', '$.ESPNID') }} is not null
    and {{ fo_json_int('row_json', '$.MLBID') }} is not null
{{ fo_latest_by_entity([fo_json_string('row_json', '$.ESPNID') | trim]) }}
