-- One row per player the league touched: everyone on a roster day plus anyone who appears
-- only in the transaction log (#11). A dim_ model describes a thing -- here a player -- with
-- one row per thing, and fact models join to it for his attributes.
--
-- WHY the union. Five players were added or dropped without ever sitting on a roster
-- snapshot. Facts about them still need a dimension row, so they are kept: resolved
-- through the id map by id alone (there is no roster name to fall back on), with a null
-- name and position. A player the id map lacks is kept too, as unresolved, rather than
-- dropped.
--
-- Name, default position, MLBAM id and resolution come from his latest roster day (latest
-- scoring_date, then lowest fantasy_team_id so the choice never depends on input order).
-- stg_idmap__players holds one row per ESPN id (it keeps the latest per id), so the join
-- cannot fan out; int_fantasy__player_crosswalk joins it the same way.
--
-- replacement_group tells a hitter from a pitcher (see the last paragraph):
--   - SP or RP when his default position says so; hitter for any other position;
--   - with no default position (transaction-only), the fo_replacement_group rule over his
--     MLB appearances across the WHOLE season, not just free-agent days: a pitcher dropped
--     after 400 outs must not become a hitter for want of a position. The same macro is
--     used by int_fantasy__replacement_levels, so the two cannot disagree;
--   - null only when he has no MLBAM id.
-- A resolved player with no MLB rows at all would get hitter from the macro; that is not
-- special-cased here.
--
-- A pitcher's days are measured by kind of outing since #52 (ADR 0008), not by a group, so
-- the column that chose a pitcher-slot level is gone; replacement_group only tells a hitter
-- from a pitcher for a drop's side.
--
-- No MLB team column: a player changes team within a season, so it is not his attribute.
-- No league_id or season, as the intermediates it reads (#28).

{{ config(materialized='table') }}

with roster_players as (

    select
        platform,
        platform_player_id,
        mlbam_player_id,
        player_name,
        player_resolution,
        default_position,
        first_rostered_date,
        last_rostered_date
    from (
        select
            platform,
            platform_player_id,
            mlbam_player_id,
            player_name,
            player_resolution,
            default_position,
            min(scoring_date) over (partition by platform_player_id) as first_rostered_date,
            max(scoring_date) over (partition by platform_player_id) as last_rostered_date,
            row_number() over (
                partition by platform_player_id
                order by scoring_date desc, fantasy_team_id
            ) as latest_rank
        from {{ ref('int_fantasy__roster_days') }}
    )
    where latest_rank = 1

),

transaction_only_players as (

    select distinct
        transactions.platform,
        transactions.platform_player_id
    from {{ ref('int_fantasy__transactions') }} as transactions
    left join roster_players
        on roster_players.platform_player_id = transactions.platform_player_id
    where transactions.platform_player_id is not null
      and roster_players.platform_player_id is null

),

players as (

    select
        platform,
        platform_player_id,
        mlbam_player_id,
        player_name,
        player_resolution,
        default_position,
        first_rostered_date,
        last_rostered_date,
        false as is_transaction_only
    from roster_players

    union all

    select
        transaction_only_players.platform,
        transaction_only_players.platform_player_id,
        crosswalk.mlbam_player_id,
        cast(null as varchar) as player_name,
        case when crosswalk.mlbam_player_id is not null then 'crosswalk_id' else 'unresolved' end
            as player_resolution,
        cast(null as varchar) as default_position,
        cast(null as date) as first_rostered_date,
        cast(null as date) as last_rostered_date,
        true as is_transaction_only
    from transaction_only_players
    left join {{ ref('stg_idmap__players') }} as crosswalk
        on crosswalk.espn_player_id = transaction_only_players.platform_player_id

),

season_totals as (

    select
        mlbam_player_id,
        sum(plate_appearances) as plate_appearances,
        sum(batters_faced) as batters_faced,
        sum(outs_recorded) as outs_recorded,
        sum(games_pitched) as games_pitched,
        sum(games_started) as games_started
    from {{ ref('int_mlb__player_game_days') }}
    group by mlbam_player_id

)

select
    players.platform,
    players.platform_player_id,
    players.mlbam_player_id,
    players.player_name,
    players.player_resolution,
    players.default_position,
    case
        when players.default_position in ('SP', 'RP') then players.default_position
        when players.default_position is not null then 'hitter'
        when players.mlbam_player_id is null then null
        else {{ fo_replacement_group(
            'season_totals.plate_appearances',
            'season_totals.batters_faced',
            'season_totals.outs_recorded',
            'season_totals.games_pitched',
            'season_totals.games_started'
        ) }}
    end as replacement_group,
    players.first_rostered_date,
    players.last_rostered_date,
    players.is_transaction_only
from players
left join season_totals
    on season_totals.mlbam_player_id = players.mlbam_player_id
