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
-- One row per platform player id, whatever ESPN has called him. ESPN can spell one
-- player two ways across snapshots (an accent added, a suffix dropped); a row per
-- (id, name) would double every roster day for him, since the join is on id alone. The
-- canonical name is the one on his latest roster snapshot: season, then scoring period
-- (every period in one backfill shares a fetched_at, so the period must decide first),
-- then fetched_at, with league and name as the final tie-break so the choice never
-- depends on input order. Roster days keep each entry's own display name; this name is
-- used only for the fallback match.

{{ config(materialized='ephemeral') }}

with mlb_players as (

    select
        strip_accents(player_name) as match_name,
        mlbam_player_id
    from {{ ref('stg_mlb__batting_game_logs') }}

    union

    select
        strip_accents(player_name),
        mlbam_player_id
    from {{ ref('stg_mlb__pitching_game_logs') }}

),

unambiguous_names as (

    select match_name, min(mlbam_player_id) as mlbam_player_id
    from mlb_players
    group by match_name
    having count(distinct mlbam_player_id) = 1

),

entries as (

    select
        espn_player_id,
        player_name
    from {{ ref('stg_espn__roster_entries') }}
    {{ fo_latest_by_entity(
        ['espn_player_id'],
        order_by='season desc, scoring_period desc, fetched_at desc, league_id, player_name'
    ) }}

)

select
    'espn' as platform,
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
