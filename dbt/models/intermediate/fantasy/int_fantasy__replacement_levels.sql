-- What a replacement player produces per day played, for each replacement group: one row
-- per (replacement_group, component). Every player's value is measured against this
-- (#11): a player is worth what he did above what a free agent would have done in the
-- same playing time.
--
-- DEFINITION. The pool is the top N MLB players of each group among those nobody in the
-- league had rostered, N being the number of fantasy teams (count of int_fantasy__teams,
-- never a literal 12).
--   1. Free-agent days: rows of int_mlb__player_game_days on a scoring date (any date in
--      int_fantasy__roster_days) where the player is on no fantasy roster that date.
--   2. Group of a player over his free-agent days, by the fo_replacement_group macro:
--      hitter, SP or RP. The same rule dim_players uses for a player with no position.
--   3. Pool: top N per group by plate appearances (hitter) or outs recorded (SP, RP)
--      over those days; ties broken by mlbam_player_id so the pool is deterministic.
--   4. Level: a group is credited for one side only, mirroring slot-role crediting in
--      int_fantasy__started_player_days: batting components for hitter, pitching for SP
--      and RP. A played day is one-sided likewise (games_batted > 0 for hitter,
--      games_pitched > 0 for SP and RP), so a hitter's mop-up inning is neither a played
--      day nor a component. level_per_played_day = pool_total / pool_played_days.
--   5. Every group gets its rows. The output starts from a spine of the three groups
--      crossed with their components and left-joins the pool, so an empty pool yields
--      rows with pool_players = 0, pool_played_days = 0 and a NULL level, not no rows
--      (which an inner join downstream would turn into players vanishing) and not 0
--      (which would say replacement produces nothing).
-- Components only, never rates: AVG or ERA is computed from these totals downstream.
--
-- BIAS. The pool is players nobody rostered that date; a free agent who got added
-- leaves it. Replacement here is therefore the never-owned remainder, and is probably
-- lower than a replacement a manager could actually have had on the wire.
--
-- SENSITIVITY: filled in by task 6 (levels measured at N/2, N and 2N).
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

player_groups as (

    select
        mlbam_player_id,
        {{ fo_replacement_group(
            'plate_appearances', 'batters_faced', 'outs_recorded', 'games_pitched', 'games_started'
        ) }} as replacement_group,
        plate_appearances,
        outs_recorded
    from player_totals

),

pool as (

    select
        mlbam_player_id,
        replacement_group
    from player_groups
    qualify row_number() over (
        partition by replacement_group
        order by
            case replacement_group when 'hitter' then plate_appearances else outs_recorded end desc,
            mlbam_player_id
    ) <= (select count(*) from {{ ref('int_fantasy__teams') }})

),

-- Only the side each group is credited for: a day is played on that side or not at all.
pool_played_days as (

    select
        pool.replacement_group,
        free_agent_days.*
    from free_agent_days
    inner join pool
        on pool.mlbam_player_id = free_agent_days.mlbam_player_id
    where case pool.replacement_group
        when 'hitter' then free_agent_days.games_batted > 0
        else free_agent_days.games_pitched > 0
    end

),

spine as (

    {%- for column in fo_batting_columns() %}
    select 'hitter' as replacement_group, '{{ column }}' as component
    union all
    {%- endfor %}
    {%- for column in fo_pitching_columns() %}
    select 'SP' as replacement_group, '{{ column }}' as component
    union all
    select 'RP' as replacement_group, '{{ column }}' as component
        {{- '\n    union all' if not loop.last }}
    {%- endfor %}

),

pool_sizes as (

    select
        replacement_group,
        count(*) as pool_players
    from pool
    group by replacement_group

),

played_day_counts as (

    select
        replacement_group,
        count(*) as pool_played_days
    from pool_played_days
    group by replacement_group

),

-- One query per component rather than a pivot: the component lists are macros, and the
-- model names no column of its own.
pool_totals as (

    {%- for column in fo_batting_columns() %}
    select replacement_group, '{{ column }}' as component, sum(coalesce({{ column }}, 0)) as pool_total
    from pool_played_days
    where replacement_group = 'hitter'
    group by replacement_group
    union all
    {%- endfor %}
    {%- for column in fo_pitching_columns() %}
    select replacement_group, '{{ column }}' as component, sum(coalesce({{ column }}, 0)) as pool_total
    from pool_played_days
    where replacement_group in ('SP', 'RP')
    group by replacement_group
        {{- '\n    union all' if not loop.last }}
    {%- endfor %}

)

select
    spine.replacement_group,
    spine.component,
    coalesce(pool_sizes.pool_players, 0) as pool_players,
    coalesce(played_day_counts.pool_played_days, 0) as pool_played_days,
    pool_totals.pool_total,
    pool_totals.pool_total / nullif(played_day_counts.pool_played_days, 0) as level_per_played_day
from spine
left join pool_sizes
    on pool_sizes.replacement_group = spine.replacement_group
left join played_day_counts
    on played_day_counts.replacement_group = spine.replacement_group
left join pool_totals
    on pool_totals.replacement_group = spine.replacement_group
    and pool_totals.component = spine.component
