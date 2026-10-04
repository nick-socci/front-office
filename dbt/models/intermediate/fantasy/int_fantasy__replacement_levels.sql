-- What a replacement player produces per day played, for each kind of day: one row per
-- (day_kind, component), the kind being batting, start or relief. Every player's value is
-- measured against this (#11, #52): a player is worth what he did above what a free agent
-- would have done in the same playing time, and a pitcher's start is measured against a
-- free agent's start, his relief appearance against a free agent's relief appearance
-- (ADR 0008).
--
-- DEFINITION. Each pool is the top N MLB players of its kind among those nobody in the
-- league had rostered, N being the number of fantasy teams (count of int_fantasy__teams,
-- never a literal 12).
--   1. Free-agent days: rows of int_mlb__player_game_days on a scoring date (any date in
--      int_fantasy__roster_days) where the player is on no fantasy roster that date.
--   2. Batting pool: free agents whose fo_replacement_group over their free-agent days is
--      hitter, top N by plate appearances, ties broken by mlbam_player_id. A played day is
--      one with games_batted > 0, and only batting components are credited, so a hitter's
--      mop-up inning is neither a played day nor a component of batting.
--   3. Pitching pools, one per kind (start, relief): each free-agent day is classified by
--      fo_pitching_day_kind, from that day's own games_started and games_pitched. Every
--      free agent with at least one day of a kind is a candidate for that kind's pool,
--      ranked by how many such days he had, then by outs recorded over them, then by
--      mlbam_player_id; the top N are in. No replacement group is consulted, so a pitcher
--      may be in both pools, and a hitter who pitched a mop-up inning may be in the relief
--      pool.
--   4. Level: pitching components are summed over the pool members' free-agent days of
--      that kind only, and divided by the count of those days (pool_played_days). A relief
--      pool member's start is in neither pool_total nor pool_played_days of relief.
--      level_per_played_day = pool_total / pool_played_days. This mirrors slot-role
--      crediting in int_fantasy__started_player_days: a day is credited on one side only.
--   5. Every kind gets its rows. The output starts from a spine of the three kinds crossed
--      with their components and left-joins the pools, so an empty pool yields rows with
--      pool_players = 0, pool_played_days = 0 and a NULL level, not no rows (which an
--      inner join downstream would turn into players vanishing) and not 0 (which would say
--      replacement produces nothing).
-- Components only, never rates: AVG or ERA is computed from these totals downstream.
--
-- BIAS. Two, pulling opposite ways.
--   * The pool is players nobody rostered that date; a free agent who got added leaves
--     it. Replacement is therefore the never-owned remainder, probably lower than what a
--     manager could actually have had on the wire.
--   * Ranking by appearances picks the pitchers MLB teams used most, and teams use good
--     relievers most. The relief pool's ERA (3.49) is about what rostered relievers post
--     in relief while started (3.37), so a reliever earns little on ERA or WHIP here and
--     nearly all his value on saves, holds and strikeouts. Accepted in ADR 0009, which
--     also measures the alternatives: ranking by outs picks long men (4.20 outs an
--     appearance against a rostered reliever's 3.01), and pooling every free-agent relief
--     appearance gives a weaker ERA floor (4.24) but a longer outing still (3.58 outs).
--
-- SENSITIVITY. Measured on the 2026 season (12 teams) at N/2, N and 2N -- pool sizes of
-- 6, 12 and 24:
--   batting  AVG   .2410 / .2416 / .2420
--   start    outs  14.84 / 14.98 / 15.01   ERA 5.40 / 5.41 / 5.06   WHIP 1.50 / 1.48 / 1.42
--   relief   outs   2.68 /  2.80 /  2.83   ERA 3.18 / 3.49 / 3.58   WHIP 1.31 / 1.26 / 1.28
-- Started players, for scale: .254; 16.39 outs and ERA 3.89 in a start; 3.01 outs and ERA
-- 3.37 in relief. The size of an outing, which decides innings and strikeouts, barely
-- moves with the pool size in either kind. Relief ERA does (0.40 of a run across the
-- range, better the smaller the pool), which is the second bias above showing itself.
--
-- Like int_fantasy__transactions this carries no league_id or season (#28): it assumes
-- the one league-season loaded.

{{ config(materialized='table') }}

with scoring_dates as (

    select distinct scoring_date
    from {{ ref('int_fantasy__roster_days') }}

),

rostered_days as (

    select distinct
        mlbam_player_id,
        scoring_date
    from {{ ref('int_fantasy__roster_days') }}
    where mlbam_player_id is not null

),

free_agent_days as (

    select days.*
    from {{ ref('int_mlb__player_game_days') }} as days
    inner join scoring_dates
        on scoring_dates.scoring_date = days.game_date
    left join rostered_days
        on rostered_days.mlbam_player_id = days.mlbam_player_id
        and rostered_days.scoring_date = days.game_date
    where rostered_days.mlbam_player_id is null

),

player_totals as (

    select
        mlbam_player_id,
        sum(plate_appearances) as plate_appearances,
        sum(batters_faced) as batters_faced,
        sum(outs_recorded) as outs_recorded,
        sum(games_pitched) as games_pitched,
        sum(games_started) as games_started
    from free_agent_days
    group by mlbam_player_id

),

hitter_totals as (

    select
        mlbam_player_id,
        plate_appearances
    from player_totals
    where {{ fo_replacement_group(
        'plate_appearances', 'batters_faced', 'outs_recorded', 'games_pitched', 'games_started'
    ) }} = 'hitter'

),

batting_pool as (

    select
        mlbam_player_id,
        'batting' as day_kind
    from hitter_totals
    qualify row_number() over (
        order by plate_appearances desc, mlbam_player_id
    ) <= (select count(*) from {{ ref('int_fantasy__teams') }})

),

pitching_days as (

    select
        mlbam_player_id,
        {{ fo_pitching_day_kind('games_pitched', 'games_started') }} as day_kind,
        outs_recorded
    from free_agent_days

),

pitching_candidates as (

    select
        mlbam_player_id,
        day_kind,
        count(*) as kind_days,
        sum(coalesce(outs_recorded, 0)) as kind_outs
    from pitching_days
    where day_kind is not null
    group by mlbam_player_id, day_kind

),

pitching_pool as (

    select
        mlbam_player_id,
        day_kind
    from pitching_candidates
    qualify row_number() over (
        partition by day_kind
        order by kind_days desc, kind_outs desc, mlbam_player_id
    ) <= (select count(*) from {{ ref('int_fantasy__teams') }})

),

pool as (

    select * from batting_pool
    union all
    select * from pitching_pool

),

-- Only the side and kind each pool is credited for: a day is played on that side, in
-- that kind, or not at all.
pool_played_days as (

    select
        pool.day_kind,
        free_agent_days.*
    from free_agent_days
    inner join pool
        on pool.mlbam_player_id = free_agent_days.mlbam_player_id
    where case pool.day_kind
        when 'batting' then free_agent_days.games_batted > 0
        else {{ fo_pitching_day_kind('free_agent_days.games_pitched', 'free_agent_days.games_started') }} = pool.day_kind
    end

),

spine as (

    {%- for column in fo_batting_columns() %}
    select 'batting' as day_kind, '{{ column }}' as component
    union all
    {%- endfor %}
    {%- for column in fo_pitching_columns() %}
    select 'start' as day_kind, '{{ column }}' as component
    union all
    select 'relief' as day_kind, '{{ column }}' as component
        {{- '\n    union all' if not loop.last }}
    {%- endfor %}

),

pool_sizes as (

    select
        day_kind,
        count(*) as pool_players
    from pool
    group by day_kind

),

played_day_counts as (

    select
        day_kind,
        count(*) as pool_played_days
    from pool_played_days
    group by day_kind

),

-- One query per component rather than a pivot: the component lists are macros, and the
-- model names no column of its own.
pool_totals as (

    {%- for column in fo_batting_columns() %}
    select day_kind, '{{ column }}' as component, sum(coalesce({{ column }}, 0)) as pool_total
    from pool_played_days
    where day_kind = 'batting'
    group by day_kind
    union all
    {%- endfor %}
    {%- for column in fo_pitching_columns() %}
    select day_kind, '{{ column }}' as component, sum(coalesce({{ column }}, 0)) as pool_total
    from pool_played_days
    where day_kind in ('start', 'relief')
    group by day_kind
        {{- '\n    union all' if not loop.last }}
    {%- endfor %}

)

select
    spine.day_kind,
    spine.component,
    coalesce(pool_sizes.pool_players, 0) as pool_players,
    coalesce(played_day_counts.pool_played_days, 0) as pool_played_days,
    pool_totals.pool_total,
    pool_totals.pool_total / nullif(played_day_counts.pool_played_days, 0) as level_per_played_day
from spine
left join pool_sizes
    on pool_sizes.day_kind = spine.day_kind
left join played_day_counts
    on played_day_counts.day_kind = spine.day_kind
left join pool_totals
    on pool_totals.day_kind = spine.day_kind
    and pool_totals.component = spine.component
