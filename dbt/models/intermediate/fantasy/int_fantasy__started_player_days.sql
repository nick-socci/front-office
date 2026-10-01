-- The attribution grain: one row per started player-day, with what that player
-- actually did in MLB that day.
--
-- This is the model everything in the mart layer is built on. It answers the only
-- question that matters for scoring a categories league -- who was in a scoring slot,
-- and what did they produce -- and it is the model the reconciliation against ESPN's
-- own scoreByStat will prove or disprove.
--
-- A LEFT join, not an inner one. A started player whose real team had an off day, or
-- who was benched by his actual manager, produces a row of zeroes rather than no row.
-- The distinction matters: "started nobody" and "started someone who did nothing" look
-- identical after an inner join, and only one of them is a management mistake.
--
-- But a row of zeroes is only a real zero if the inputs were there. input_status says
-- which it is (#25), checked in this order:
--   unresolved_player  -- no MLBAM id, so his stats could not be looked up at all;
--   played             -- he appears in that date's MLB production;
--   missing_boxscore   -- a game played that date has no loaded boxscore, so he may be
--                         in it. Flags every non-appearing player that date, not just
--                         the ones on the missing game's teams: over-flagging is the
--                         safe direction, and the audit gates this to zero anyway;
--   verified_off       -- every game played that date is loaded (or there were none),
--                         so he did not play. A team off day and a manager's bench are
--                         both real zeroes for fantasy scoring, so they share a status.
-- The zero-filled columns are kept for every status. Consumers decide what to do with
-- the non-verified rows; they must not quietly count them as zeroes.
--
-- Doubleheaders are already summed one level down, in int_mlb__player_game_days.
-- Verified against ESPN for matchup period 15, which contains six doubleheader starts.

{{ config(materialized='table') }}

select
    days.platform,
    days.league_id,
    days.season,
    days.scoring_date,
    days.scoring_period,
    days.fantasy_team_id,
    days.platform_player_id,
    days.mlbam_player_id,
    days.player_name,
    days.roster_slot,
    days.player_resolution,

    coalesce(stats.games_batted, 0) as games_batted,
    coalesce(stats.games_pitched, 0) as games_pitched,
    (stats.mlbam_player_id is not null) as played,
    case
        when days.mlbam_player_id is null then 'unresolved_player'
        when stats.mlbam_player_id is not null then 'played'
        -- No row in game_dates means no MLB games that date: complete by definition.
        when not coalesce(game_dates.is_complete, true) then 'missing_boxscore'
        else 'verified_off'
    end as input_status,

    coalesce(stats.plate_appearances, 0) as plate_appearances,
    coalesce(stats.at_bats, 0) as at_bats,
    coalesce(stats.hits, 0) as hits,
    coalesce(stats.doubles, 0) as doubles,
    coalesce(stats.triples, 0) as triples,
    coalesce(stats.home_runs, 0) as home_runs,
    coalesce(stats.runs, 0) as runs,
    coalesce(stats.runs_batted_in, 0) as runs_batted_in,
    coalesce(stats.batter_walks, 0) as batter_walks,
    coalesce(stats.batter_strikeouts, 0) as batter_strikeouts,
    coalesce(stats.stolen_bases, 0) as stolen_bases,
    coalesce(stats.caught_stealing, 0) as caught_stealing,
    coalesce(stats.hit_by_pitch, 0) as hit_by_pitch,
    coalesce(stats.sacrifice_flies, 0) as sacrifice_flies,
    coalesce(stats.total_bases, 0) as total_bases,

    coalesce(stats.games_started, 0) as games_started,
    coalesce(stats.outs_recorded, 0) as outs_recorded,
    coalesce(stats.batters_faced, 0) as batters_faced,
    coalesce(stats.hits_allowed, 0) as hits_allowed,
    coalesce(stats.runs_allowed, 0) as runs_allowed,
    coalesce(stats.earned_runs, 0) as earned_runs,
    coalesce(stats.home_runs_allowed, 0) as home_runs_allowed,
    coalesce(stats.pitcher_walks, 0) as pitcher_walks,
    coalesce(stats.pitcher_strikeouts, 0) as pitcher_strikeouts,
    coalesce(stats.hit_batsmen, 0) as hit_batsmen,
    coalesce(stats.wins, 0) as wins,
    coalesce(stats.losses, 0) as losses,
    coalesce(stats.saves, 0) as saves,
    coalesce(stats.holds, 0) as holds,
    coalesce(stats.blown_saves, 0) as blown_saves
from {{ ref('int_fantasy__roster_days') }} as days
left join {{ ref('int_mlb__player_game_days') }} as stats
    on stats.mlbam_player_id = days.mlbam_player_id
    and stats.game_date = days.scoring_date
left join {{ ref('int_mlb__game_dates') }} as game_dates
    on game_dates.official_date = days.scoring_date
where days.is_started
