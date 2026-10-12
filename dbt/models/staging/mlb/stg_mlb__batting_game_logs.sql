-- One row per (game, batter): component counts only.
--
-- No rate stats live here. AVG and friends are ratios of these columns, and a ratio
-- averaged over games is not the same as the ratio of the sums -- computing them
-- downstream from components is the only way to get them right.
--
-- Stored, not a view: this parses ~2,400 boxscore payloads, so a view would redo that
-- work on every query.
--
-- Built a season at a time. DuckDB holds every parsed payload of a run at once, and two
-- seasons took the build to its memory limit, so dbt runs this model once per calendar
-- year (microbatch), reading one season's captures through stg_raw__season_responses.
-- Every build redoes every season. On BigQuery it is a plain table (spec 0143, ADRs 0058
-- to 0060).

{{ config(
    materialized=('incremental' if target.type == 'duckdb' else 'table'),
    incremental_strategy=('microbatch' if target.type == 'duckdb' else none),
    event_time='season_start',
    batch_size='year',
    begin=var('first_season_start'),
    lookback=fo_batches_back_to_first_season(),
    concurrent_batches=false,
    on_schema_change='fail'
) }}

with players as (

    {{ fo_boxscore_players(ref('stg_raw__season_responses')) }}

)

select
    game_pk,
    {{ fo_json_int('player', '$.person.id') }} as mlbam_player_id,
    side,
    team_id,
    {{ fo_json_text('player', '$.person.fullName') }} as player_name,
    {{ fo_json_text('player', '$.position.abbreviation') }} as position,
    {{ fo_json_text('player', '$.battingOrder') }} as batting_order,
    {{ fo_json_bool('player', '$.gameStatus.isSubstitute') }} as is_substitute,

    {{ fo_json_int('player', '$.stats.batting.plateAppearances') }} as plate_appearances,
    {{ fo_json_int('player', '$.stats.batting.atBats') }} as at_bats,
    {{ fo_json_int('player', '$.stats.batting.hits') }} as hits,
    {{ fo_json_int('player', '$.stats.batting.doubles') }} as doubles,
    {{ fo_json_int('player', '$.stats.batting.triples') }} as triples,
    {{ fo_json_int('player', '$.stats.batting.homeRuns') }} as home_runs,
    {{ fo_json_int('player', '$.stats.batting.runs') }} as runs,
    {{ fo_json_int('player', '$.stats.batting.rbi') }} as runs_batted_in,
    {{ fo_json_int('player', '$.stats.batting.baseOnBalls') }} as walks,
    {{ fo_json_int('player', '$.stats.batting.intentionalWalks') }} as intentional_walks,
    {{ fo_json_int('player', '$.stats.batting.strikeOuts') }} as strikeouts,
    {{ fo_json_int('player', '$.stats.batting.stolenBases') }} as stolen_bases,
    {{ fo_json_int('player', '$.stats.batting.caughtStealing') }} as caught_stealing,
    {{ fo_json_int('player', '$.stats.batting.hitByPitch') }} as hit_by_pitch,
    {{ fo_json_int('player', '$.stats.batting.sacFlies') }} as sacrifice_flies,
    {{ fo_json_int('player', '$.stats.batting.sacBunts') }} as sacrifice_bunts,
    {{ fo_json_int('player', '$.stats.batting.totalBases') }} as total_bases,
    {{ fo_json_int('player', '$.stats.batting.groundIntoDoublePlay') }}
        as grounded_into_double_play,
    {{ fo_json_int('player', '$.stats.batting.catchersInterference') }} as catchers_interference,

    {{ fo_parse_fetched_at() }} as fetched_at,
    season_start
from players
-- Bench players carry an empty batting block; gamesPlayed = 1 marks an appearance. A
-- pinch runner has 0 plate appearances but can still steal a base, so filtering on
-- plate_appearances would lose real events.
where {{ fo_json_int('player', '$.stats.batting.gamesPlayed') }} = 1
{{ fo_latest_by_entity(['game_pk', fo_json_string('player', '$.person.id') | trim]) }}
