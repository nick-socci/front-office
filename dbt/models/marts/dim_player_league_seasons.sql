-- One row per player per league and season in which he was rostered or transacted (#28,
-- ADR 0012): everyone on a roster day of that league-season plus anyone who appears only in
-- its transaction log (#11). It holds what is true of a player IN a league-season, and every
-- league-season model (roster days, transaction impact, value) reads his MLBAM id and group
-- from here, never from dim_players.
--
-- WHY it exists. A player's MLBAM id is resolved per league and season (see
-- int_fantasy__player_crosswalk): the name fallback depends on which MLB players appeared in
-- that season and on the name ESPN showed in that league. A table with one row per platform
-- player would let a later season's or another league's match decide an earlier season's
-- number. So the per-player attributes that can differ between league-seasons live here, and
-- this table is the bridge from a platform's player id to an MLB id (ADR 0034); dim_players,
-- keyed by MLB id, reads the ids and the fallback names from it.
--
-- WHY the union. Five players in 2026 were added or dropped without ever sitting on a roster
-- snapshot. Facts about them still need a row, so they are kept: resolved through the id map
-- by id alone (there is no roster name to fall back on), with a null name and position. A
-- player the id map lacks is kept too, as unresolved, rather than dropped. A player who is
-- transaction-only in one league-season and rostered in another has a row of each kind: the
-- unresolved 2026 row of a player first matched by name in 2027 is correct, not a gap.
--
-- Within each league-season, name, default position, MLBAM id and resolution come from his
-- latest roster day there (latest scoring_date, then lowest fantasy_team_id so the choice
-- never depends on input order). stg_idmap__players holds one row per ESPN id, so the join
-- cannot fan out.
--
-- replacement_group tells a hitter from a pitcher:
--   - SP or RP when his default position says so; hitter for any other position;
--   - with no default position (transaction-only), the fo_replacement_group rule over his
--     MLB appearances in THAT MLB SEASON ONLY (R4.6), not just free-agent days: a pitcher
--     dropped after 400 outs must not become a hitter for want of a position, and 2027 starts
--     must not turn a 2026 reliever into a starter. The same macro is used by
--     int_fantasy__replacement_levels, so the two cannot disagree;
--   - null only when he has no MLBAM id.
-- A resolved player with no MLB rows at all would get hitter from the macro; that is not
-- special-cased here.
--
-- A pitcher's days are measured by kind of outing since #52 (ADR 0008), not by a group, so
-- replacement_group only tells a hitter from a pitcher for a drop's side.
--
-- No MLB team column: a player changes team within a season, so it is not his attribute.

{{ config(materialized='table') }}

with roster_players as (

    select
        platform,
        league_id,
        season,
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
            league_id,
            season,
            platform_player_id,
            mlbam_player_id,
            player_name,
            player_resolution,
            default_position,
            min(scoring_date) over (
                partition by platform, league_id, season, platform_player_id
            ) as first_rostered_date,
            max(scoring_date) over (
                partition by platform, league_id, season, platform_player_id
            ) as last_rostered_date,
            row_number() over (
                partition by platform, league_id, season, platform_player_id
                order by scoring_date desc, fantasy_team_id
            ) as latest_rank
        from {{ ref('int_fantasy__roster_days') }}
    )
    where latest_rank = 1

),

transaction_only_players as (

    select distinct
        transactions.platform,
        transactions.league_id,
        transactions.season,
        transactions.platform_player_id
    from {{ ref('int_fantasy__transactions') }} as transactions
    left join roster_players
        on roster_players.platform = transactions.platform
        and roster_players.league_id = transactions.league_id
        and roster_players.season = transactions.season
        and roster_players.platform_player_id = transactions.platform_player_id
    where transactions.platform_player_id is not null
      and roster_players.platform_player_id is null

),

players as (

    select
        platform,
        league_id,
        season,
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
        transaction_only_players.league_id,
        transaction_only_players.season,
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

-- Per MLB season, so a league-season's group never reads another season's appearances.
season_totals as (

    select
        mlbam_player_id,
        season,
        sum(plate_appearances) as plate_appearances,
        sum(batters_faced) as batters_faced,
        sum(outs_recorded) as outs_recorded,
        sum(games_pitched) as games_pitched,
        sum(games_started) as games_started
    from {{ ref('int_mlb__player_game_days') }}
    group by mlbam_player_id, season

)

select
    players.platform,
    players.league_id,
    players.season,
    players.platform_player_id,
    players.mlbam_player_id,
    players.player_resolution,
    players.player_name,
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
    and season_totals.season = players.season
