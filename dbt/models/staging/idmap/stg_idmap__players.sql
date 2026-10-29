-- The ESPN <-> MLBAM crosswalk.
--
-- Rows missing either id are dropped: a crosswalk entry that maps nothing is not a
-- mapping. Roughly half of the source rows are historical players with no ESPN id.
--
-- For the same reason, an ESPN id the capture gives to more than one MLB player is dropped:
-- an entry that names two players does not say which one the id is. The real map gave
-- ESPN 5214984 to Jonah Tong and to Michael Tonkin, both pitchers, so no order could choose,
-- and a warehouse that kept Tonkin would have credited Tong's league days to him. Left out,
-- the id goes to int_fantasy__player_crosswalk's name fallback, which matches only a name
-- held by one MLB player that season and says so in `resolution`, or leaves the player
-- unresolved, never wrong (the owner, 2026-10-28; ADR 0109).

with latest as (

    select
        payload,
        fetched_at,
        file_path
    from {{ ref('stg_raw__idmap_player_id_map') }}
    {{ fo_keep_first([], 'fetched_at desc, file_path desc') }}

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

),

with_ids as (

    select
        fetched_at,
        row_json,
        {{ fo_json_int('row_json', '$.ESPNID') }} as espn_player_id,
        {{ fo_json_int('row_json', '$.MLBID') }} as mlbam_player_id
    from mapped

),

ambiguous_ids as (

    select espn_player_id
    from with_ids
    where espn_player_id is not null
    group by espn_player_id
    -- Qualified: BigQuery reads a bare name in HAVING as a select alias.
    having count(distinct with_ids.mlbam_player_id) > 1

)

select
    espn_player_id,
    mlbam_player_id,
    {{ fo_json_text('row_json', '$.PLAYERNAME') }} as player_name,
    {{ fo_json_text('row_json', '$.TEAM') }} as team,
    {{ fo_json_text('row_json', '$.POS') }} as position,
    {{ fo_json_int('row_json', '$.IDFANGRAPHS') }} as fangraphs_id,
    {{ fo_parse_fetched_at() }} as fetched_at
from with_ids
where
    espn_player_id is not null
    and mlbam_player_id is not null
    and espn_player_id not in (select ambiguous_ids.espn_player_id from ambiguous_ids)
-- The map lists a two-way player once per position under one ESPN id and one MLB id
-- (Shohei Ohtani as P and as DH), in one capture, so recency cannot choose. The later
-- position in text order wins, P before DH: a rule to make the choice the same on every
-- warehouse, not a claim about the player (the owner, 2026-10-11; spec 0130).
{{ fo_latest_by_entity(
    ['espn_player_id'],
    order_by="fetched_at desc, " ~ fo_json_text('row_json', '$.POS') ~ " desc"
) }}
