-- Resolves a fantasy platform's player id to an MLBAM id, and records HOW.
--
-- Ephemeral on purpose. This is an internal helper with no independent meaning: it is
-- used by two models above it and nobody would ever query it directly, so dbt inlines
-- it as a CTE rather than building a relation. That is the trade -- no object in the
-- warehouse, and no way to test or query it on its own.
--
-- It is also why the four int_fantasy__* interface models are views rather than
-- ephemeral: dbt does not support model contracts on ephemeral models, and a contract
-- is the entire point of those four.
--
-- Two-step resolution, in order, carried over from docs/examples/roster_day_query.sql:
--
--   1. the SFBB crosswalk, which resolved 99.41% of started entries in 2026 and
--      correctly separates the two different major leaguers named Max Muncy;
--   2. failing that, an accent-normalised name match, but ONLY for names belonging to
--      exactly one MLB player. ESPN strips accents where MLB does not, and the
--      crosswalk lags for late call-ups, so the fallback earns its place. Restricting
--      it to unambiguous names is what stops it silently merging two people.
--
-- resolution keeps that decision visible downstream instead of burying it in a
-- coalesce, so a mart can report how its players were matched.
--
-- Resolved PER LEAGUE-SEASON, not once per player (#28). The name fallback depends on
-- two things that change with the season: who the MLB players of that season are, and
-- what name ESPN showed for the player in that league. If either were pooled across
-- seasons or leagues, loading another season could create a match (a 2027 rookie
-- sharing a 2026 name) or destroy one (a second player with the name appearing in
-- 2027), and one league's spelling could decide another league's match. So a name
-- counts as unambiguous only if it belongs to exactly ONE MLB player who appeared in
-- THAT MLB season, and the name used is the one on his latest snapshot of THAT
-- league-season.
--
-- One row per (platform, league, season, platform player id), whatever ESPN has called
-- him. ESPN can spell one player two ways across snapshots (an accent added, a suffix
-- dropped); a row per (id, name) would double every roster day for him, since the join
-- is on id alone. The canonical name is the one on his latest roster snapshot of the
-- league-season: scoring period (every period in one backfill shares a fetched_at, so
-- the period must decide first), then fetched_at, with the name as the final tie-break
-- so the choice never depends on input order. Roster days keep each entry's own display
-- name; this name is used only for the fallback match.

{{ config(materialized='ephemeral') }}

with mlb_players as (

    select
        strip_accents(logs.player_name) as match_name,
        logs.mlbam_player_id,
        games.season
    from {{ ref('stg_mlb__batting_game_logs') }} as logs
    inner join {{ ref('stg_mlb__games') }} as games
        on games.game_pk = logs.game_pk

    union

    select
        strip_accents(logs.player_name) as match_name,
        logs.mlbam_player_id,
        games.season
    from {{ ref('stg_mlb__pitching_game_logs') }} as logs
    inner join {{ ref('stg_mlb__games') }} as games
        on games.game_pk = logs.game_pk

),

unambiguous_names as (

    select
        match_name,
        season,
        min(mlbam_player_id) as mlbam_player_id
    from mlb_players
    group by match_name, season
    having count(distinct mlbam_player_id) = 1

),

entries as (

    select
        league_id,
        season,
        espn_player_id,
        player_name
    from {{ ref('stg_espn__roster_entries') }}
    {{ fo_latest_by_entity(
        ['league_id', 'season', 'espn_player_id'],
        order_by='scoring_period desc, fetched_at desc, player_name'
    ) }}

)

select
    'espn' as platform,
    entries.league_id,
    entries.season,
    entries.espn_player_id as platform_player_id,
    entries.player_name,
    coalesce(crosswalk.mlbam_player_id, unambiguous_names.mlbam_player_id)
        as mlbam_player_id,
    case
        when crosswalk.mlbam_player_id is not null then 'crosswalk_id'
        when unambiguous_names.mlbam_player_id is not null then 'unambiguous_name'
        else 'unresolved'
    end as resolution
from entries
left join {{ ref('stg_idmap__players') }} as crosswalk
    on crosswalk.espn_player_id = entries.espn_player_id
left join unambiguous_names
    on unambiguous_names.match_name = strip_accents(entries.player_name)
    and unambiguous_names.season = entries.season
