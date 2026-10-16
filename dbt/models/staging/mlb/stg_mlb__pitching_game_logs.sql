-- One row per (game, pitcher): component counts only.
--
-- Innings are stored as outs_recorded. MLB conveniently reports `outs` directly; the
-- original notation is kept in innings_pitched so a test can cross-check the two (see
-- tests/stg_mlb__pitching_outs_match_innings.sql).
--
-- The boxscores come from the boxscore capture view (stg_raw__mlb_boxscore, spec 0150),
-- which parses each file as it reads it.

{{ config(materialized='table') }}

with players as (

    {{ fo_boxscore_players() }}

),

lines as (

    -- The columns first, and the dedup over these narrow rows below: a window holds every
    -- row it ranks, and ranked with the player's JSON still attached it held every player
    -- of every season (spec 0150, Amendments). person_key is the raw text of the id, the
    -- deduplication key fo_json_string exists for.
    select
        game_pk,
        {{ fo_json_int('player.person', '$.id') }} as mlbam_player_id,
        side,
        team_id,
        {{ fo_json_text('player.person', '$.fullName') }} as player_name,
        {{ fo_json_int('player.stats.pitching', '$.gamesStarted') }} as games_started,

        {{ fo_json_int('player.stats.pitching', '$.outs') }} as outs_recorded,
        {{ fo_json_text('player.stats.pitching', '$.inningsPitched') }} as innings_pitched,
        {{ fo_json_int('player.stats.pitching', '$.battersFaced') }} as batters_faced,
        {{ fo_json_int('player.stats.pitching', '$.hits') }} as hits_allowed,
        {{ fo_json_int('player.stats.pitching', '$.runs') }} as runs_allowed,
        {{ fo_json_int('player.stats.pitching', '$.earnedRuns') }} as earned_runs,
        {{ fo_json_int('player.stats.pitching', '$.homeRuns') }} as home_runs_allowed,
        {{ fo_json_int('player.stats.pitching', '$.baseOnBalls') }} as walks,
        {{ fo_json_int('player.stats.pitching', '$.intentionalWalks') }} as intentional_walks,
        {{ fo_json_int('player.stats.pitching', '$.strikeOuts') }} as strikeouts,
        {{ fo_json_int('player.stats.pitching', '$.hitBatsmen') }} as hit_batsmen,
        {{ fo_json_int('player.stats.pitching', '$.balks') }} as balks,
        {{ fo_json_int('player.stats.pitching', '$.wildPitches') }} as wild_pitches,
        {{ fo_json_int('player.stats.pitching', '$.pitchesThrown') }} as pitches_thrown,
        {{ fo_json_int('player.stats.pitching', '$.inheritedRunners') }} as inherited_runners,

        {{ fo_json_int('player.stats.pitching', '$.wins') }} as wins,
        {{ fo_json_int('player.stats.pitching', '$.losses') }} as losses,
        {{ fo_json_int('player.stats.pitching', '$.saves') }} as saves,
        {{ fo_json_int('player.stats.pitching', '$.saveOpportunities') }} as save_opportunities,
        {{ fo_json_int('player.stats.pitching', '$.holds') }} as holds,
        {{ fo_json_int('player.stats.pitching', '$.blownSaves') }} as blown_saves,
        {{ fo_json_int('player.stats.pitching', '$.completeGames') }} as complete_games,
        {{ fo_json_int('player.stats.pitching', '$.shutouts') }} as shutouts,

        {{ fo_parse_fetched_at() }} as fetched_at,
        {{ fo_json_string('player.person', '$.id') | trim }} as person_key
    from players
    where {{ fo_json_int('player.stats.pitching', '$.gamesPitched') }} = 1

)

select
    game_pk,
    mlbam_player_id,
    side,
    team_id,
    player_name,
    games_started,
    outs_recorded,
    innings_pitched,
    batters_faced,
    hits_allowed,
    runs_allowed,
    earned_runs,
    home_runs_allowed,
    walks,
    intentional_walks,
    strikeouts,
    hit_batsmen,
    balks,
    wild_pitches,
    pitches_thrown,
    inherited_runners,
    wins,
    losses,
    saves,
    save_opportunities,
    holds,
    blown_saves,
    complete_games,
    shutouts,
    fetched_at
from lines
-- A player listed on both sides of one game (game 746942: a suspended game resumed after
-- he changed teams) ties on fetched_at, since both sides are one capture. The line with
-- the most batters faced is kept, the one where he played, then the side, so the choice
-- is stated and not left to row order (rule 5; the owner's decision, 2026-10-15).
{{ fo_latest_by_entity(
    ['game_pk', 'person_key'], order_by='fetched_at desc, batters_faced desc, side'
) }}
