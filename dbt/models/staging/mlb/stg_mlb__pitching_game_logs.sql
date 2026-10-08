-- One row per (game, pitcher): component counts only.
--
-- Innings are stored as outs_recorded. MLB conveniently reports `outs` directly; the
-- original notation is kept in innings_pitched so a test can cross-check the two (see
-- tests/stg_mlb__pitching_outs_match_innings.sql).

{{ config(materialized='table') }}

with players as (

    {{ fo_boxscore_players() }}

)

select
    game_pk,
    {{ fo_json_int('player', '$.person.id') }} as mlbam_player_id,
    side,
    team_id,
    {{ fo_json_text('player', '$.person.fullName') }} as player_name,
    {{ fo_json_int('player', '$.stats.pitching.gamesStarted') }} as games_started,

    {{ fo_json_int('player', '$.stats.pitching.outs') }} as outs_recorded,
    {{ fo_json_text('player', '$.stats.pitching.inningsPitched') }} as innings_pitched,
    {{ fo_json_int('player', '$.stats.pitching.battersFaced') }} as batters_faced,
    {{ fo_json_int('player', '$.stats.pitching.hits') }} as hits_allowed,
    {{ fo_json_int('player', '$.stats.pitching.runs') }} as runs_allowed,
    {{ fo_json_int('player', '$.stats.pitching.earnedRuns') }} as earned_runs,
    {{ fo_json_int('player', '$.stats.pitching.homeRuns') }} as home_runs_allowed,
    {{ fo_json_int('player', '$.stats.pitching.baseOnBalls') }} as walks,
    {{ fo_json_int('player', '$.stats.pitching.intentionalWalks') }} as intentional_walks,
    {{ fo_json_int('player', '$.stats.pitching.strikeOuts') }} as strikeouts,
    {{ fo_json_int('player', '$.stats.pitching.hitBatsmen') }} as hit_batsmen,
    {{ fo_json_int('player', '$.stats.pitching.balks') }} as balks,
    {{ fo_json_int('player', '$.stats.pitching.wildPitches') }} as wild_pitches,
    {{ fo_json_int('player', '$.stats.pitching.pitchesThrown') }} as pitches_thrown,
    {{ fo_json_int('player', '$.stats.pitching.inheritedRunners') }} as inherited_runners,

    {{ fo_json_int('player', '$.stats.pitching.wins') }} as wins,
    {{ fo_json_int('player', '$.stats.pitching.losses') }} as losses,
    {{ fo_json_int('player', '$.stats.pitching.saves') }} as saves,
    {{ fo_json_int('player', '$.stats.pitching.saveOpportunities') }} as save_opportunities,
    {{ fo_json_int('player', '$.stats.pitching.holds') }} as holds,
    {{ fo_json_int('player', '$.stats.pitching.blownSaves') }} as blown_saves,
    {{ fo_json_int('player', '$.stats.pitching.completeGames') }} as complete_games,
    {{ fo_json_int('player', '$.stats.pitching.shutouts') }} as shutouts,

    {{ fo_parse_fetched_at() }} as fetched_at
from players
where {{ fo_json_int('player', '$.stats.pitching.gamesPitched') }} = 1
{{ fo_latest_by_entity(['game_pk', fo_json_string('player', '$.person.id') | trim]) }}
