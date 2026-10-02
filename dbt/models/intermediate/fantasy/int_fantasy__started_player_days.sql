-- The attribution grain: one row per started player-day, with the MLB production his
-- fantasy slot credits that day.
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
--   missing_boxscore   -- a game played that date has no loaded boxscore, so he may be
--                         in it. That holds even if he appears in another game that
--                         date: half a doubleheader is not his day's production. Flags
--                         every resolved player that date, not just the ones on the
--                         missing game's teams: over-flagging is the safe direction,
--                         and the audit gates this to zero anyway;
--   played             -- every game that date is loaded and he appears in one;
--   verified_off       -- every game played that date is loaded (or there were none),
--                         and he is in none of them. A team off day and a manager's
--                         bench are both real zeroes for fantasy scoring, so they share
--                         a status.
-- played (the boolean) still says only whether he appears in what is loaded, so it can
-- be true on a missing_boxscore row. The stat columns are kept for every status.
-- Consumers decide what to do with the non-verified rows; they must not quietly count
-- them as complete.
--
-- Credited, not everything he did (#10). A hitter slot credits only his batting and a
-- pitcher slot (P, SP, RP) only his pitching -- the slot's slot_role, from the
-- espn_lineup_slots seed; the two column lists are the fo_*_columns macros. That is
-- ESPN's rule, measured rather than assumed: summing every started player's full line
-- leaves up to 18 of 286 matchup sides off ESPN per stat; crediting by role leaves only
-- official-scoring differences. A pitcher's at-bat or a position player's mop-up inning
-- is real but scores nothing, and stays visible in int_mlb__player_game_days. played
-- and input_status describe his whole day, not the credited part: they say whether the
-- inputs are complete, which crediting can't change.
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

    (stats.mlbam_player_id is not null) as played,
    case
        when days.mlbam_player_id is null then 'unresolved_player'
        -- No row in game_dates means no MLB games that date: complete by definition.
        when not coalesce(game_dates.is_complete, true) then 'missing_boxscore'
        when stats.mlbam_player_id is not null then 'played'
        else 'verified_off'
    end as input_status,
    days.slot_role,

    {%- for column in fo_batting_columns() %}
    case when days.slot_role = 'hitter' then coalesce(stats.{{ column }}, 0) else 0 end as {{ column }},
    {%- endfor %}
    {%- for column in fo_pitching_columns() %}
    case when days.slot_role = 'pitcher' then coalesce(stats.{{ column }}, 0) else 0 end as {{ column }}
        {{- ',' if not loop.last }}
    {%- endfor %}
from {{ ref('int_fantasy__roster_days') }} as days
left join {{ ref('int_mlb__player_game_days') }} as stats
    on stats.mlbam_player_id = days.mlbam_player_id
    and stats.game_date = days.scoring_date
left join {{ ref('int_mlb__game_dates') }} as game_dates
    on game_dates.official_date = days.scoring_date
where days.is_started
