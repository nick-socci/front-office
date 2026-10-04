-- What a replacement player produces per day played, for each kind of day, in each league
-- and season: one row per (platform, league_id, season, day_kind, component), the kind being
-- batting, start or relief. Every player's value is
-- measured against this (#11, #52): a player is worth what he did above what a free agent
-- would have done in the same playing time, and a pitcher's start is measured against a
-- free agent's start, his relief appearance against a free agent's relief appearance
-- (ADR 0008).
--
-- DEFINITION, everything per league and season (#28). Each pool is the top N MLB players of
-- its kind among those nobody in THAT LEAGUE had rostered, N being that league-season's own
-- number of fantasy teams (count of int_fantasy__teams, never a literal 12), joined in, not
-- read as one scalar over every league.
--   1. Free-agent days: rows of int_mlb__player_game_days, of the league-season's own MLB
--      season, on one of its scoring dates (any date of its int_fantasy__roster_days) where
--      the player is on none of ITS rosters that date. He may be rostered in another league
--      the same day and is still a free agent here.
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
--   5. Every kind gets its rows. The output starts from a spine of the league-seasons crossed
--      with the three kinds and their components and left-joins the pools, so an empty pool yields rows with
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
-- The sensitivity figures above are the 2026 league's; each league-season has its own.

{{ config(materialized='table') }}

with league_seasons as (

    select
        platform,
        league_id,
        season,
        count(*) as team_count
    from {{ ref('int_fantasy__teams') }}
    group by platform, league_id, season

),

scoring_dates as (

    select distinct
        platform,
        league_id,
        season,
        scoring_date
    from {{ ref('int_fantasy__roster_days') }}

),

rostered_days as (

    select distinct
        platform,
        league_id,
        season,
        mlbam_player_id,
        scoring_date
    from {{ ref('int_fantasy__roster_days') }}
    where mlbam_player_id is not null

),

-- days.* carries the MLB season; joining on it makes the league-season's season the MLB
-- season of every free-agent day (R4.6), so `season` here is both.
free_agent_days as (

    select
        scoring_dates.platform,
        scoring_dates.league_id,
        days.*
    from {{ ref('int_mlb__player_game_days') }} as days
    inner join scoring_dates
        on scoring_dates.scoring_date = days.game_date
        and scoring_dates.season = days.season
    left join rostered_days
        on rostered_days.platform = scoring_dates.platform
        and rostered_days.league_id = scoring_dates.league_id
        and rostered_days.season = scoring_dates.season
        and rostered_days.mlbam_player_id = days.mlbam_player_id
        and rostered_days.scoring_date = days.game_date
    where rostered_days.mlbam_player_id is null

),

player_totals as (

    select
        platform,
        league_id,
        season,
        mlbam_player_id,
        sum(plate_appearances) as plate_appearances,
        sum(batters_faced) as batters_faced,
        sum(outs_recorded) as outs_recorded,
        sum(games_pitched) as games_pitched,
        sum(games_started) as games_started
    from free_agent_days
    group by platform, league_id, season, mlbam_player_id

),

hitter_totals as (

    select
        platform,
        league_id,
        season,
        mlbam_player_id,
        plate_appearances
    from player_totals
    where {{ fo_replacement_group(
        'plate_appearances', 'batters_faced', 'outs_recorded', 'games_pitched', 'games_started'
    ) }} = 'hitter'

),

batting_pool as (

    select
        hitter_totals.platform,
        hitter_totals.league_id,
        hitter_totals.season,
        hitter_totals.mlbam_player_id,
        'batting' as day_kind
    from hitter_totals
    inner join league_seasons
        on league_seasons.platform = hitter_totals.platform
        and league_seasons.league_id = hitter_totals.league_id
        and league_seasons.season = hitter_totals.season
    qualify row_number() over (
        partition by hitter_totals.platform, hitter_totals.league_id, hitter_totals.season
        order by hitter_totals.plate_appearances desc, hitter_totals.mlbam_player_id
    ) <= league_seasons.team_count

),

pitching_days as (

    select
        platform,
        league_id,
        season,
        mlbam_player_id,
        {{ fo_pitching_day_kind('games_pitched', 'games_started') }} as day_kind,
        outs_recorded
    from free_agent_days

),

pitching_candidates as (

    select
        platform,
        league_id,
        season,
        mlbam_player_id,
        day_kind,
        count(*) as kind_days,
        sum(coalesce(outs_recorded, 0)) as kind_outs
    from pitching_days
    where day_kind is not null
    group by platform, league_id, season, mlbam_player_id, day_kind

),

pitching_pool as (

    select
        pitching_candidates.platform,
        pitching_candidates.league_id,
        pitching_candidates.season,
        pitching_candidates.mlbam_player_id,
        pitching_candidates.day_kind
    from pitching_candidates
    inner join league_seasons
        on league_seasons.platform = pitching_candidates.platform
        and league_seasons.league_id = pitching_candidates.league_id
        and league_seasons.season = pitching_candidates.season
    qualify row_number() over (
        partition by
            pitching_candidates.platform,
            pitching_candidates.league_id,
            pitching_candidates.season,
            pitching_candidates.day_kind
        order by
            pitching_candidates.kind_days desc,
            pitching_candidates.kind_outs desc,
            pitching_candidates.mlbam_player_id
    ) <= league_seasons.team_count

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
        on pool.platform = free_agent_days.platform
        and pool.league_id = free_agent_days.league_id
        and pool.season = free_agent_days.season
        and pool.mlbam_player_id = free_agent_days.mlbam_player_id
    where case pool.day_kind
        when 'batting' then free_agent_days.games_batted > 0
        else {{ fo_pitching_day_kind('free_agent_days.games_pitched', 'free_agent_days.games_started') }} = pool.day_kind
    end

),

spine as (

    select league_seasons.platform, league_seasons.league_id, league_seasons.season,
        kinds.day_kind, kinds.component
    from league_seasons
    cross join (
        {%- for column in fo_batting_columns() %}
        select 'batting' as day_kind, '{{ column }}' as component
        union all
        {%- endfor %}
        {%- for column in fo_pitching_columns() %}
        select 'start' as day_kind, '{{ column }}' as component
        union all
        select 'relief' as day_kind, '{{ column }}' as component
            {{- '\n        union all' if not loop.last }}
        {%- endfor %}
    ) as kinds

),

pool_sizes as (

    select
        platform,
        league_id,
        season,
        day_kind,
        count(*) as pool_players
    from pool
    group by platform, league_id, season, day_kind

),

played_day_counts as (

    select
        platform,
        league_id,
        season,
        day_kind,
        count(*) as pool_played_days
    from pool_played_days
    group by platform, league_id, season, day_kind

),

-- One query per component rather than a pivot: the component lists are macros, and the
-- model names no column of its own.
pool_totals as (

    {%- for column in fo_batting_columns() %}
    select platform, league_id, season, day_kind, '{{ column }}' as component,
        sum(coalesce({{ column }}, 0)) as pool_total
    from pool_played_days
    where day_kind = 'batting'
    group by platform, league_id, season, day_kind
    union all
    {%- endfor %}
    {%- for column in fo_pitching_columns() %}
    select platform, league_id, season, day_kind, '{{ column }}' as component,
        sum(coalesce({{ column }}, 0)) as pool_total
    from pool_played_days
    where day_kind in ('start', 'relief')
    group by platform, league_id, season, day_kind
        {{- '\n    union all' if not loop.last }}
    {%- endfor %}

)

select
    spine.platform,
    spine.league_id,
    spine.season,
    spine.day_kind,
    spine.component,
    coalesce(pool_sizes.pool_players, 0) as pool_players,
    coalesce(played_day_counts.pool_played_days, 0) as pool_played_days,
    pool_totals.pool_total,
    pool_totals.pool_total / nullif(played_day_counts.pool_played_days, 0) as level_per_played_day
from spine
left join pool_sizes
    on pool_sizes.platform = spine.platform
    and pool_sizes.league_id = spine.league_id
    and pool_sizes.season = spine.season
    and pool_sizes.day_kind = spine.day_kind
left join played_day_counts
    on played_day_counts.platform = spine.platform
    and played_day_counts.league_id = spine.league_id
    and played_day_counts.season = spine.season
    and played_day_counts.day_kind = spine.day_kind
left join pool_totals
    on pool_totals.platform = spine.platform
    and pool_totals.league_id = spine.league_id
    and pool_totals.season = spine.season
    and pool_totals.day_kind = spine.day_kind
    and pool_totals.component = spine.component
