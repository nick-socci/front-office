-- One row per (player, calendar date): everything a major leaguer did that day.
--
-- Fantasy scoring happens per day, not per game, so this is the grain the whole
-- attribution layer needs. Three things make it more than a rename of the staging
-- models, and all three are real in the 2026 season rather than hypothetical:
--
--   * 412 player-dates have TWO batting lines and 3 have two pitching lines --
--     doubleheaders. Both games count toward the fantasy day, verified against ESPN's
--     own numbers for matchup period 15, which contains six doubleheader starts:
--     AB 324, H 72, HR 10, R 43, TB 112, matching exactly.
--   * 212 player-dates appear in BOTH the batting and pitching logs. A pitcher who
--     bats, or a genuine two-way player, is one row here with both sides populated --
--     which is why this is a full outer join and not a union.
--   * Components only, never rates. AVG and ERA are computed at whatever grain the
--     question needs, downstream. Innings stay as outs_recorded for the same reason.
--
-- Materialized as a table: it is the join target for every roster-day above it, and
-- 71,044 rows is nothing.

{{ config(materialized='table') }}

with batting as (

    select
        logs.mlbam_player_id,
        games.official_date as game_date,
        count(*) as games_batted,
        sum(logs.plate_appearances) as plate_appearances,
        sum(logs.at_bats) as at_bats,
        sum(logs.hits) as hits,
        sum(logs.doubles) as doubles,
        sum(logs.triples) as triples,
        sum(logs.home_runs) as home_runs,
        sum(logs.runs) as runs,
        sum(logs.runs_batted_in) as runs_batted_in,
        sum(logs.walks) as batter_walks,
        sum(logs.intentional_walks) as batter_intentional_walks,
        sum(logs.strikeouts) as batter_strikeouts,
        sum(logs.stolen_bases) as stolen_bases,
        sum(logs.caught_stealing) as caught_stealing,
        sum(logs.hit_by_pitch) as hit_by_pitch,
        sum(logs.sacrifice_flies) as sacrifice_flies,
        sum(logs.sacrifice_bunts) as sacrifice_bunts,
        sum(logs.total_bases) as total_bases,
        sum(logs.grounded_into_double_play) as grounded_into_double_play
    from {{ ref('stg_mlb__batting_game_logs') }} as logs
    inner join {{ ref('stg_mlb__games') }} as games
        on games.game_pk = logs.game_pk
    group by logs.mlbam_player_id, games.official_date

),

pitching as (

    select
        logs.mlbam_player_id,
        games.official_date as game_date,
        count(*) as games_pitched,
        sum(logs.games_started) as games_started,
        sum(logs.outs_recorded) as outs_recorded,
        sum(logs.batters_faced) as batters_faced,
        sum(logs.hits_allowed) as hits_allowed,
        sum(logs.runs_allowed) as runs_allowed,
        sum(logs.earned_runs) as earned_runs,
        sum(logs.home_runs_allowed) as home_runs_allowed,
        sum(logs.walks) as pitcher_walks,
        sum(logs.intentional_walks) as pitcher_intentional_walks,
        sum(logs.strikeouts) as pitcher_strikeouts,
        sum(logs.hit_batsmen) as hit_batsmen,
        sum(logs.wild_pitches) as wild_pitches,
        sum(logs.pitches_thrown) as pitches_thrown,
        sum(logs.wins) as wins,
        sum(logs.losses) as losses,
        sum(logs.saves) as saves,
        sum(logs.save_opportunities) as save_opportunities,
        sum(logs.holds) as holds,
        sum(logs.blown_saves) as blown_saves,
        sum(logs.complete_games) as complete_games,
        sum(logs.shutouts) as shutouts
    from {{ ref('stg_mlb__pitching_game_logs') }} as logs
    inner join {{ ref('stg_mlb__games') }} as games
        on games.game_pk = logs.game_pk
    group by logs.mlbam_player_id, games.official_date

)

select
    coalesce(batting.mlbam_player_id, pitching.mlbam_player_id) as mlbam_player_id,
    coalesce(batting.game_date, pitching.game_date) as game_date,

    coalesce(batting.games_batted, 0) as games_batted,
    coalesce(pitching.games_pitched, 0) as games_pitched,

    -- Zero, not null: a pitcher who did not bat had no plate appearances, which is a
    -- number. Nulls here would poison every sum downstream.
    coalesce(batting.plate_appearances, 0) as plate_appearances,
    coalesce(batting.at_bats, 0) as at_bats,
    coalesce(batting.hits, 0) as hits,
    coalesce(batting.doubles, 0) as doubles,
    coalesce(batting.triples, 0) as triples,
    coalesce(batting.home_runs, 0) as home_runs,
    coalesce(batting.runs, 0) as runs,
    coalesce(batting.runs_batted_in, 0) as runs_batted_in,
    coalesce(batting.batter_walks, 0) as batter_walks,
    coalesce(batting.batter_intentional_walks, 0) as batter_intentional_walks,
    coalesce(batting.batter_strikeouts, 0) as batter_strikeouts,
    coalesce(batting.stolen_bases, 0) as stolen_bases,
    coalesce(batting.caught_stealing, 0) as caught_stealing,
    coalesce(batting.hit_by_pitch, 0) as hit_by_pitch,
    coalesce(batting.sacrifice_flies, 0) as sacrifice_flies,
    coalesce(batting.sacrifice_bunts, 0) as sacrifice_bunts,
    coalesce(batting.total_bases, 0) as total_bases,
    coalesce(batting.grounded_into_double_play, 0) as grounded_into_double_play,

    coalesce(pitching.games_started, 0) as games_started,
    coalesce(pitching.outs_recorded, 0) as outs_recorded,
    coalesce(pitching.batters_faced, 0) as batters_faced,
    coalesce(pitching.hits_allowed, 0) as hits_allowed,
    coalesce(pitching.runs_allowed, 0) as runs_allowed,
    coalesce(pitching.earned_runs, 0) as earned_runs,
    coalesce(pitching.home_runs_allowed, 0) as home_runs_allowed,
    coalesce(pitching.pitcher_walks, 0) as pitcher_walks,
    coalesce(pitching.pitcher_intentional_walks, 0) as pitcher_intentional_walks,
    coalesce(pitching.pitcher_strikeouts, 0) as pitcher_strikeouts,
    coalesce(pitching.hit_batsmen, 0) as hit_batsmen,
    coalesce(pitching.wild_pitches, 0) as wild_pitches,
    coalesce(pitching.pitches_thrown, 0) as pitches_thrown,
    coalesce(pitching.wins, 0) as wins,
    coalesce(pitching.losses, 0) as losses,
    coalesce(pitching.saves, 0) as saves,
    coalesce(pitching.save_opportunities, 0) as save_opportunities,
    coalesce(pitching.holds, 0) as holds,
    coalesce(pitching.blown_saves, 0) as blown_saves,
    coalesce(pitching.complete_games, 0) as complete_games,
    coalesce(pitching.shutouts, 0) as shutouts
from batting
full outer join pitching
    on pitching.mlbam_player_id = batting.mlbam_player_id
    and pitching.game_date = batting.game_date
