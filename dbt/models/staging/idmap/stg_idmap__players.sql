-- The ESPN <-> MLBAM crosswalk.
--
-- Rows missing either id are dropped: a crosswalk entry that maps nothing is not a
-- mapping. Roughly half of the source rows are historical players with no ESPN id.
--
-- For the same reason, an ESPN id the capture gives to more than one player is dropped:
-- an entry that names two players does not say which one the id is. The real map gave
-- ESPN 5214984 to Jonah Tong and to Michael Tonkin, both pitchers, so no order could choose,
-- and a warehouse that kept Tonkin would have credited Tong's league days to him. Left out,
-- the id goes to int_fantasy__player_crosswalk's name fallback, which matches only a name
-- held by one MLB player that season and says so in `resolution`, or leaves the player
-- unresolved, never wrong (the owner, 2026-10-28; ADR 0109). The same holds for one MLB id
-- listed under two teams (#223, below).

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

kept_columns as (

    select
        espn_player_id,
        mlbam_player_id,
        {{ fo_json_text('row_json', '$.PLAYERNAME') }} as player_name,
        {{ fo_json_text('row_json', '$.TEAM') }} as team,
        {{ fo_json_text('row_json', '$.POS') }} as position,
        {{ fo_json_int('row_json', '$.IDFANGRAPHS') }} as fangraphs_id,
        fetched_at
    from with_ids
    where
        espn_player_id is not null
        and mlbam_player_id is not null

),

-- An ESPN id is ambiguous when the capture gives it to more than one entry that differs in
-- anything but position: another MLB id (Tong and Tonkin), or the same MLB id under two teams
-- (Matt Wilkinson, SF and CLE, on 2026-11-10, with two Baseball-Reference ids behind one MLB
-- id). Position alone does not make an id ambiguous: a two-way player is listed once per
-- position, and the rule at the foot of this model chooses between those rows. The ids are
-- left out whole (the owner, 2026-11-13, #223), as for Tong and Tonkin above.
ambiguous_ids as (

    select entries.espn_player_id
    from (
        select
            espn_player_id,
            mlbam_player_id,
            player_name,
            team,
            fangraphs_id
        from kept_columns
        group by
            espn_player_id,
            mlbam_player_id,
            player_name,
            team,
            fangraphs_id
    ) as entries
    group by entries.espn_player_id
    -- Qualified: BigQuery reads a bare name in HAVING as a select alias.
    having count(*) > 1

),

-- The map lists some players on more than one row, and the rows can be alike in every column
-- this model keeps: on 2026-11-10 Shohei Ohtani had two `DH` rows that differed only in
-- columns read nowhere here (his own id string and a Yahoo id), and the tie rule stopped the
-- build (#223). Rows alike in every kept column are one row, so they are grouped (`GROUP BY`
-- over every column, `NULL`s grouping together, the same on both warehouses). Rows that
-- differ in a kept column are not grouped, and still tie below: that is a conflict, not
-- a repeat.
distinct_rows as (

    select
        espn_player_id,
        mlbam_player_id,
        player_name,
        team,
        position,
        fangraphs_id,
        fetched_at
    from kept_columns
    where espn_player_id not in (select ambiguous_ids.espn_player_id from ambiguous_ids)
    group by
        espn_player_id,
        mlbam_player_id,
        player_name,
        team,
        position,
        fangraphs_id,
        fetched_at

)

select
    espn_player_id,
    mlbam_player_id,
    player_name,
    team,
    position,
    fangraphs_id,
    {{ fo_parse_fetched_at() }} as fetched_at
from distinct_rows
-- The map lists a two-way player once per position under one ESPN id and one MLB id
-- (Shohei Ohtani as P and as DH), in one capture, so recency cannot choose. The later
-- position in text order wins, P before DH: a rule to make the choice the same on every
-- warehouse, not a claim about the player (the owner, 2026-10-11; spec 0130).
{{ fo_latest_by_entity(
    ['espn_player_id'],
    order_by="fetched_at desc, position desc"
) }}
